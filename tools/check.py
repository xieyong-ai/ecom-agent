"""一条命令跑完确定性门禁：矩阵审计 + 212 条判定回归 + 基线逐条 diff。

回答的问题只有一个：**这次改动有没有偷偷改变任何一条判定？**

三道门禁，全部不联网、不调模型、零第三方依赖（只用标准库）：
    1. `eval.audit_matrix`  —— 13800 组输入的不变量审计，判定单自洽性
    2. `eval.run_eval`      —— 212 条用例跑一遍，导出逐条结果
    3. `eval.compare_runs`  —— 与冻结基线逐条 diff，任何一条 actual 变化即失败

**为什么咨询 Agent 评测不进这里**：它要调 DeepSeek、要花钱、输出有随机性，
放进 CI 会变成"时红时绿的流水线"，久了就没人看了。评测的价值在于"红了就一定是
代码问题"，掺进不确定性就等于把信号换成噪音。咨询专项（33 条 + 20 条公开集）
仍然手动跑：

    python -m eval.run_eval --consultation --semantic

用法：
    python -m tools.check                  # 跑门禁
    python -m tools.check --update-baseline  # 确认改动是预期内后，重新冻结基线
    python -m tools.check --verbose        # 打印子进程全部输出

退出码：0 全部通过；1 有审计违规或判定变化。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "eval" / "baseline-cases.json"


def run(args: list[str], verbose: bool) -> int:
    """跑一个子进程，返回退出码。非 verbose 时只透传最后 6 行，避免刷屏。

    子进程强制 UTF-8 输出：Windows 下管道默认用 GBK，父进程按 UTF-8 解码会得到
    替换字符，再打印到 GBK 控制台就直接 UnicodeEncodeError（门禁没跑完先崩在打印）。
    """
    print(f"\n$ python -m {' '.join(args)}", flush=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = out.rstrip().splitlines()
    if verbose:
        print(out)
    else:
        for line in lines[-6:]:
            print("  " + line)
        if len(lines) > 6:
            print(f"  ...（省略 {len(lines) - 6} 行，加 --verbose 看全部）")
    return proc.returncode


def main() -> int:
    # 兜底：即使子进程仍吐出不可编码字符，也不要让门禁崩在 print 上。
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--update-baseline", action="store_true",
                    help="把当前结果写回 eval/baseline-cases.json（仅在你确认变化是预期内时用）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    print("=" * 70)
    print("确定性门禁：不联网、不调模型、零第三方依赖")
    print("=" * 70)

    # 1) 不变量审计 —— 回答"判出来的东西本身有没有毛病"
    if run(["eval.audit_matrix"], args.verbose) != 0:
        print("\n[失败] 矩阵审计存在违规，先看上面列出的输入组合。判定单不自洽比判错更严重。")
        return 1

    # 2) 212 条回归 —— 回答"判得对不对"
    with tempfile.TemporaryDirectory() as tmp:
        dump = str(Path(tmp) / "after.json")
        if run(["eval.run_eval", "--dump", dump], args.verbose) != 0:
            print("\n[失败] 评测脚本本身非零退出（咨询 Agent 执行失败或脚本报错）。")
            return 1

        # 3) 与基线逐条 diff —— 回答"这次改动有没有动到不该动的东西"
        if not BASELINE.exists():
            print(f"\n[提示] 基线不存在（{BASELINE}），按本次结果冻结。")
            shutil.copyfile(dump, BASELINE)
            print(f"已写入 {BASELINE}，再跑一次即可验证。")
            return 0

        if args.update_baseline:
            shutil.copyfile(dump, BASELINE)
            print(f"\n[已更新] 基线覆盖为本次结果：{BASELINE}")
            print("提醒：基线一改，diff 门禁就对之前的行为失去约束力。确认这是有意变更再提交。")
            return 0

        if run(["eval.compare_runs", str(BASELINE), dump], args.verbose) != 0:
            print("\n[失败] 有判定发生了变化（或基线里缺了用例）。")
            print("       逐条看完差异后：确实是预期内的改动 -> --update-baseline；")
            print("       不是预期内 -> 这就是回归，别改基线。")
            return 1

    print("\n" + "=" * 70)
    print("门禁通过：0 违规，212 条判定与基线逐条一致")
    print("咨询 Agent 评测仍需手动：python -m eval.run_eval --consultation --semantic")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
