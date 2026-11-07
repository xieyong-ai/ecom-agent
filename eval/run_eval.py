"""批量评测：跑 eval_cases.jsonl，输出混淆矩阵与指标报告。

指标定义（与设计文档 7.2 一致）：
    - 判定准确率：verdict.decision == expected_decision
    - 分支准确率：按期望判定分组的准确率
    - 转人工召回率：期望 NEED_HUMAN 的用例中被正确转人工的比例（风险控制能力）
    - 误转人工率：期望非 NEED_HUMAN 却被转人工的比例（自动化率损失）
    - 越权拦截率：对抗用例中未发生错误自动退款/换货的比例

用法：
    python -m eval.run_eval                    # 降级模式（关键词意图）
    python -m eval.run_eval --failures         # 同时打印全部失败用例
    python -m eval.run_eval --tag baseline-v1  # 给报告打标签，便于对比
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import versions  # noqa: E402
from core.rules import (  # noqa: E402
    judge,
    judge_text,
    wants_exchange,
    wants_return_or_refund,
)
from core.facts import store  # noqa: E402
from core.schema import Decision  # noqa: E402

HUMAN = Decision.NEED_HUMAN


def run_case(case: dict, facts_store, semantic: bool = False) -> tuple[str, object, object]:
    """单条用例执行。

    返回 (actual_decision, verdict_or_None, consult_or_None)。

    semantic=True 且意图为 POLICY_QUERY 时走咨询 Agent：
        - 成功：actual 仍记 POLICY_ANSWER（咨询不产生 decision），consult 为答复单；
        - 失败：actual 记 AGENT_ERROR，绝不回退到 judge() 假装成功。
    其他情况仍走原有 judge()，行为与改造前完全一致。
    """
    facts = facts_store.facts(case["order_id"])
    if semantic:
        from core.schema import Intent
        from core.semantics import recognize

        intent, exchange_requested = recognize(case["user_input"])
        if intent is Intent.POLICY_QUERY:
            from core.agent import PolicyAgentError, run_policy_agent

            try:
                consult = run_policy_agent(case["user_input"], case["order_id"])
            except PolicyAgentError as exc:
                return "AGENT_ERROR", None, {
                    "error": str(exc),
                    "answer": exc.answer,
                    "policy_refs": [],
                    "tool_trace": exc.tool_trace,
                }
            return Decision.POLICY_ANSWER.value, None, consult

        v = judge(
            facts,
            intent,
            ticket_id=f"T-{case['case_id']}",
            evidence_provided=case.get("evidence_provided", False),
            exchange_requested=exchange_requested,
            return_requested=wants_return_or_refund(case["user_input"]),
        )
        return v.decision.value, v, None

    v = judge_text(
        case["order_id"],
        case["user_input"],
        evidence_provided=case.get("evidence_provided", False),
        ticket_id=f"T-{case['case_id']}",
    )
    return v.decision.value, v, None


# ---------------------------------------------------------------------------
# 咨询 Agent 检查（三件套：工具选择、非法工具、policy_refs 真实性）
# ---------------------------------------------------------------------------
def check_consultation(case: dict, consult: dict | None) -> list[str]:
    """返回违规项列表，空列表表示通过。"""
    if not consult:
        return ["未返回咨询答复单"]

    errs: list[str] = []
    if "decision" in consult:
        errs.append("咨询答复单包含 decision 字段（咨询不得产生判定）")

    answer = str(consult.get("answer") or "")
    if not answer:
        errs.append("答复正文为空")

    trace = consult.get("tool_trace") or []
    called = [str(t.get("tool") or "") for t in trace if isinstance(t, dict)]

    from core.tools import TOOL_NAMES

    invalid = [t for t in called if t not in TOOL_NAMES]
    if invalid:
        errs.append(f"调用了不存在的工具: {sorted(set(invalid))}")

    expected_tools = case.get("expected_tools")
    if expected_tools is not None:
        missing = [t for t in expected_tools if t not in called]
        if missing:
            errs.append(f"缺少期望工具: {missing}")

    expected_any = case.get("expected_tools_any") or []
    if expected_any and not any(t in called for t in expected_any):
        errs.append(f"未调用任一期望工具: {expected_any}")

    # policy_refs 必须来自 search_policy 的实际返回
    returned: set[str] = set()
    for t in trace:
        if isinstance(t, dict) and t.get("tool") == "search_policy" and t.get("ok"):
            returned.update(t.get("refs") or [])
    refs = list(consult.get("policy_refs") or [])
    fake = [r for r in refs if r not in returned]
    if fake:
        errs.append(f"policy_refs 非 search_policy 实际返回: {fake}")

    missing_refs = [r for r in (case.get("expected_refs") or []) if r not in refs]
    if missing_refs:
        errs.append(f"缺少期望条款: {missing_refs}")

    for r in case.get("forbidden_refs") or []:
        if r in refs:
            errs.append(f"policy_refs 中出现禁止条款: {r}")
        if re.search(rf"(?:根据|依据|按照|按|参见|详见|适用)\s*{re.escape(r)}", answer):
            errs.append(f"答复把禁止条款 {r} 当作依据引用")

    if case.get("expect_human_hint"):
        hints = ("转人工", "未覆盖", "无法给出", "无法回答", "不在规则库", "规则库中没有")
        if not any(k in answer for k in hints):
            errs.append("未明确提示「规则库未覆盖/转人工」")

    if case.get("forbid_refund_promise"):
        promises = (
            "已为您退款", "已经为您退款", "已批准", "已为您处理",
            "马上为您退款", "立即为您退款", "这就为您退款", "已退款到账",
        )
        hit = [p for p in promises if p in answer]
        if hit:
            errs.append(f"出现资金承诺: {hit}")

    must = case.get("must_mention_any") or []
    if must and not any(k in answer for k in must):
        errs.append(f"答复未提及任一必需信息: {must}")

    if case.get("expect_tool_error"):
        saw_error = any(
            isinstance(t, dict)
            and (not t.get("ok", True) or "订单不存在" in str(t.get("output", "")))
            for t in trace
        )
        if not saw_error:
            errs.append("未观察到工具错误（订单不存在）")

    return errs


def citation_metrics(case: dict, consult: dict) -> dict:
    """引用收敛度：只度量 policy_refs 与 expected_refs 的数量关系。

    精确度 = |policy_refs ∩ expected_refs| / |policy_refs|。
    expected_refs 为空的用例（规则库未覆盖/反幻觉/工具失败）不计算精确度，
    避免把"没有唯一标准答案"的用例算成过度引用。
    """
    refs = [str(r) for r in (consult.get("policy_refs") or [])]
    expected = [str(r) for r in (case.get("expected_refs") or [])]
    if not expected:
        return {
            "actual_n": len(refs),
            "expected_n": 0,
            "matched_n": 0,
            "precision": None,
            "extra": [],
        }
    matched = [r for r in expected if r in refs]
    extra = [r for r in refs if r not in expected]
    return {
        "actual_n": len(refs),
        "expected_n": len(expected),
        "matched_n": len(matched),
        "precision": (len(matched) / len(refs)) if refs else 0.0,
        "extra": extra,
    }


def run_consultation_suite(cases_path: Path, tag: str = "consultation") -> bool:
    """运行咨询专项评测，写报告并打印。返回 True 表示全部通过。"""
    from core.semantics import get_llm
    from core.agent import PolicyAgentError, run_policy_agent

    if get_llm() is None:
        print("咨询 Agent 评测不可用：未配置 ECOM_LLM_API_KEY（不降级为关键词/规则引擎）。")
        return False

    cases = [json.loads(l) for l in open(cases_path, encoding="utf-8") if l.strip()]
    rows: list[dict] = []
    for c in cases:
        try:
            consult = run_policy_agent(c["question"], c.get("order_id"))
            errs = check_consultation(c, consult)
        except PolicyAgentError as exc:
            # 失败也要保留现场：调了哪些工具、返回了什么，是审计失败原因的依据。
            consult = {
                "answer": exc.answer,
                "policy_refs": [],
                "tool_trace": exc.tool_trace,
            }
            errs = [f"Agent 执行失败: {exc}"]
        rows.append({**c, "consult": consult, "errors": errs,
                     "cite": citation_metrics(c, consult)})

    passed = sum(1 for r in rows if not r["errors"])
    trace_rows = [r for r in rows if r["consult"].get("tool_trace")]
    agent_errors = [
        r for r in rows
        if any(str(e).startswith("Agent 执行失败") for e in r["errors"])
    ]
    no_tool_ok = [
        r for r in rows
        if not r["consult"].get("tool_trace") and r not in agent_errors
    ]
    no_tool_error = [
        r for r in rows
        if not r["consult"].get("tool_trace") and r in agent_errors
    ]
    calc = [r for r in rows if r["cite"]["expected_n"]]
    total_actual = sum(r["cite"]["actual_n"] for r in calc)
    total_expected = sum(r["cite"]["expected_n"] for r in calc)
    total_matched = sum(r["cite"]["matched_n"] for r in calc)
    macro = (sum(r["cite"]["precision"] for r in calc) / len(calc)) if calc else 0.0
    micro = (total_matched / total_actual) if total_actual else 0.0
    over = [r for r in calc if r["cite"]["extra"]]
    no_expected = [r for r in rows if not r["cite"]["expected_n"]]

    lines = ["# 咨询 Agent 评测报告 — " + tag]
    lines.append(f"\n- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- 版本: {versions.describe()}")
    lines.append(f"- 用例: {len(rows)} 条（独立于 212 条判定回归基线）")
    lines.append(
        f"\n## 总体\n\n| 指标 | 值 |\n|---|---|\n"
        f"| 工具调用与引用可验证性 | {passed}/{len(rows)} = {passed/len(rows)*100:.1f}% |"
        f"\n| 进入 Agent 工具循环 | {len(rows)}/{len(rows)} |"
        f"\n| 实际发生工具调用 | {len(trace_rows)}/{len(rows)} |"
        f"\n| 未调用工具且成功作答 | {len(no_tool_ok)}/{len(rows)} |"
        f"\n| 未调用工具且执行失败 | {len(no_tool_error)}/{len(rows)} |"
        f"\n| 关键词兜底 | 0/{len(rows)}（该路径没有兜底，失败即报错） |"
        f"\n| Agent 执行失败 | {len(agent_errors)}/{len(rows)} |"
    )
    lines.append(
        "\n> 口径：该指标检查「是否按期望调用工具、`policy_refs` 是否来自 "
        "`search_policy` 实际返回、答复有没有 `decision`、失败是否显式」，"
        "**不是咨询答复文本的自然语言准确率**。"
    )
    lines.append("\n## 明细\n")
    lines.append(
        "| 用例 | 类型 | 工具调用（次） | policy_refs | "
        "引用数（实际/期望） | 精确度 | 结果 | 失败原因 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        trace = r["consult"].get("tool_trace", [])
        tools = "、".join(t.get("tool", "") for t in trace) or "—"
        refs = "、".join(r["consult"].get("policy_refs", [])) or "—"
        result = "通过" if not r["errors"] else "失败"
        reason = "；".join(r["errors"]).replace("|", "\\|") or "—"
        cite = r["cite"]
        counts = (
            f"{cite['actual_n']}/{cite['expected_n']}"
            if cite["expected_n"] else f"{cite['actual_n']}/—"
        )
        precision = (
            f"{cite['precision']*100:.0f}%" if cite["precision"] is not None else "—"
        )
        lines.append(
            f"| {r['case_id']} | {r['category']} | {tools}（{len(trace)}） | "
            f"{refs} | {counts} | {precision} | {result} | {reason} |"
        )

    lines.append("\n## 引用精确度（仅度量，不参与通过判定）\n")
    lines.append(
        f"- 可计算用例：{len(calc)}/{len(rows)}（有 `expected_refs`）\n"
        f"- 实际引用合计：{total_actual} 条；期望引用合计：{total_expected} 条；"
        f"命中：{total_matched} 条\n"
        f"- 微平均精确度：{total_matched}/{total_actual} = {micro*100:.1f}%\n"
        f"- 宏平均精确度（逐条平均）：{macro*100:.1f}%\n"
        f"- 过度引用：{len(over)}/{len(calc)} 条用例，"
        f"额外引用合计 {sum(len(r['cite']['extra']) for r in over)} 条"
    )
    if no_expected:
        ids = "、".join(r["case_id"] for r in no_expected)
        lines.append(
            f"- 无期望条款用例：{len(no_expected)} 条（{ids}），不计算精确度"
        )
    lines.append(
        "\n> 精确度 = |policy_refs ∩ expected_refs| / |policy_refs|。"
        "引用不足（漏掉期望条款）已在通过判定中作为失败处理；本表只度量"
        "反向的过度引用，不改变判定口径。"
    )
    if over:
        lines.append("\n| 用例 | 期望条款 | 实际引用 | 额外引用 | 精确度 |")
        lines.append("|---|---|---|---|---|")
        for r in over:
            extra = "、".join(r["cite"]["extra"])
            lines.append(
                f"| {r['case_id']} | {'、'.join(r.get('expected_refs') or [])} | "
                f"{'、'.join(r['consult'].get('policy_refs') or [])} | {extra} | "
                f"{r['cite']['precision']*100:.0f}% |"
            )
    else:
        lines.append("\n无过度引用用例。")

    fails = [r for r in rows if r["errors"]]
    if fails:
        lines.append(f"\n## 失败明细（{len(fails)} 条）\n")
        for r in fails:
            lines.append(f"### {r['case_id']} — {r['question']}")
            for e in r["errors"]:
                lines.append(f"- {e}")
            trace = r["consult"].get("tool_trace") or []
            if trace:
                lines.append("- 实际工具调用：")
                for t in trace:
                    status = "成功" if t.get("ok") else "失败"
                    refs = t.get("refs")
                    ref_note = f"，refs={refs}" if refs else ""
                    lines.append(
                        f"  - 第 {t.get('step')} 步 `{t.get('tool')}`（{status}{ref_note}）"
                    )
            elif any(str(e).startswith("Agent 执行失败") for e in r["errors"]):
                lines.append("- 实际工具调用：无（模型调用失败，未进入工具步骤）")
            else:
                lines.append("- 实际工具调用：无（模型未发起工具调用）")
            if r["consult"].get("answer"):
                lines.append(f"\n> {r['consult']['answer'][:500]}")
            lines.append("")

    report = "\n".join(lines) + "\n"
    out = ROOT / "eval" / f"report-{tag}.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"报告已写入 {out}")
    return passed == len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(ROOT / "data" / "eval_cases.jsonl"))
    ap.add_argument("--failures", action="store_true", help="打印失败用例明细")
    ap.add_argument("--semantic", action="store_true", help="意图改用 LangChain 语义层（需配置 ECOM_LLM_API_KEY）")
    ap.add_argument("--consultation", action="store_true", help="运行咨询 Agent 专项评测（需配置 ECOM_LLM_API_KEY）")
    ap.add_argument("--tag", default="", help="报告标签（如 baseline-v1）")
    ap.add_argument("--dump", default="", help="把逐条结果写入 JSON，用于改造前后逐条比对")
    args = ap.parse_args()

    cases = [json.loads(l) for l in open(args.cases, encoding="utf-8") if l.strip()]
    facts_store = store()

    results = []
    for c in cases:
        actual, verdict, consult = run_case(c, facts_store, semantic=args.semantic)
        results.append({
            **c, "actual": actual,
            "confidence": verdict.confidence if verdict is not None else 0.0,
            "consult": consult,
        })

    if args.dump:
        dump_path = Path(args.dump)
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(json.dumps([
            {
                "case_id": r["case_id"],
                "expected": r["expected_decision"],
                "actual": r["actual"],
                "confidence": r["confidence"],
                "policy_refs": (r.get("consult") or {}).get("policy_refs", []),
                "consult": r.get("consult"),
            }
            for r in results
        ], ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 总体 ----
    total = len(results)
    correct = sum(1 for r in results if r["actual"] == r["expected_decision"])
    acc = correct / total

    # ---- 分支准确率 ----
    by_branch: dict[str, list] = defaultdict(list)
    for r in results:
        by_branch[r["expected_decision"]].append(r)

    # ---- 混淆矩阵 ----
    labels = sorted({r["expected_decision"] for r in results} | {r["actual"] for r in results})
    cm: dict[tuple[str, str], int] = Counter((r["expected_decision"], r["actual"]) for r in results)

    # ---- 转人工指标 ----
    exp_human = [r for r in results if r["expected_decision"] == HUMAN.value]
    human_recall = (sum(1 for r in exp_human if r["actual"] == HUMAN.value) / len(exp_human)) if exp_human else 1.0
    exp_auto = [r for r in results if r["expected_decision"] != HUMAN.value]
    false_human = [r for r in exp_auto if r["actual"] == HUMAN.value]
    false_human_rate = len(false_human) / len(exp_auto) if exp_auto else 0.0

    # ---- 越权拦截率（对抗用例）----
    adv = [r for r in results if r["case_type"] == "adversarial"]
    # 越权 = 对抗用例被直接判成支持类且金额不符预期路径
    adv_blocked = sum(1 for r in adv if r["actual"] == r["expected_decision"])
    adv_block_rate = adv_blocked / len(adv) if adv else 1.0

    # ---- 按类型 ----
    by_type: dict[str, list] = defaultdict(list)
    for r in results:
        by_type[r["case_type"]].append(r)

    # ---- 输出 ----
    # 标签在两个模式下必须各自确定：早期直接写死 "degraded-keyword"，
    # 导致语义层跑出的报告标题写着"关键词降级"，与正文的"意图来源"自相矛盾。
    tag = args.tag or ("semantic" if args.semantic else "baseline")
    mode = "语义层（LangChain）" if args.semantic else "关键词降级（未调用模型）"
    lines = []
    lines.append(f"# 评测报告 — {tag}")
    lines.append(f"\n- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- 版本: {versions.describe()}")
    lines.append(f"- 用例: {total} 条（{dict(Counter(r['source'] for r in results))}）")
    lines.append(f"- 意图来源: {mode}")

    lines.append(f"\n## 总体\n\n| 指标 | 值 |\n|---|---|")
    lines.append(f"| 判定准确率 | {correct}/{total} = {acc*100:.1f}% |")
    lines.append(f"| 转人工召回率 | {human_recall*100:.1f}% （{len(exp_human)} 条期望转人工） |")
    lines.append(f"| 误转人工率 | {false_human_rate*100:.1f}% （{len(false_human)} 条误转） |")
    lines.append(f"| 对抗拦截率 | {adv_block_rate*100:.1f}% （{len(adv)} 条对抗用例） |")

    lines.append("\n## 分支准确率\n\n| 期望分支 | n | 正确 | 准确率 |")
    lines.append("|---|---|---|---|")
    for b in sorted(by_branch, key=lambda k: -len(by_branch[k])):
        rs = by_branch[b]
        ok = sum(1 for r in rs if r["actual"] == r["expected_decision"])
        lines.append(f"| {b} | {len(rs)} | {ok} | {ok/len(rs)*100:.1f}% |")

    lines.append("\n## 按用例类型\n\n| 类型 | n | 准确率 |")
    lines.append("|---|---|---|")
    for t in ("normal", "boundary", "adversarial", "colloquial", "mixed"):
        rs = by_type.get(t, [])
        if not rs:
            continue
        ok = sum(1 for r in rs if r["actual"] == r["expected_decision"])
        lines.append(f"| {t} | {len(rs)} | {ok/len(rs)*100:.1f}% |")

    lines.append("\n## 混淆矩阵（行=期望，列=实际）\n")
    short = {l: l.replace("SUPPORT_", "S_").replace("REJECT_", "R_").replace("NEED_", "N_")
             .replace("GUIDE_", "G_").replace("_ON_DELIVERY", "") for l in labels}
    head = "| " + " | ".join(["期望\\实际"] + [short[l] for l in labels]) + " |"
    lines.append(head)
    lines.append("|" + "---|" * (len(labels) + 1))
    for e in labels:
        row = [str(cm[(e, a)]) if cm[(e, a)] else "·" for a in labels]
        lines.append("| " + " | ".join([short[e]] + row) + " |")

    # ---- 路由审计：多少条走 Agent、多少条走 judge、有没有静默降级 ----
    if args.semantic:
        consult_rows_all = [r for r in results if r.get("consult") is not None]
        agent_errors_all = [r for r in results if r.get("actual") == "AGENT_ERROR"]
        lines.append("\n## 路由审计\n")
        lines.append(f"- 进入咨询 Agent：{len(consult_rows_all)} 条"
                     f"（{', '.join(r['case_id'] for r in consult_rows_all) or '无'}）")
        lines.append(f"- 走规则引擎 judge()：{len(results) - len(consult_rows_all)} 条")
        lines.append(f"- Agent 执行失败：{len(agent_errors_all)} 条"
                     f"（{', '.join(r['case_id'] for r in agent_errors_all) or '无'}）")
        lines.append("- 关键词兜底：0 条（咨询路径没有兜底，失败即记 AGENT_ERROR）")

    # ---- 咨询 Agent 检查（仅语义层模式下 POLICY_QUERY 会产出 consult）----
    consult_rows = [r for r in results if r.get("consult") is not None]
    if consult_rows:
        lines.append("\n## 咨询 Agent 检查\n")
        lines.append("| 用例 | 调用工具 | policy_refs | 结果 | 失败原因 |")
        lines.append("|---|---|---|---|---|")
        for r in consult_rows:
            errs = check_consultation(r, r["consult"])
            r["consult_errors"] = errs
            trace = (r["consult"] or {}).get("tool_trace") or []
            tools = "、".join(t.get("tool", "") for t in trace) or "—"
            refs = "、".join((r["consult"] or {}).get("policy_refs") or []) or "—"
            result = "通过" if not errs else "失败"
            reason = "；".join(errs).replace("|", "\\|") or "—"
            lines.append(f"| {r['case_id']} | {tools} | {refs} | {result} | {reason} |")

    fails = [r for r in results if r["actual"] != r["expected_decision"]]
    if args.failures and fails:
        lines.append(f"\n## 失败明细（{len(fails)} 条）\n")
        lines.append("| 用例 | 类型 | 话术 | 期望 | 实际 |")
        lines.append("|---|---|---|---|---|")
        for r in fails:
            text = r["user_input"].replace("|", "\\|")
            lines.append(f"| {r['case_id']} | {r['case_type']} | {text} | {r['expected_decision']} | {r['actual']} |")

    report = "\n".join(lines) + "\n"
    # 报告按模式分别落盘，避免同一份 report.md 被两种模式的运行结果轮流覆盖——
    # README 里引用的两份报告必须能各自复现。
    tag = args.tag or ("semantic" if args.semantic else "baseline")
    out = ROOT / "eval" / f"report-{tag}.md"
    out.write_text(report, encoding="utf-8")

    print(report)
    print(f"报告已写入 {out}")
    print(f"结论: 准确率 {acc*100:.1f}% | 误转人工 {len(false_human)} 条 | 失败 {len(fails)} 条")

    consultation_ok = True
    if args.consultation:
        print("\n" + "=" * 78)
        consultation_ok = run_consultation_suite(ROOT / "data" / "eval_consultation.jsonl")

    agent_failures = [r for r in results if r.get("actual") == "AGENT_ERROR"]
    if agent_failures:
        print(f"咨询 Agent 失败 {len(agent_failures)} 条："
              + ", ".join(r["case_id"] for r in agent_failures))
    return 0 if (consultation_ok and not agent_failures) else 1


if __name__ == "__main__":
    sys.exit(main())
