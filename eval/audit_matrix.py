"""规则矩阵审计：穷举输入组合，检查判定单是否自洽。

评测（run_eval.py）回答"判得对不对"，本脚本回答"判出来的东西本身有没有毛病"。
两者的用例来源不同：评测用的是 209 条人工/半自动标注的话术，覆盖面受限于
标注者想到的场景；这里直接对输入空间做笛卡尔积，用不变量而非标准答案做断言，
能扫到标注集覆盖不到的边角（如 0 元订单、签收 0 天、例外类目 + 质量主张）。

四条断言（全部来自 core/schema.py 的 Verdict 契约与规则库原文）：
    1. 不变量：拒绝类不得带退款金额、支持类必须带正金额、转人工必须走 HUMAN 路径……
    2. 条款可追溯：每张判定单引用的 R-xxx，必须能在 data/policies.md 里找到原文
    3. 退款金额不得超过实付金额
    4. 文案不越界：不得断言事实层没有核实过的内容（如"商品未拆封"）

用法：
    python -m eval.audit_matrix            # 扫描并汇总
    python -m eval.audit_matrix --verbose  # 打印每条违规的输入组合
退出码非 0 表示存在违规，可直接接入 CI。
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.facts import Facts  # noqa: E402
from core.rules import judge  # noqa: E402
from core.schema import Decision, Intent  # noqa: E402

STATUSES = ["已签收", "已发货", "待发货", "待付款", "已取消", "已退款"]
DAYS = [None, 0, 1, 7, 8, 15, 16, 30, 31, 40]
AMOUNTS = [0.0, 0.01, 199.0, 2000.0, 5800.0]

# 文案里出现即代表"替事实下结论"的说法：事实层没有对应字段，一律不该出现
FORBIDDEN_CLAIMS = ("商品未拆封", "未拆封")


def _facts(status: str, days, amount: float, exempt: bool, disputed: bool) -> Facts:
    return Facts(
        order={
            "order_id": "AUDIT",
            "status": status,
            "after_sale": [],
            "items": [{"name": "审计商品", "exempt_reason": "生鲜易腐类" if exempt else None}],
        },
        days_since_delivery=days,
        is_exempt=exempt,
        exempt_reason="生鲜易腐类" if exempt else None,
        amount=amount,
        logistics_disputed=disputed,
    )


def _policy_refs() -> set[str]:
    md = (ROOT / "data" / "policies.md").read_text(encoding="utf-8")
    return {
        m.group(1)
        for m in re.finditer(r"^#{2,4}\s+.*?(R-\d+).*?$", md, flags=re.M)
    }


def combos():
    """按订单状态过滤掉不可能的输入（未签收订单不会同时有签收天数）。

    return_requested 也是 judge() 的输入之一，必须进笛卡尔积：它在途分支里
    决定"引导拒收"还是"转物流客服"，漏掉它等于这一段逻辑没有受审计。
    """
    for status, intent, days, amount, exempt, disputed, evidence, exchange, ret in itertools.product(
        STATUSES, Intent, DAYS, AMOUNTS, [False, True], [False, True], [False, True], [False, True],
        [None, False, True],
    ):
        if (status == "已签收") != (days is not None):
            continue
        if disputed and status != "已签收":
            continue
        yield _facts(status, days, amount, exempt, disputed), intent, evidence, exchange, ret


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="打印每条违规的输入组合")
    args = ap.parse_args()

    known_refs = _policy_refs()
    issues: list[tuple[str, str, str]] = []
    decisions: Counter[str] = Counter()
    total = 0

    for facts, intent, evidence, exchange, ret in combos():
        total += 1
        v = judge(facts, intent, ticket_id="T-AUDIT",
                  evidence_provided=evidence, exchange_requested=exchange,
                  return_requested=ret)
        decisions[v.decision.value] += 1
        key = (
            f"{facts.status}/意图={intent.value}/距签收={facts.days_since_delivery}"
            f"/金额={facts.amount}/例外={facts.is_exempt}/争议={facts.logistics_disputed}"
            f"/凭证={evidence}/换货={exchange}/退货诉求={ret}"
        )

        for err in v.validate():
            issues.append((key, "INVARIANT", err))
        for ref in v.policy_refs:
            if ref not in known_refs:
                issues.append((key, "MISSING_REF", f"{ref} 在 policies.md 中无对应条目"))
        if v.refund_amount > facts.amount + 1e-6:
            issues.append((key, "OVER_REFUND", f"退 {v.refund_amount} > 实付 {facts.amount}"))
        if v.decision in (Decision.SUPPORT_RETURN, Decision.SUPPORT_REFUND_ONLY) and v.refund_amount <= 0:
            issues.append((key, "NO_AMOUNT", f"{v.decision.value} 未携带退款金额"))
        for claim in FORBIDDEN_CLAIMS:
            if claim in v.reason:
                issues.append((key, "UNVERIFIED_CLAIM", f"文案断言「{claim}」，事实层无此字段"))

    print(f"组合总数 {total}（状态 × 意图 × 天数 × 金额 × 例外类目 × 签收争议 × 凭证 × 换货 × 退货诉求）")
    print(f"未覆盖的判定分支: {sorted(set(d.value for d in Decision) - set(decisions)) or '无'}")
    print("分支命中分布:")
    for name, n in sorted(decisions.items()):
        print(f"  {name:<26} {n}")

    if not issues:
        print("\n审计结果: 全部通过（0 违规）")
        return 0

    print(f"\n审计结果: {len(issues)} 条违规")
    for kind, n in Counter(k for _, k, _ in issues).items():
        print(f"  {kind}: {n}")
    if args.verbose:
        print()
        for key, kind, msg in issues:
            print(f"[{kind}] {key}\n    {msg}")
    else:
        print("  加 --verbose 查看每条违规的输入组合")
    return 1


if __name__ == "__main__":
    sys.exit(main())
