"""把外部公开/授权语料导入为评测用例（不联网、不改动既有 212 条基线）。

为什么要有这个脚本：
    公开数据集的字段名、标注口径、隐私内容各不相同，直接复制进仓库既不可
    复现，也不合规。这个脚本把"导入"拆成可审计的四步：
        读取 → 清洗（脱敏）→ 校验（枚举/条款/重复）→ 落盘 + 记账
    每一步都留下记录，数据从哪来、删了什么、丢了多少条，都能回答。

输入格式（JSONL，一行一条）：
    {
      "question": "七天无理由退货运费谁出？",     # 必填（或 user_input）
      "order_id": null,                          # 咨询类可空；判定类必填
      "expected_refs": ["R-301"],                # 咨询类
      "expected_decision": "SUPPORT_RETURN",     # 判定类
      "evidence_provided": false,
      "case_type": "normal",
      "category": "generic_rule",
      "note": "原文改写"
    }

来源信息走命令行参数（整批一致），不信任输入行里的自报来源：
    --source-name "消费者权益保护法 第二十五条"
        --source-url "https://www.gov.cn/..."
        --license "public-law-text"
        --source-type "paraphrase"

用法：
    python tools/import_public_cases.py --input raw.jsonl --kind consultation \
        --output data/public/eval_consultation_public.jsonl \
        --source-name "..." --source-url "..." --license "..." --source-type paraphrase

    python tools/import_public_cases.py ... --dry-run   # 只校验，不写文件

安全约束：
    - 不执行输入中的任何内容，只当纯文本处理；
    - 手机号/身份证/银行卡/邮箱/详细地址一律替换为占位符；
    - 脱敏后占位符占比过高的记录直接丢弃（原文几乎全是隐私，没有评测价值）；
    - 重复记录（清洗+归一化后相同）默认丢弃，可用 --allow-duplicates 保留。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.privacy import PLACEHOLDERS, redact  # noqa: E402
from core.schema import Decision  # noqa: E402

POLICY_FILE = ROOT / "data" / "policies.md"
DEFAULT_EXISTING = [
    ROOT / "data" / "eval_cases.jsonl",
    ROOT / "data" / "eval_consultation.jsonl",
]

PUNCT = re.compile(r"[\s，。！？、；：\"'“”‘’（）()\[\]【】,.!?;:~…—\-_/\\]+")
REF_RE = re.compile(r"^R-\d{3}$")


def normalize(text: str) -> str:
    """用于查重：去掉空白与标点，英文小写。"""
    return PUNCT.sub("", (text or "").lower())


def scrub(text: str) -> tuple[str, int]:
    """返回（脱敏后的文本, 命中的高敏模式数）。

    规则统一在 core/privacy.py：离线导入与在线送模型共用一套口径，
    不维护两份正则——两份迟早会漂移，而漂移的那天没人会发现。
    """
    out, hits = redact(text or "")
    return out, sum(hits.values())


def load_policy_refs() -> set[str]:
    text = POLICY_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"^### (R-\d{3})", text, flags=re.M))


def load_existing(paths: list[Path]) -> tuple[set[str], set[str]]:
    """返回（已有问题归一化集合, 已有 case_id 集合）。"""
    seen: set[str] = set()
    ids: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            q = rec.get("question") or rec.get("user_input") or ""
            if q:
                seen.add(normalize(q))
            if rec.get("case_id"):
                ids.add(str(rec["case_id"]))
    return seen, ids


def next_case_id(prefix: str, used: set[str]) -> str:
    n = 1
    while f"{prefix}{n:03d}" in used:
        n += 1
    used.add(f"{prefix}{n:03d}")
    return f"{prefix}{n:03d}"


def validate(rec: dict, kind: str, refs_ok: set[str]) -> list[str]:
    errs: list[str] = []
    q = rec.get("question") or rec.get("user_input") or ""
    if not q.strip():
        errs.append("缺少 question/user_input")
    if kind == "decision":
        if not rec.get("order_id"):
            errs.append("判定类用例必须提供 order_id")
        dec = rec.get("expected_decision")
        if dec not in {d.value for d in Decision}:
            errs.append(f"expected_decision 非法: {dec!r}")
    else:
        bad = [r for r in rec.get("expected_refs") or [] if not REF_RE.match(str(r))]
        if bad:
            errs.append(f"expected_refs 格式非法: {bad}")
        unknown = [r for r in rec.get("expected_refs") or [] if r not in refs_ok]
        if unknown:
            errs.append(f"expected_refs 在规则库中不存在: {unknown}")
        if not rec.get("expected_refs") and not rec.get("expect_human_hint"):
            # 允许空引用，但必须显式说明是"未覆盖"场景，避免用空列表掩盖漏标
            errs.append("咨询类用例既无 expected_refs 也未标 expect_human_hint")
    return errs


def build_record(rec: dict, kind: str, args, case_id: str, cleaned: str) -> dict:
    provenance = {
        "source": args.source_type,
        "source_name": args.source_name,
        "source_url": args.source_url,
        "license": args.license,
    }
    if kind == "decision":
        out = {
            "case_id": case_id,
            "order_id": rec["order_id"],
            "user_input": cleaned,
            "evidence_provided": bool(rec.get("evidence_provided", False)),
            "expected_decision": rec["expected_decision"],
            "case_type": rec.get("case_type", "normal"),
            "note": rec.get("note", ""),
            **provenance,
        }
    else:
        out = {
            "case_id": case_id,
            "order_id": rec.get("order_id"),
            "question": cleaned,
            "category": rec.get("category", "public_seed"),
            "expected_tools": rec.get("expected_tools", ["search_policy"]),
            "expected_refs": rec.get("expected_refs") or [],
            "note": rec.get("note", ""),
            **provenance,
        }
        for key in ("forbidden_refs", "expect_human_hint", "forbid_refund_promise",
                    "must_mention_any", "expect_tool_error", "expected_tools_any"):
            if key in rec:
                out[key] = rec[key]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="原始 JSONL 文件")
    ap.add_argument("--output", required=True, help="目标 JSONL 文件")
    ap.add_argument("--kind", choices=["decision", "consultation"], required=True)
    ap.add_argument("--source-name", required=True)
    ap.add_argument("--source-url", required=True)
    ap.add_argument("--license", required=True)
    ap.add_argument("--source-type", default="paraphrase",
                    choices=["public_dataset", "paraphrase", "manual", "platform_faq"])
    ap.add_argument("--existing", nargs="*", default=[str(p) for p in DEFAULT_EXISTING])
    ap.add_argument("--allow-duplicates", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw_path = Path(args.input)
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    if out_path.resolve() == raw_path.resolve():
        print("拒绝执行：输出文件不能覆盖输入文件。")
        return 2

    raw_bytes = raw_path.read_bytes()
    sha = hashlib.sha256(raw_bytes).hexdigest()

    lines = [l for l in raw_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    refs_ok = load_policy_refs()
    existing_q, used_ids = load_existing([Path(p) for p in args.existing])
    if out_path.exists():
        more_q, more_ids = load_existing([out_path])
        existing_q |= more_q
        used_ids |= more_ids

    kept: list[dict] = []
    dropped: list[tuple[int, str]] = []
    pii_hits = 0
    seen_in_batch: set[str] = set()

    for lineno, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
        except ValueError as exc:
            dropped.append((lineno, f"JSON 解析失败: {exc}"))
            continue
        if not isinstance(rec, dict):
            dropped.append((lineno, "不是对象"))
            continue

        errs = validate(rec, args.kind, refs_ok)
        if errs:
            dropped.append((lineno, "；".join(errs)))
            continue

        q = rec.get("question") or rec.get("user_input") or ""
        cleaned, hits = scrub(q)
        pii_hits += hits
        placeholders = sum(cleaned.count(p) for p in PLACEHOLDERS)
        if placeholders and len(cleaned) < 8:
            dropped.append((lineno, "脱敏后内容过短，疑似纯隐私文本"))
            continue

        key = normalize(cleaned)
        if key in existing_q or key in seen_in_batch:
            if not args.allow_duplicates:
                dropped.append((lineno, "与已有用例重复"))
                continue
        seen_in_batch.add(key)

        rec = dict(rec)
        if "question" in rec or args.kind == "consultation":
            rec["question"] = cleaned
        else:
            rec["user_input"] = cleaned
        kept.append(build_record(rec, args.kind, args, next_case_id("P", used_ids), cleaned))

    print(f"输入 {len(lines)} 条 | 保留 {len(kept)} 条 | 丢弃 {len(dropped)} 条 | 脱敏命中 {pii_hits} 处")
    for lineno, reason in dropped[:20]:
        print(f"  第 {lineno} 行丢弃：{reason}")
    if len(dropped) > 20:
        print(f"  ……其余 {len(dropped) - 20} 条略")

    if args.dry_run:
        print("dry-run：未写入任何文件。")
        return 0 if kept else 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8", newline="\n") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    manifest = out_path.parent / "import_manifest.jsonl"
    entry = {
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(raw_path),
        "input_sha256": sha,
        "output": str(out_path),
        "kind": args.kind,
        "source_name": args.source_name,
        "source_url": args.source_url,
        "license": args.license,
        "source_type": args.source_type,
        "input_lines": len(lines),
        "kept": len(kept),
        "dropped": len(dropped),
        "pii_replacements": pii_hits,
        "case_ids": [r["case_id"] for r in kept],
    }
    with manifest.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"已写入 {out_path}（{len(kept)} 条），记账 {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
