"""逐条比对两次评测结果，回答"改造前后哪些用例变了"。

用法：
    python -m eval.compare_runs eval/.baseline-before-semantic.json eval/.after-semantic-final.json

输出：
    - 总条数、actual 差异条数与明细；
    - 按 expected 分组统计；
    - 若存在 consult 字段，额外统计"进入咨询 Agent / Agent 失败"。

判定口径只看 `actual`（最终判定），不看置信度——置信度会随路径变化，
把它算进"差异"会把设计内的路由变化误报成回归。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: str) -> dict[str, dict]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(r["case_id"]): r for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("after")
    ap.add_argument("--allow-new", action="store_true",
                    help="新增用例不算差异（默认算：基线里没有的用例意味着基线已过期，需重新冻结）")
    args = ap.parse_args()

    before = load(args.baseline)
    after = load(args.after)

    missing = sorted(set(before) - set(after))
    extra = sorted(set(after) - set(before))
    diffs = []
    for cid in sorted(set(before) & set(after)):
        b, a = before[cid], after[cid]
        if b.get("actual") != a.get("actual"):
            diffs.append((cid, b.get("actual"), a.get("actual")))

    print(f"baseline {len(before)} 条 | after {len(after)} 条")
    print(f"actual 差异: {len(diffs)} 条")
    if missing:
        print(f"缺少用例: {missing}")
    if extra:
        print(f"新增用例: {extra}")
    for cid, b, a in diffs:
        print(f"  {cid}: {b} -> {a}")

    routed = [cid for cid, r in after.items() if r.get("consult") is not None]
    errors = [cid for cid, r in after.items() if r.get("actual") == "AGENT_ERROR"]
    print(f"进入咨询 Agent: {len(routed)} 条 {routed}")
    print(f"Agent 执行失败: {len(errors)} 条 {errors}")

    by_branch = Counter(
        (before[cid].get("expected"), before[cid].get("actual") != after[cid].get("actual"))
        for cid in set(before) & set(after)
    )
    changed = {
        branch: count
        for (branch, is_diff), count in by_branch.items()
        if is_diff
    }
    if changed:
        print("按期望分支的差异数:", changed)

    return 0 if not diffs and not missing and (args.allow_new or not extra) else 1


if __name__ == "__main__":
    raise SystemExit(main())
