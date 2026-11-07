"""版本标识：规则库版本与咨询 Prompt 版本。

设计意图（不是装饰字段）：
    判定单必须能回答"这张单是哪版规则 + 哪版 Prompt 产出的"。
    版本号随判定单一起落盘，基线文件按版本命名存档，
    回滚时用「旧版本代码 + 旧版本基线」复跑，diff 为空才算回滚成功。

取值来源：
    ECOM_RULESET_VERSION  默认 v1.0，需与 data/policies.md 头部「版本」一致；
    ECOM_CONSULT_PROMPT   默认 v2，只影响咨询分支的引用口径，不影响判定主链。

为什么用环境变量而不是代码常量：
    回滚要在不改进判定的前提下切换版本——checkout 旧 tag 是最强的回滚，
    环境变量是同一个版本内做 A/B（v1/v2 口径对比）时需要的最小开关。
"""

from __future__ import annotations

import os

#: 规则库版本，必须与 data/policies.md 的表头版本号同步
RULESET_VERSION = (os.getenv("ECOM_RULESET_VERSION") or "v1.0").strip() or "v1.0"

#: 咨询 Prompt 口径版本，只允许 v1 / v2 / v3；默认 v2
#: （v3 修复了 C026 漏引，但过度引用上升，A/B 后被回退，见 core/agent.py 注释）
_P = (os.getenv("ECOM_CONSULT_PROMPT") or "v2").strip().lower()
PROMPT_VERSION = _P if _P in ("v1", "v2", "v3") else "v2"


def describe() -> str:
    """一行版本描述，写进报告头与判定单。"""
    return f"ruleset {RULESET_VERSION} / prompt {PROMPT_VERSION}"


if __name__ == "__main__":
    print(describe())
