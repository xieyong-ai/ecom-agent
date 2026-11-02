"""事实层：订单与物流查询。

职责边界：
    只负责"查到什么"，不负责"怎么判"。所有判定逻辑都在 rules.py。
    换数据源（从 JSON 换成真实数据库）时，只需替换本模块的实现。

时间基准说明：
    本项目的订单数据以 2026-10-28 12:00 为基准日构造。若使用真实当前时间，
    数据会随时间推移逐渐"腐化"——所有订单都会变成超期订单，七天无理由
    判定将全部失效。因此固定基准时间，可通过环境变量覆盖以做时间穿越测试。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 数据构造的基准时间。允许通过环境变量覆盖，用于测试不同时点的判定。
REFERENCE_NOW = datetime.strptime(
    os.environ.get("ECOM_REFERENCE_NOW", "2026-10-28 12:00"), "%Y-%m-%d %H:%M"
)

# 不适用七天无理由的类目判定字段组合
EXEMPT_CATEGORIES = {"生鲜果蔬", "定制礼品"}

# 已关闭订单的状态等价类：均无可退标的，判定行为一致。
# 待付款（未支付）同样无款可退，与已取消/交易关闭归并。
CLOSED_STATUSES = {"已取消", "交易关闭", "待付款"}

# 大额阈值（R-402）。判定与文案共用同一个常量，避免改了阈值而提示语还说 2000。
LARGE_AMOUNT_THRESHOLD = 2000.0


class OrderNotFound(LookupError):
    """订单不存在。调用方应引导用户核对订单号，而非编造结论。"""


@dataclass
class Facts:
    """一张订单的判定所需事实。规则引擎的唯一输入。"""

    order: dict
    days_since_delivery: int | None
    is_exempt: bool
    exempt_reason: str | None
    amount: float
    # 用户主张未收到货，与签收记录冲突（R-503）。事实存疑时不适用任何退货规则。
    logistics_disputed: bool = False

    @property
    def order_id(self) -> str:
        return self.order["order_id"]

    @property
    def status(self) -> str:
        return self.order["status"]

    @property
    def is_duplicated(self) -> bool:
        """是否已退款或存在进行中的售后工单（R-501）。"""
        if self.status == "已退款":
            return True
        for as_item in self.order.get("after_sale") or []:
            if as_item.get("status") in ("处理中", "已完成"):
                return True
        return False

    @property
    def is_closed(self) -> bool:
        """是否已取消 / 交易关闭（R-502）。

        等价类归并：平台实际的「已取消」「交易关闭」「超时未支付关闭」等状态
        在售后判定上行为一致——均无可退标的，故统一归并为同一等价类，
        避免状态爆炸（每多一个状态，测试组合翻一倍）。
        """
        return self.status in CLOSED_STATUSES

    @property
    def is_large_amount(self) -> bool:
        """是否达到大额阈值（R-402）。"""
        return self.amount >= LARGE_AMOUNT_THRESHOLD


def _judge_exempt(order: dict) -> tuple[bool, str | None]:
    """判断商品是否属于七天无理由的例外类目。

    优先读结构化字段 exempt_reason；没有该字段时回退到类目标记。
    不使用商品名称做字符串匹配——名称是展示用的，随时可能改版。
    """
    items = order.get("items") or []
    if not items:
        # 无商品明细无法判断类目。返回 False 而非抛错：类目只是规则的前置条件之一，
        # 缺明细时其余事实（状态、时限）仍可支撑判定；是否需要人工由规则层决定。
        return False, None
    item = items[0]
    if item.get("exempt_reason"):
        return True, item["exempt_reason"]
    if item.get("is_fresh"):
        return True, "生鲜易腐类"
    if item.get("is_custom"):
        return True, "按用户要求定制"
    if item.get("category") in EXEMPT_CATEGORIES:
        return True, f"{item['category']}属例外类目"
    if item.get("category") == "个护美妆" and not item.get("sealed", True):
        return True, "已拆封个护用品"
    return False, None


class OrderStore:
    """订单库。合并手工金标准样本与脚本生成的批量样本。"""

    def __init__(self, files: tuple[str, ...] = ("orders.json", "orders_bulk.json")):
        self._orders: dict[str, dict] = {}
        for name in files:
            path = DATA_DIR / name
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            for o in payload.get("orders", []):
                self._orders[o["order_id"]] = o

    def __len__(self) -> int:
        return len(self._orders)

    def get(self, order_id: str) -> dict:
        oid = (order_id or "").strip().upper()
        if oid not in self._orders:
            raise OrderNotFound(f"订单不存在: {order_id}")
        return self._orders[oid]

    def raw(self, order_id: str) -> dict | None:
        """按订单号取原始订单字典，不存在返回 None（供界面层做输入校验）。"""
        oid = (order_id or "").strip().upper()
        return self._orders.get(oid)

    def all_ids(self) -> list[str]:
        """全部订单号（gold 在前，便于界面快捷选择）。"""
        return sorted(self._orders, key=lambda x: (not x.startswith("ORD100"), x))

    def find_by_phone(self, phone_suffix: str) -> list[dict]:
        return [o for o in self._orders.values() if o.get("phone", "").endswith(phone_suffix)]

    def facts(self, order_id: str, now: datetime | None = None) -> Facts:
        order = self.get(order_id)
        now = now or REFERENCE_NOW

        days = None
        if order.get("delivered_at"):
            try:
                delivered = datetime.strptime(order["delivered_at"], "%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                delivered = None
            if delivered is not None:
                delta = (now.date() - delivered.date()).days
                # 签收时间晚于基准时间属数据异常。若直接返回负数，会命中"≤7 天"的
                # 无理由分支，等于用错误事实放行退款；置为 None 交由规则层转人工。
                days = delta if delta >= 0 else None

        exempt, reason = _judge_exempt(order)
        try:
            amount = float(order.get("amount") or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        return Facts(
            order=order,
            days_since_delivery=days,
            is_exempt=exempt,
            exempt_reason=reason,
            amount=amount,
            logistics_disputed=bool(order.get("logistics_disputed", False)),
        )


_STORE: OrderStore | None = None


def store() -> OrderStore:
    """全局单例。首次调用时加载数据，避免重复 IO。"""
    global _STORE
    if _STORE is None:
        _STORE = OrderStore()
    return _STORE


if __name__ == "__main__":
    s = store()
    print(f"已加载订单 {len(s)} 条")
    print(f"基准时间 {REFERENCE_NOW}\n")
    for oid in ("ORD10001", "ORD10002", "ORD10003", "ORD10006", "ORD10009", "ORD10014"):
        f = s.facts(oid)
        print(
            f"{oid}  状态={f.status:<4} 距签收={str(f.days_since_delivery):<4} "
            f"金额={f.amount:>7.2f}  例外类目={f.is_exempt}  "
            f"重复={f.is_duplicated}  大额={f.is_large_amount}"
        )
    print("\n--- 查询不存在的订单 ---")
    try:
        s.get("ORD99999")
    except OrderNotFound as e:
        print("已正确抛出:", e)
