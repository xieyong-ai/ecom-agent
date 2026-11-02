"""咨询分支的只读工具集。

本模块只做「查」，不做「改」：
    - 四个工具全部是只读查询，不提供任何写操作、退款、改单、取消订单能力。
    - 工具注册表 READ_ONLY_TOOLS 是唯一的工具来源，Agent 只能从这里拿工具；
      「不挂写工具」靠注册表保证，而不是靠提示词约束。

工具体系与判定链路的关系：
    judge() 仍然只接收 Facts + Intent，不调用本模块。本模块只服务于
    `core/agent.py` 的咨询答复路径——咨询只回答规则，不产生 decision。

检索设计：
    data/policies.md 只有 18 条规则，引入向量库属于过度设计。
    search_policy 直接按 `### R-xxx` 标题抽取条款，用字符 bigram + BM25
    做关键词检索，零额外依赖、结果可复现。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from core.facts import OrderNotFound, REFERENCE_NOW, store

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 时限口径与规则库一致：R-101 七天无理由、R-104 十五日换货、R-103 三十日质量。
NO_REASON_DAYS = 7
EXCHANGE_DAYS = 15
QUALITY_DAYS = 30

# 检索停用词：问句里的高频虚词，命中它们不代表条款相关。
_STOPWORDS = {
    "怎么", "什么", "为什", "可以", "能否", "能不", "不能", "这个", "那个",
    "我的", "我是", "请问", "一下", "现在", "到底", "应该", "需要", "是否",
    "的话", "还是", "就是", "然后", "因为", "所以", "如果", "但是", "而且",
}

# 规则关键词：BM25 之外的一层确定性加权。18 条规则的领域词很集中，
# 直接按关键词加权比调 BM25 参数更可解释、也更容易回归。
_RULE_HINTS: dict[str, tuple[str, ...]] = {
    "R-101": ("七天", "7天", "无理由", "不喜欢", "不想要", "签收次日"),
    "R-102": ("例外类目", "生鲜", "定制", "拆封", "激活", "贴身", "不能七天"),
    "R-103": ("质量问题", "破损", "故障", "划痕", "开胶", "凭证", "照片", "视频"),
    "R-104": ("换货", "换一个", "换个", "换新", "15天"),
    "R-105": ("超过30", "超期", "过期", "不再受理", "一个多月"),
    "R-106": ("超过七天", "超无理由", "8-30"),
    "R-201": ("未发货", "待发货", "取消订单"),
    "R-202": ("在途", "运输中", "拒收", "已发货"),
    "R-301": ("运费", "邮费", "寄回"),
    "R-401": ("到账", "退款时效", "工作日"),
    "R-402": ("大额", "2000"),
    "R-501": ("重复", "已退款", "幂等"),
    "R-502": ("已关闭", "交易关闭", "待付款", "已取消"),
    "R-503": ("未收到", "虚假签收", "签收争议", "物流争议"),
    "R-504": ("未覆盖", "跨境", "保税", "投诉", "法律途径"),
    "R-505": ("0元", "金额异常"),
    "R-601": ("咨询", "流程"),
}

_QUALITY_HINTS = ("质量", "破损", "故障", "划痕", "开胶", "坏了")


def _hint_bonus(question: str, ref: str) -> float:
    """关键词与天数信号加权。只做正向加分，不改变 BM25 的基本排序逻辑。"""
    bonus = 0.0
    for kw in _RULE_HINTS.get(ref, ()):
        if kw in question:
            bonus += 4.0

    # 用户直接说"签收 38 天"时，天数本身就是最强的分流信号
    for m in re.finditer(r"(\d+)\s*天", question):
        n = int(m.group(1))
        if n > 30 and ref == "R-105":
            bonus += 8.0
        elif 8 <= n <= 30:
            if ref == "R-106" and not any(k in question for k in _QUALITY_HINTS):
                bonus += 4.0
            if ref == "R-103":
                bonus += 2.0
        elif n <= 7 and ref == "R-101":
            bonus += 4.0
    return bonus


# ---------------------------------------------------------------------------
# policies.md 解析
# ---------------------------------------------------------------------------
def _load_policy_sections() -> list[dict[str, str]]:
    """按 `### R-xxx 标题` 切分规则库，返回条款列表。"""
    md = (DATA_DIR / "policies.md").read_text(encoding="utf-8")
    pattern = re.compile(r"^###\s+(R-\d+)\s+(.+?)\s*$", flags=re.M)
    matches = list(pattern.finditer(md))
    sections: list[dict[str, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[start:end].strip()
        # 去掉条款之间的分隔线和下一节的二级标题残留
        body = re.sub(r"^---\s*$", "", body, flags=re.M).strip()
        body = re.split(r"^##\s+", body, maxsplit=1, flags=re.M)[0].strip()
        sections.append({"ref": m.group(1), "title": m.group(2).strip(), "text": body})
    return sections


_POLICY_SECTIONS: list[dict[str, str]] | None = None


def _policy_sections() -> list[dict[str, str]]:
    global _POLICY_SECTIONS
    if _POLICY_SECTIONS is None:
        _POLICY_SECTIONS = _load_policy_sections()
    return _POLICY_SECTIONS


def _tokens(text: str) -> list[str]:
    """中文字符 bigram + 英文/数字词。中文检索不做分词，bigram 足够。"""
    text = (text or "").lower()
    toks = re.findall(r"[a-z0-9]+", text)
    for run in re.findall(r"[一-鿿]+", text):
        if len(run) == 1:
            toks.append(run)
        else:
            toks.extend(run[i : i + 2] for i in range(len(run) - 1))
    return [t for t in toks if t not in _STOPWORDS]


def _bm25_search(question: str, top_k: int = 4) -> list[dict[str, Any]]:
    """BM25 检索。返回按相关度排序的条款，score 为 0 的条款不返回。"""
    sections = _policy_sections()
    if not sections:
        return []

    docs = [_tokens(s["title"] + "\n" + s["text"]) for s in sections]
    q = _tokens(question)
    if not q:
        return []

    n = len(docs)
    avg_len = sum(len(d) for d in docs) / n
    df = Counter()
    for d in docs:
        df.update(set(d))
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in set(q)}

    k1, b = 1.5, 0.75
    scored: list[tuple[float, int]] = []
    for idx, d in enumerate(docs):
        tf = Counter(d)
        dl = len(d)
        score = 0.0
        for t in q:
            if t not in tf:
                continue
            denom = tf[t] + k1 * (1 - b + b * dl / avg_len)
            score += idf.get(t, 0.0) * (tf[t] * (k1 + 1)) / denom
        # 标题命中额外加权：用户问"运费"，标题里带运费承担的条款更相关
        title_tokens = set(_tokens(sections[idx]["title"]))
        score += 0.8 * sum(1 for t in set(q) if t in title_tokens)
        # 领域关键词与天数信号：弥补 BM25 在短问句上的排序偏差
        score += _hint_bonus(question, sections[idx]["ref"])
        if score > 0:
            scored.append((score, idx))

    scored.sort(key=lambda x: (-x[0], x[1]))
    out: list[dict[str, Any]] = []
    for score, idx in scored[:top_k]:
        s = sections[idx]
        out.append({
            "ref": s["ref"],
            "title": s["title"],
            "score": round(score, 3),
            "text": s["text"][:1600],
        })
    return out


# ---------------------------------------------------------------------------
# 四个只读工具
# ---------------------------------------------------------------------------
@tool
def query_order(order_id: str) -> str:
    """只读查询订单事实：状态、距签收天数、实付金额、例外类目、是否重复申请。

    当用户的问题涉及"这一单/我这个订单"时调用，用事实回答，不要猜。
    本工具不修改订单、不创建售后、不退款。
    """
    try:
        f = store().facts(order_id)
    except OrderNotFound:
        return json.dumps(
            {"error": f"订单不存在：{order_id}", "hint": "请让用户核对订单号"},
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "order_id": f.order_id,
            "status": f.status,
            "days_since_delivery": f.days_since_delivery,
            "amount": round(f.amount, 2),
            "exempt_reason": f.exempt_reason,
            "is_duplicated": f.is_duplicated,
        },
        ensure_ascii=False,
    )


@tool
def search_policy(question: str) -> str:
    """检索平台售后规则库，返回命中的条款编号（R-xxx）、标题和原文。

    回答任何规则问题前都必须先调用本工具。答复中的条款编号只能取自
    本工具的实际返回；检索不到就如实说"规则库未覆盖，建议转人工"，
    禁止凭记忆编造条款编号、时限或运费承担方。
    本工具只读，不会执行退款或修改订单。
    """
    matches = _bm25_search(question)
    if not matches:
        return json.dumps(
            {"matches": [], "note": "规则库未检索到相关条款，建议转人工"},
            ensure_ascii=False,
        )
    return json.dumps({"matches": matches}, ensure_ascii=False)


@tool
def calc_return_window(order_id: str) -> str:
    """按订单签收时间计算退货/换货窗口的剩余天数。

    返回七天无理由（R-101）、质量问题换货（R-104，15 日）、
    质量问题退货（R-103，30 日）的剩余天数与是否仍在窗口内。
    用户问"还能退吗/还剩几天/过没过期"时调用。
    本工具只做计算，不执行退货或退款。
    """
    try:
        f = store().facts(order_id)
    except OrderNotFound:
        return json.dumps(
            {"error": f"订单不存在：{order_id}", "hint": "请让用户核对订单号"},
            ensure_ascii=False,
        )

    days = f.days_since_delivery
    if days is None:
        return json.dumps(
            {
                "order_id": f.order_id,
                "status": f.status,
                "days_since_delivery": None,
                "note": "订单未签收或签收记录异常，无法计算受理时限",
            },
            ensure_ascii=False,
        )

    def left(limit: int) -> int:
        return max(0, limit - days)

    return json.dumps(
        {
            "order_id": f.order_id,
            "status": f.status,
            "days_since_delivery": days,
            "no_reason": {
                "limit_days": NO_REASON_DAYS,
                "days_left": left(NO_REASON_DAYS),
                "within": days <= NO_REASON_DAYS,
            },
            "quality_return": {
                "limit_days": QUALITY_DAYS,
                "days_left": left(QUALITY_DAYS),
                "within": days <= QUALITY_DAYS,
            },
            "quality_exchange": {
                "limit_days": EXCHANGE_DAYS,
                "days_left": left(EXCHANGE_DAYS),
                "within": days <= EXCHANGE_DAYS,
            },
        },
        ensure_ascii=False,
    )


@tool
def check_logistics(order_id: str) -> str:
    """只读查询订单物流轨迹与当前物流状态。

    用户问"到哪了/为什么还没到/有没有签收"时调用。
    优先返回订单库里的真实模拟轨迹；没有轨迹时按订单状态生成静态说明。
    本工具不修改地址、不拦截包裹、不执行退款。
    """
    order = store().raw(order_id)
    if order is None:
        return json.dumps(
            {"error": f"订单不存在：{order_id}", "hint": "请让用户核对订单号"},
            ensure_ascii=False,
        )

    status = order.get("status")
    logistics = order.get("logistics") or {}
    traces = list(logistics.get("traces") or [])

    if not traces:
        # 无轨迹的订单：按状态给一条静态说明，避免返回空数组让模型无从解释
        fallback = {
            "待付款": [{"time": order.get("created_at"), "desc": "订单待支付"}],
            "待发货": [{"time": order.get("paid_at") or order.get("created_at"),
                       "desc": "支付成功，等待仓库发货"}],
            "已发货": [{"time": order.get("shipped_at"), "desc": "商品已出库，运输中"}],
            "已取消": [{"time": order.get("created_at"), "desc": "订单已取消"}],
            "交易关闭": [{"time": order.get("created_at"), "desc": "订单已关闭"}],
            "已退款": [{"time": order.get("created_at"), "desc": "退款已完成，订单关闭"}],
        }.get(status, [])
        traces = [t for t in fallback if t.get("time")]

    return json.dumps(
        {
            "order_id": order["order_id"],
            "status": status,
            "company": logistics.get("company"),
            "tracking_no": logistics.get("tracking_no"),
            "delivered_at": order.get("delivered_at"),
            "traces": traces,
            "logistics_disputed": bool(order.get("logistics_disputed", False)),
        },
        ensure_ascii=False,
    )


# 工具注册表：Agent 只从这里取工具。新增任何工具都必须先通过这里的只读审查。
READ_ONLY_TOOLS = (query_order, search_policy, calc_return_window, check_logistics)
TOOL_NAMES = tuple(t.name for t in READ_ONLY_TOOLS)
TOOL_MAP = {t.name: t for t in READ_ONLY_TOOLS}


if __name__ == "__main__":
    # 自测：检索、订单事实、窗口、物流
    print("--- search_policy('退货流程怎么走，运费谁出') ---")
    print(search_policy.invoke({"question": "退货流程怎么走，运费谁出"}))
    print("\n--- search_policy('开发票') ---")
    print(search_policy.invoke({"question": "开发票"}))
    print("\n--- query_order('ORD10001') ---")
    print(query_order.invoke({"order_id": "ORD10001"}))
    print("\n--- calc_return_window('ORD10001') ---")
    print(calc_return_window.invoke({"order_id": "ORD10001"}))
    print("\n--- check_logistics('ORD10001') ---")
    print(check_logistics.invoke({"order_id": "ORD10001"}))
    print("\n工具清单:", TOOL_NAMES)
