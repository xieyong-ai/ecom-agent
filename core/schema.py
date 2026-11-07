"""判定单数据结构与枚举定义。

本模块是全项目的契约中心：规则引擎产出它，评测脚本读取它，界面渲染它。
任何判定结果都必须是一个通过 validate() 校验的 Verdict 实例——
自由文本的判定一律不接受。

与 data/policies.md 的对应关系：
    每个 Decision 取值都对应规则库中的至少一条规则，
    判定单的 policy_refs 字段负责记录具体命中了哪几条。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from core import versions


class Decision(str, Enum):
    """判定结果枚举。

    固定枚举是结构化的前提。新增取值必须同步更新：
    1. data/policies.md 的规则映射表
    2. 判定分支的期望分布（用于评测分层）
    """

    SUPPORT_RETURN = "SUPPORT_RETURN"
    SUPPORT_EXCHANGE = "SUPPORT_EXCHANGE"
    SUPPORT_REFUND_ONLY = "SUPPORT_REFUND_ONLY"
    GUIDE_REJECT_ON_DELIVERY = "GUIDE_REJECT_ON_DELIVERY"
    REJECT_OVERDUE = "REJECT_OVERDUE"
    REJECT_EXEMPT_CATEGORY = "REJECT_EXEMPT_CATEGORY"
    REJECT_DUPLICATE = "REJECT_DUPLICATE"
    REJECT_CLOSED_ORDER = "REJECT_CLOSED_ORDER"
    NEED_EVIDENCE = "NEED_EVIDENCE"
    NEED_HUMAN = "NEED_HUMAN"
    # 咨询类：用户只问规则，未提出执行诉求。不产生判定结论，也不挂退款金额。
    POLICY_ANSWER = "POLICY_ANSWER"

    @property
    def label(self) -> str:
        return _DECISION_LABELS[self]

    @property
    def is_terminal(self) -> bool:
        """是否为终态。

        NEED_EVIDENCE 不是终态——用户补充凭证后需要重新判定。
        POLICY_ANSWER 不是终态——用户问完规则后仍可提出执行诉求，需重新判定。
        其余取值一旦给出即为最终结论，不可自动推翻。
        """
        return self not in (Decision.NEED_EVIDENCE, Decision.POLICY_ANSWER)

    @property
    def is_rejection(self) -> bool:
        return self.value.startswith("REJECT_")


_DECISION_LABELS: dict[Decision, str] = {
    Decision.SUPPORT_RETURN: "支持退货",
    Decision.SUPPORT_EXCHANGE: "支持换货",
    Decision.SUPPORT_REFUND_ONLY: "支持仅退款",
    Decision.GUIDE_REJECT_ON_DELIVERY: "引导拒收后退款",
    Decision.REJECT_OVERDUE: "超期拒受理",
    Decision.REJECT_EXEMPT_CATEGORY: "例外类目拒无理由退货",
    Decision.REJECT_DUPLICATE: "重复申请拒受理",
    Decision.REJECT_CLOSED_ORDER: "订单已关闭拒受理",
    Decision.NEED_EVIDENCE: "待补充凭证",
    Decision.NEED_HUMAN: "转人工",
    Decision.POLICY_ANSWER: "政策咨询（不产生判定）",
}


class DecisionPath(str, Enum):
    """判定路径，决定了结论的可信度与成本。"""

    RULE_ONLY = "RULE_ONLY"          # 纯规则命中，未调用模型
    MODEL_ASSISTED = "MODEL_ASSISTED"  # 规则留白，模型补充语义后判定
    HUMAN = "HUMAN"                  # 转人工


class Intent(str, Enum):
    """用户诉求性质。由语义层识别，是规则引擎的输入之一。"""

    NO_REASON = "无理由"      # 不喜欢、不想要、买错
    QUALITY = "质量问题"      # 破损、故障、与描述不符
    LOGISTICS = "物流问题"    # 未收到、物流停滞、发错地址
    POLICY_QUERY = "政策咨询"  # 仅询问规则，无明确操作诉求
    UNKNOWN = "未识别"


class ShippingBearer(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    NONE = "NONE"

    @property
    def label(self) -> str:
        return {"BUYER": "买家承担", "SELLER": "卖家承担", "NONE": "不涉及"}[self.value]


# 置信度由判定路径推导，不由模型自评。
# 理由：模型给出的置信度不可校准、不可复现，同一输入可能给出不同数值。
CONFIDENCE_BY_PATH: dict[DecisionPath, float] = {
    DecisionPath.RULE_ONLY: 0.95,
    DecisionPath.MODEL_ASSISTED: 0.75,  # 预留：模型参与语义补判的路径
    DecisionPath.HUMAN: 1.0,   # 转人工：不是"结论可信"，而是"该转人工这件事确定"
}

# 关于"冲突折扣"与"置信度阈值"：设计阶段预留了 CONFLICT_DISCOUNT / CONFIDENCE_THRESHOLD
# 两个常量，实现时没有落地，原因是它们要解决的问题不存在——模型只输出意图枚举，
# 不参与判决，因此不存在"模型结论与规则冲突"或"置信度不足需拦截"的场景。
# 规则引擎的每个分支都是确定性的：命中即结论，未命中即转人工（R-504）。
# 留空的抽象比错误的抽象好，故直接删除，而不是保留成永远不生效的配置。


@dataclass
class Ticket:
    """售后工单。判责引擎的输入单元。"""

    ticket_id: str
    user_input: str
    order_id: str | None = None
    evidence_provided: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # 语义层填充，规则引擎读取
    intent: Intent = Intent.UNKNOWN
    round_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["intent"] = self.intent.value
        return d


@dataclass
class Verdict:
    """判定单。判责引擎的输出单元，也是可审计的最小凭证。"""

    ticket_id: str
    decision: Decision
    policy_refs: list[str]
    reason: str
    order_id: str | None = None
    refund_amount: float = 0.0
    shipping_bearer: ShippingBearer = ShippingBearer.NONE
    confidence: float = 0.0
    decided_by: DecisionPath = DecisionPath.RULE_ONLY
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # 模型辅助时记录中间变量，便于回溯
    model_trace: dict[str, Any] = field(default_factory=dict)
    # 版本标识：这张单由哪版规则库 + 哪版 Prompt 产出。
    # 带默认值，judge() 无需改动；回滚时按版本定位基线。
    ruleset_version: str = field(default_factory=lambda: versions.RULESET_VERSION)
    prompt_version: str = field(default_factory=lambda: versions.PROMPT_VERSION)
    # 判定单单号：同一工单重判（补凭证、追加诉求）会产生多张单，
    # 下游按本字段幂等、按 ticket_id 归集。带默认值，judge() 无需改动。
    decision_id: str = field(default_factory=lambda: "D" + uuid4().hex)

    @property
    def need_human(self) -> bool:
        """是否转人工。由 decision 唯一决定，不允许独立赋值。"""
        return self.decision is Decision.NEED_HUMAN

    def validate(self) -> list[str]:
        """校验判定单的不变量。返回违规项列表，空列表表示通过。

        这些约束是判定单可信的基础——宁可抛出错误，也不让一张
        自相矛盾的判定单流入下游。
        """
        errors: list[str] = []

        if not (0.0 <= self.confidence <= 1.0):
            errors.append(f"confidence 越界: {self.confidence}")

        if self.refund_amount < 0:
            errors.append(f"refund_amount 为负: {self.refund_amount}")

        if not self.policy_refs:
            errors.append("policy_refs 为空：任何判定都必须挂到具体规则上")

        # 拒绝类判定不得携带退款金额
        if self.decision.is_rejection and self.refund_amount > 0:
            errors.append(f"{self.decision.value} 不应有退款金额: {self.refund_amount}")

        # 支持类判定必须有退款金额（换货除外，换货不退款）
        if self.decision in (Decision.SUPPORT_RETURN, Decision.SUPPORT_REFUND_ONLY):
            if self.refund_amount <= 0:
                errors.append(f"{self.decision.value} 必须携带正的退款金额")

        # 转人工的判定不应给出自动结论性质的置信度
        if self.need_human and self.decided_by is not DecisionPath.HUMAN:
            errors.append("NEED_HUMAN 的 decided_by 应为 HUMAN")

        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "decision_id": self.decision_id,
            "order_id": self.order_id,
            "decision": self.decision.value,
            "decision_label": self.decision.label,
            "refund_amount": round(self.refund_amount, 2),
            "shipping_bearer": self.shipping_bearer.value,
            "policy_refs": self.policy_refs,
            "confidence": round(self.confidence, 2),
            "decided_by": self.decided_by.value,
            "need_human": self.need_human,
            "reason": self.reason,
            "created_at": self.created_at,
            "model_trace": self.model_trace,
            "ruleset_version": self.ruleset_version,
            "prompt_version": self.prompt_version,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


if __name__ == "__main__":
    # 自测：构造一张合规判定单，验证校验逻辑
    v = Verdict(
        ticket_id="T20250728-0001",
        order_id="ORD10001",
        decision=Decision.SUPPORT_RETURN,
        refund_amount=328.00,
        shipping_bearer=ShippingBearer.BUYER,
        policy_refs=["R-101", "R-301"],
        confidence=CONFIDENCE_BY_PATH[DecisionPath.RULE_ONLY],
        decided_by=DecisionPath.RULE_ONLY,
        reason="签收次日起 2 天，属七天无理由期内；鞋靴非例外类目；商品需保持完好、不影响二次销售。",
    )
    print(v.to_json())
    print("\n校验结果:", v.validate() or "通过")

    print("\n--- 非法用例：拒绝类判定却带退款金额 ---")
    bad = Verdict(
        ticket_id="T20250728-0002",
        decision=Decision.REJECT_OVERDUE,
        refund_amount=199.0,
        policy_refs=["R-105"],
        reason="超过 30 日",
    )
    print("校验结果:", bad.validate())

    print("\n--- 判定枚举一览 ---")
    for d in Decision:
        print(f"  {d.value:<26} {d.label:<16} 终态={d.is_terminal}")
