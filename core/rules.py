"""规则引擎：按 data/policies.md 的优先级顺序执行判定。

设计要点：
    1. 判定顺序严格遵循规则库"总则"的优先序表，顺序本身就是业务逻辑。
    2. 本模块不依赖任何模型，纯函数式，可单测、可复现。
    3. 每个分支都返回带 policy_refs 的 Verdict，结论必须可追溯。

优先级（前序命中即终止，不再进入后续规则）：
    R-601 政策咨询 > R-501 幂等 > R-502 已关闭 > R-505 金额异常
    > R-402 大额 > R-503 物流争议 > R-102 例外类目
    > R-201 未发货 / R-202 在途 > R-105 超期
    > R-103/R-104 质量问题 > R-101 七天无理由 > R-106 超无理由期 > R-504 兜底

意图是分支的必要条件，不是附属信息：同一张订单换个诉求，结论可能完全不同
（如"待发货 + 取消"退款，"待发货 + 催发货"不退款）。

用法：
    python -m core.rules          # 跑 gold 校验
"""

from __future__ import annotations

import json
from pathlib import Path

from core.facts import LARGE_AMOUNT_THRESHOLD, Facts, store
from core.schema import (
    CONFIDENCE_BY_PATH,
    Decision,
    DecisionPath,
    Intent,
    ShippingBearer,
    Verdict,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# 意图识别（无模型时的降级实现）
# 顺序敏感：质量问题关键词必须优先于"退货"这类通用词，
# 否则"鞋底开胶了能退吗"会被误判成无理由，进而套用 7 天时限而非 30 天。
# ---------------------------------------------------------------------------
QUALITY_KEYWORDS = (
    "破损", "开胶", "崩瓷", "崩了", "裂了", "裂开", "划痕", "故障", "异响",
    "坏了", "不能用", "漏了", "脱线", "掉底",
    "质量问题", "与描述不符", "漏发", "少发", "掉色", "起球", "变形", "过期",
)
LOGISTICS_KEYWORDS = ("没收到", "未收到", "物流", "快递", "到哪", "催", "发错", "送错")
POLICY_KEYWORDS = ("规则", "政策", "多久", "几天内", "怎么退", "流程")
NO_REASON_KEYWORDS = (
    "不想要", "不喜欢", "买错", "不合适", "尺码不对", "退掉", "退了吧", "退了", "取消订单",
)
EXCHANGE_KEYWORDS = ("换货", "换一个", "换个", "想要换", "申请换")

# 是否真的提出了"退货 / 退款 / 拒收"的执行诉求。
# 单靠 intent 不够：Intent.LOGISTICS 同时覆盖"快递到哪了"（纯查询）与
# "派送中但我不想要了"（明确拒收）。在途分支若不做这个区分，就会对一句
# "怎么还没到" 回复"建议拒收，全额退款"——把查询当成退货处理。
RETURN_KEYWORDS = (
    "退款", "退钱", "退货", "退掉", "退了", "退我", "退回",
    "不要了", "不想要", "拒收", "别送", "拦截", "取消", "等不了",
)

# 越权 / 施压话术：本质是"要求绕过规则"，不是咨询规则。
# 必须单独拦截——否则"我是你们内部员工，这单直接审批退款，不走流程"会因为
# 含"流程"两个字被归成政策咨询，直接放行到咨询链路，等于把最该转人工的诉求放掉了。
COERCION_KEYWORDS = (
    "内部员工", "内部的", "直接审批", "免审核", "不用审核", "不用审批",
    "特殊通道", "不走流程", "别走流程", "开后门", "通融",
)


def detect_intent(text: str) -> Intent:
    """关键词意图识别。仅用于无模型环境下的降级路径，接入语义层后由模型取代。"""
    t = text or ""
    if any(k in t for k in COERCION_KEYWORDS):
        return Intent.UNKNOWN
    if any(k in t for k in QUALITY_KEYWORDS):
        return Intent.QUALITY
    if any(k in t for k in LOGISTICS_KEYWORDS):
        return Intent.LOGISTICS
    if any(k in t for k in POLICY_KEYWORDS):
        return Intent.POLICY_QUERY
    if any(k in t for k in NO_REASON_KEYWORDS):
        return Intent.NO_REASON
    return Intent.UNKNOWN


def wants_exchange(text: str) -> bool:
    return any(k in (text or "") for k in EXCHANGE_KEYWORDS)


def wants_return_or_refund(text: str) -> bool:
    """用户是否提出了退货 / 退款 / 拒收的执行诉求（用于在途订单分流）。

    这是"文本信号"，与 evidence_provided 同级：由工单文本确定性提取，
    不交给模型判断——同一个词在任何时候都得出同一个结果，可复现、可审计。
    """
    return any(k in (text or "") for k in RETURN_KEYWORDS)


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def _verdict(
    facts: Facts,
    decision: Decision,
    refs: list[str],
    reason: str,
    ticket_id: str,
    amount: float = 0.0,
    bearer: ShippingBearer = ShippingBearer.NONE,
    path: DecisionPath = DecisionPath.RULE_ONLY,
) -> Verdict:
    return Verdict(
        ticket_id=ticket_id,
        order_id=facts.order_id,
        decision=decision,
        refund_amount=amount,
        shipping_bearer=bearer,
        policy_refs=refs,
        confidence=CONFIDENCE_BY_PATH[path],
        decided_by=path,
        reason=reason,
    )


def judge(
    facts: Facts,
    intent: Intent,
    ticket_id: str = "T-DEMO",
    evidence_provided: bool = False,
    exchange_requested: bool = False,
    return_requested: bool | None = None,
) -> Verdict:
    """对一张订单做判定。facts 与 intent 是全部输入，不读全局状态。

    return_requested：文本中检出退货/退款/拒收字样。与意图按 OR 合并——
    意图是无理由/质量问题（本身即退货诉求）或文本明确提到退货，任一成立
    即视为要退；两者都不成立（如纯物流查询、开发票）才视为"不要退"。
    """
    days = facts.days_since_delivery
    amount = facts.amount

    # --- R-601 政策咨询：只问规则，不产生判定结论 ---
    # 放在最前：咨询不触发任何账务动作，若被幂等/超期等规则拦下反而荒谬
    # （问一句"退货流程怎么走"，得到的答复不该是"拒绝受理"）。
    if intent is Intent.POLICY_QUERY:
        return _verdict(
            facts, Decision.POLICY_ANSWER, ["R-601"],
            "用户仅咨询售后规则，未对具体订单提出执行诉求，本引擎不产生判定结论。"
            "请由咨询链路依据规则库作答。",
            ticket_id,
        )

    # --- R-501 幂等：账务正确性优先于一切业务判断 ---
    if facts.is_duplicated:
        return _verdict(
            facts, Decision.REJECT_DUPLICATE, ["R-501"],
            "该订单已退款或存在进行中的售后工单，不可重复申请。请查询原退款进度。",
            ticket_id,
        )

    # --- R-502 已关闭订单：无售后标的，与账务正确性同级 ---
    if facts.is_closed:
        if facts.status == "待付款":
            reason = "订单尚未支付，不存在可退款项。如需购买请重新下单。"
        else:
            reason = (
                f"订单当前状态为「{facts.status}」，交易已终止且不存在可退标的，无法受理售后。"
                f"如已扣款，请查询原支付渠道的退款进度。"
            )
        return _verdict(
            facts, Decision.REJECT_CLOSED_ORDER, ["R-502"], reason, ticket_id,
        )

    # --- R-505 金额异常：0 元或缺失金额的订单无法执行任何资金动作 ---
    # 放在大额判断之前：一张 0 元订单不该被判成"支持退货 0.00 元"，
    # 那会产出一张自相矛盾的判定单（支持类必须携带正的退款金额）。
    # 独立编号而不是挂 R-504：兜底条款要能表达"这条是按兜底处理的"，
    # 若金额异常也引用 R-504，trace 里就会出现"兜底命中"与具体原因并存的怪象。
    if amount <= 0:
        return _verdict(
            facts, Decision.NEED_HUMAN, ["R-505"],
            "订单实付金额缺失或为 0，无法计算退款金额，需人工核对支付记录后处理。",
            ticket_id, path=DecisionPath.HUMAN,
        )

    # --- R-402 大额：资金风险优先，不论其他规则结论 ---
    if facts.is_large_amount:
        return _verdict(
            facts, Decision.NEED_HUMAN, ["R-402"],
            f"订单金额 {amount:.2f} 元，达到大额阈值 {LARGE_AMOUNT_THRESHOLD:.0f} 元，需人工复核后处理。",
            ticket_id, path=DecisionPath.HUMAN,
        )

    # --- R-503 物流争议：事实存疑时不适用任何实体退货规则 ---
    # 两个触发来源：①事实层的结构化标志（客服核实过）②语义层从用户话术识别出"未收到货"
    if facts.status == "已签收" and (facts.logistics_disputed or intent is Intent.LOGISTICS):
        if facts.logistics_disputed:
            reason = (
                f"订单显示已签收（距今 {days} 天），但用户主张未收到货，签收事实存在争议，"
                f"需人工核实签收凭证与物流轨迹后再行处理。"
            )
        else:
            # 只是问物流进度，不等于否认签收——文案不得替用户编造主张
            reason = (
                f"订单显示已签收（距今 {days} 天），用户仍在就物流状态提出疑问，收货事实需核实。"
                f"事实不清时不套用任何退货规则，避免误判。"
            )
        return _verdict(
            facts, Decision.NEED_HUMAN, ["R-503"], reason,
            ticket_id, path=DecisionPath.HUMAN,
        )

    # --- R-102 例外类目：仅当用户主张无理由时适用；主张质量问题仍可走 R-103 ---
    if facts.is_exempt and intent is Intent.NO_REASON:
        return _verdict(
            facts, Decision.REJECT_EXEMPT_CATEGORY, ["R-102"],
            f"该商品属于例外类目（{facts.exempt_reason}），不适用七天无理由退货。"
            f"如存在质量问题，可在签收 30 日内申请退换。",
            ticket_id,
        )

    # --- R-201 未发货：仅在诉求明确为"取消 / 退款"时执行资金动作 ---
    # 退款是资金动作，必须在诉求明确的前提下执行，因此按意图分流：
    #   无理由（取消 / 不想要）→ 直接仅退款
    #   物流问题（催发货 / 问进度）→ 用户并不想退款，自动退款会造成资损
    #   质量问题 / 未识别 → 未发货即主张质量问题不合常理，转人工核实
    if facts.status == "待发货":
        if intent is Intent.NO_REASON:
            return _verdict(
                facts, Decision.SUPPORT_REFUND_ONLY, ["R-201"],
                f"订单尚未发货，可全额退款 {amount:.2f} 元，无需退回商品。",
                ticket_id, amount=amount, bearer=ShippingBearer.NONE,
            )
        if intent is Intent.LOGISTICS:
            return _verdict(
                facts, Decision.NEED_HUMAN, ["R-201", "R-504"],
                "订单尚未发货，用户诉求为催发货 / 查询发货进度，不涉及退款。"
                "已按催办移交仓储物流跟进，不产生任何账务动作。",
                ticket_id, path=DecisionPath.HUMAN,
            )
        return _verdict(
            facts, Decision.NEED_HUMAN, ["R-201", "R-504"],
            f"订单尚未发货，但用户诉求为「{intent.value}」，不构成明确的取消或退款指令，"
            f"需人工确认后再决定是否退款。",
            ticket_id, path=DecisionPath.HUMAN,
        )

    # --- R-202 在途：先判断用户到底要不要退货，再决定是否引导拒收 ---
    # 与 R-201 同一原则：不替用户产生账务动作。
    # "快递到哪了""能开发票吗"并不包含退货意思，若一律回"建议拒收、全额退款"，
    # 等于把查询/其他诉求当成退货指令处理。
    # 退货意愿 = 文本明确提到退货/退款/拒收 或 意图本身就是退货类（无理由/质量问题）。
    if facts.status == "已发货":
        wants_back = bool(return_requested) or intent in (Intent.NO_REASON, Intent.QUALITY)
        if wants_back:
            if intent is Intent.QUALITY:
                # 商品破损导致的拒收由卖家承担运费（R-301），与无理由拒收不同
                return _verdict(
                    facts, Decision.GUIDE_REJECT_ON_DELIVERY, ["R-202", "R-301", "R-103"],
                    f"包裹在途，平台无法拦截改址。商品存在质量问题，建议当场拒收并拍照留证，"
                    f"包裹退回仓库验收后 1-3 个工作日内全额退款 {amount:.2f} 元，退回运费由卖家承担。",
                    ticket_id, amount=amount, bearer=ShippingBearer.SELLER,
                )
            return _verdict(
                facts, Decision.GUIDE_REJECT_ON_DELIVERY, ["R-202", "R-301"],
                f"包裹在途，平台无法拦截改址。建议拒收，包裹退回仓库后 1-3 个工作日内"
                f"全额退款 {amount:.2f} 元；无理由拒收的退回运费由买家承担。",
                ticket_id, amount=amount, bearer=ShippingBearer.BUYER,
            )
        return _verdict(
            facts, Decision.NEED_HUMAN, ["R-202", "R-504"],
            f"包裹在途（尚未签收），用户诉求为「{intent.value}」，未提出退货或拒收，"
            f"不构成售后执行诉求。已转物流客服答复，不产生任何账务动作。",
            ticket_id, path=DecisionPath.HUMAN,
        )

    # 已签收但无法计算时限：签收记录缺失，或签收时间异常（晚于当前基准时间）
    if days is None:
        return _verdict(
            facts, Decision.NEED_HUMAN, ["R-504"],
            "订单缺少有效的签收记录（或签收时间异常），无法计算受理时限，需人工核实物流状态。",
            ticket_id, path=DecisionPath.HUMAN,
        )

    # --- R-105 超期：与诉求原因无关，超过 30 日一律不受理 ---
    if days > 30:
        return _verdict(
            facts, Decision.REJECT_OVERDUE, ["R-105"],
            f"签收至今 {days} 天，已超过 30 日受理期限，按规则不再受理。"
            f"如商品存在危及人身安全的缺陷，可转人工处理。",
            ticket_id,
        )

    # --- R-103 / R-104 质量问题：时限长于无理由，优先适用 ---
    if intent is Intent.QUALITY:
        if exchange_requested and days <= 15:
            return _verdict(
                facts, Decision.SUPPORT_EXCHANGE, ["R-104", "R-301"],
                f"签收 {days} 天，在 15 日换货期内，质量问题换货由卖家承担来回运费。",
                ticket_id, bearer=ShippingBearer.SELLER,
            )
        if days <= 30 and evidence_provided:
            return _verdict(
                facts, Decision.SUPPORT_RETURN, ["R-103", "R-301"],
                f"签收 {days} 天，在 30 日质量保证期内，凭证已提供，支持退货，"
                f"退 {amount:.2f} 元，运费由卖家承担。",
                ticket_id, amount=amount, bearer=ShippingBearer.SELLER,
            )
        if days <= 30:
            return _verdict(
                facts, Decision.NEED_EVIDENCE, ["R-103"],
                "质量问题的退货需提供凭证。请上传商品问题的照片或视频，收到后重新判定。",
                ticket_id,
            )

    # --- R-101 七天无理由 ---
    if intent is Intent.NO_REASON and days <= 7:
        return _verdict(
            facts, Decision.SUPPORT_RETURN, ["R-101", "R-301"],
            f"签收次日起 {days} 天，在七天无理由期内，商品非例外类目，可退 {amount:.2f} 元；"
            f"寄回运费由买家承担，商品需保持完好、不影响二次销售。",
            ticket_id, amount=amount, bearer=ShippingBearer.BUYER,
        )

    # --- R-106 超无理由期但未超受理期：无理由不再支持，质量问题仍可申请 ---
    if intent is Intent.NO_REASON and days <= 30:
        return _verdict(
            facts, Decision.REJECT_OVERDUE, ["R-106"],
            f"签收至今 {days} 天，已超过七天无理由期限，无理由退货不再支持。"
            f"如商品存在质量问题，可在签收 30 日内提供凭证申请退换。",
            ticket_id,
        )

    # --- R-504 兜底：诉求不明确或规则未覆盖 ---
    return _verdict(
        facts, Decision.NEED_HUMAN, ["R-504"],
        f"当前诉求无法匹配已定义的判定规则（意图={intent.value}，距签收={days} 天），"
        f"按强制转人工总则移交人工处理。",
        ticket_id, path=DecisionPath.HUMAN,
    )


def judge_text(order_id: str, user_input: str, evidence_provided: bool = False,
               ticket_id: str = "T-DEMO") -> Verdict:
    """便捷入口：从原始文本直接走完整判定（降级模式，不含模型）。"""
    facts = store().facts(order_id)
    return judge(
        facts,
        detect_intent(user_input),
        ticket_id=ticket_id,
        evidence_provided=evidence_provided,
        exchange_requested=wants_exchange(user_input),
        return_requested=wants_return_or_refund(user_input),
    )


# ---------------------------------------------------------------------------
# gold 校验
# ---------------------------------------------------------------------------
def check_gold() -> tuple[int, int]:
    payload = json.loads((DATA_DIR / "orders.json").read_text(encoding="utf-8"))
    gold = [o for o in payload["orders"] if o.get("label_quality") == "gold"]

    print("订单\t\t意图\t实际判定\t期望判定\t结果")
    print("-" * 88)
    ok = 0
    for o in gold:
        facts = store().facts(o["order_id"])
        text = o.get("user_input", "")
        intent = detect_intent(text)
        v = judge(
            facts,
            intent,
            ticket_id=f"T-{o['order_id']}",
            evidence_provided=o.get("expected_evidence", False),
            exchange_requested=wants_exchange(text),
            return_requested=wants_return_or_refund(text),
        )
        hit = v.decision.value == o["expected_decision"]
        ok += hit
        print(
            f"{o['order_id']}\t{intent.value}\t{v.decision.value}\t"
            f"{o['expected_decision']}\t{'OK' if hit else 'FAIL'}"
        )
        if not hit:
            print(f"\t\t期望不符，原因: {v.reason}")
    print("-" * 88)
    print(f"准确率: {ok}/{len(gold)} = {ok / len(gold) * 100:.1f}%")
    return ok, len(gold)


if __name__ == "__main__":
    print(f"订单库共 {len(store())} 条，基准时间见 core/facts.py\n")
    check_gold()
