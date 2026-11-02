#!/usr/bin/env python
"""按标签生成订单数据（label-first generation）。

设计要点：
    先确定这条订单"期望被判成什么"，再反推构造满足该判定的参数
    （距签收天数、类目、金额、订单状态），最后落成一条订单记录。

    这样做是为了避免循环论证——如果先用规则引擎跑一遍生成"标准答案"，
    再用这份答案去评测规则引擎，准确率永远 100%，评测就失去了意义。
    按标签生成时，标签在构造阶段就已确定，与被测系统完全解耦。

用法：
    python tools/gen_orders.py --count 488
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

BASE_DATE = datetime(2026, 10, 28, 12, 0, 0)

# 类目池：exempt 标记该商品是否属于"不适用七天无理由"的例外类目
CATEGORY_POOL = {
    "normal": [
        ("鞋靴", "轻量跑步鞋 男款 {size} 码", 199, 899),
        ("服饰", "纯棉宽松短袖 T 恤 {color}", 59, 299),
        ("箱包", "商务双肩包 15.6 寸", 199, 999),
        ("家居日用", "保温杯 316 不锈钢 500ml", 49, 259),
        ("厨房电器", "家用电磁炉 2200W", 399, 1599),
        ("电脑办公", "无线鼠标 静音款", 69, 259),
    ],
    "exempt": [
        ("生鲜果蔬", "智利进口车厘子 2J 级 1kg", 69, 299),
        ("定制礼品", "定制水晶相册 20 页 刻字款", 199, 699),
        ("个护美妆", "氨基酸洗发水 500ml", 49, 199),
        ("电脑办公", "轻薄笔记本电脑 14 寸 已激活", 3999, 8999),
        ("服饰", "女士内衣 无钢圈款", 89, 259),
    ],
    # 高价池：用于构造触发大额人工复核的订单，避免靠 max(低价, 2000) 硬拉
    "high_value": [
        ("手机数码", "智能手机 8GB+256GB 星空黑", 2199, 5999),
        ("电脑办公", "轻薄笔记本电脑 14 寸 16GB+512GB", 3999, 8999),
        ("大家电", "滚筒洗衣机 10kg 变频", 2199, 4599),
        ("厨房电器", "嵌入式蒸烤箱 60L", 2599, 6999),
        ("家居日用", "实木餐桌 1.8m 胡桃色", 2399, 5299),
    ],
}

COLORS = ["黑色", "米白色", "深灰", "藏青", "灰蓝", "卡其"]
SIZES = ["38", "39", "40", "41", "42", "43"]
CITIES = [
    ("浙江省杭州市西湖区", "文三路"),
    ("江苏省南京市鼓楼区", "中山北路"),
    ("广东省深圳市南山区", "科技园南路"),
    ("北京市朝阳区", "建国路"),
    ("四川省成都市武侯区", "天府大道"),
    ("湖北省武汉市洪山区", "珞瑜路"),
    ("陕西省西安市雁塔区", "高新路"),
    ("福建省厦门市思明区", "望海路"),
]
SURNAMES = "王李张刘陈杨赵黄周吴徐孙马朱胡郭何高林罗"
GIVEN = ["伟", "芳", "娜", "敏", "静", "磊", "洋", "强", "军", "杰", "雪", "涛", "明", "超", "丽"]
COMPANIES = [("顺丰速运", "SF"), ("京东物流", "JD"), ("中通快递", "ZT"), ("圆通速递", "YT"), ("韵达快递", "YD")]

# 七个判定分支
DECISIONS = [
    "SUPPORT_RETURN",
    "SUPPORT_EXCHANGE",
    "SUPPORT_REFUND_ONLY",
    "REJECT_OVERDUE",
    "REJECT_EXEMPT_CATEGORY",
    "NEED_EVIDENCE",
    "NEED_HUMAN",
]


def _pick_category(exempt: bool, tier: str = "normal") -> tuple[str, str, float, str | None]:
    if tier == "high":
        cat, name, lo, hi = random.choice(CATEGORY_POOL["high_value"])
        name = name.format(size=random.choice(SIZES), color=random.choice(COLORS))
        return cat, name, round(random.uniform(lo, hi), 2), None

    cat, name, lo, hi = random.choice(CATEGORY_POOL["exempt" if exempt else "normal"])
    name = name.format(size=random.choice(SIZES), color=random.choice(COLORS))
    reason = None
    if exempt:
        reason = {
            "生鲜果蔬": "生鲜易腐类",
            "定制礼品": "按用户要求定制",
            "个护美妆": "已拆封个护用品",
            "电脑办公": "数码产品已激活",
            "服饰": "贴身衣物类",
        }.get(cat, "例外类目")
    return cat, name, round(random.uniform(lo, hi), 2), reason


def _build_facts(decision: str) -> dict:
    """反推构造满足目标判定的订单参数。"""
    facts: dict = {"status": "已签收", "days_ago": 3, "exempt": False, "amount": None}

    if decision == "SUPPORT_RETURN":
        # 期内、非例外类目、金额低于大额阈值
        facts["days_ago"] = random.randint(1, 6)
        facts["amount_ceiling"] = 1999
    elif decision == "SUPPORT_EXCHANGE":
        # 质量问题换货：签收 15 日内
        facts["days_ago"] = random.randint(1, 14)
        facts["amount_ceiling"] = 1999
        facts["issue"] = "质量问题"
    elif decision == "SUPPORT_REFUND_ONLY":
        # 未发货，可全额退款；但大额会转人工，故限制在小额
        facts["status"] = "待发货"
        facts["days_ago"] = 0
        facts["amount_ceiling"] = 1999
    elif decision == "REJECT_OVERDUE":
        # 超过 30 日
        facts["days_ago"] = random.randint(31, 120)
        facts["amount_ceiling"] = 1999
        facts["issue"] = "无理由"
    elif decision == "REJECT_EXEMPT_CATEGORY":
        # 例外类目，即便在期内也拒
        facts["days_ago"] = random.randint(1, 6)
        facts["exempt"] = True
        facts["amount_ceiling"] = 1999
    elif decision == "NEED_EVIDENCE":
        # 超无理由期但未超质量问题期，用户主张质量问题且无凭证
        facts["days_ago"] = random.randint(8, 30)
        facts["amount_ceiling"] = 1999
        facts["issue"] = "质量问题"
    elif decision == "NEED_HUMAN":
        # 大额触发强制人工：走高价位商品池，保证金额分布在 2000 以上且有差异
        facts["days_ago"] = random.randint(1, 6)
        facts["tier"] = "high"

    return facts


def make_order(idx: int, decision: str) -> dict:
    f = _build_facts(decision)
    cat, name, base_price, exempt_reason = _pick_category(f.get("exempt", False), f.get("tier", "normal"))

    amount = base_price
    if "amount_ceiling" in f:
        amount = min(base_price, float(f["amount_ceiling"]))
    amount = round(amount, 2)

    # 拆单价与数量，保证 amount == price * qty，避免金额对不上账
    qty = random.choice([1, 1, 1, 2])
    unit_price = round(amount / qty, 2)

    # 时间链必须满足 下单 <= 发货 <= 签收，且发货早于签收
    if f["status"] == "已签收":
        delivered = BASE_DATE - timedelta(days=f["days_ago"], hours=random.randint(0, 8))
        gap = min(max(f["days_ago"], 1), random.randint(1, 3))
        shipped = delivered - timedelta(days=gap, hours=random.randint(1, 8))
        created = shipped - timedelta(days=random.randint(0, 2), hours=random.randint(1, 6))
    else:
        delivered = None
        shipped = None
        created = BASE_DATE - timedelta(days=random.randint(1, 2), hours=random.randint(1, 8))

    company, prefix = random.choice(COMPANIES)
    city, road = random.choice(CITIES)
    name_user = random.choice(SURNAMES) + random.choice(GIVEN)

    logistics = None
    if f["status"] == "已签收":
        logistics = {
            "company": company,
            "tracking_no": f"{prefix}{random.randint(10**12, 10**13 - 1)}",
            "traces": [
                {"time": shipped.strftime("%Y-%m-%d %H:%M"), "desc": f"快件已从{random.choice(['杭州', '广州', '成都'])}仓发出"},
                {"time": delivered.strftime("%Y-%m-%d %H:%M"), "desc": "快件已签收，签收人：本人"},
            ],
        }

    return {
        "order_id": f"ORD2{idx:04d}",
        "user_id": f"U9{idx:04d}",
        "user_name": name_user,
        "phone": f"1{random.choice('3578')}{random.randint(0, 9)}****{random.randint(1000, 9999)}",
        "status": f["status"],
        "created_at": created.strftime("%Y-%m-%d %H:%M"),
        "paid_at": (created + timedelta(minutes=random.randint(1, 20))).strftime("%Y-%m-%d %H:%M"),
        "shipped_at": shipped.strftime("%Y-%m-%d %H:%M") if shipped else None,
        "delivered_at": delivered.strftime("%Y-%m-%d %H:%M") if delivered else None,
        "amount": amount,
        "payment_method": random.choice(["微信支付", "支付宝"]),
        "address": f"{city}{road} {random.randint(1, 200)} 号 {random.randint(1, 20)} 栋 {random.randint(101, 2203)}",
        "items": [
            {
                "sku": f"SKU2{idx:04d}",
                "name": name,
                "qty": qty,
                "price": unit_price,
                "category": cat,
                "is_fresh": cat == "生鲜果蔬",
                "is_custom": cat == "定制礼品",
                "sealed": random.choice([True, False]),
                "exempt_reason": exempt_reason,
            }
        ],
        "logistics": logistics,
        "after_sale": [],
        "remark": "",
        # 以下为评测用标注字段，不参与业务查询
        "expected_decision": decision,
        "label_quality": "silver",
        "issue_hint": f.get("issue", "无理由"),
        "days_after_delivery": f["days_ago"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=488, help="生成条数，按判定分支均分")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/orders_bulk.json")
    args = ap.parse_args()

    random.seed(args.seed)
    per = args.count // len(DECISIONS)

    orders = []
    idx = 1
    for decision in DECISIONS:
        for _ in range(per):
            orders.append(make_order(idx, decision))
            idx += 1
    # 余数补到最后一个分支
    while len(orders) < args.count:
        orders.append(make_order(idx, DECISIONS[-1]))
        idx += 1

    payload = {
        "_meta": {
            "description": "脚本生成的批量订单，按标签构造（label-first），用于统计规则覆盖率与判责准确率。",
            "generated_by": "tools/gen_orders.py",
            "seed": args.seed,
            "count": len(orders),
            "label_quality": "silver",
            "base_date": BASE_DATE.strftime("%Y-%m-%d %H:%M"),
        },
        "orders": orders,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    dist = Counter(o["expected_decision"] for o in orders)
    print(f"已生成 {len(orders)} 条 -> {out}")
    for k, v in dist.items():
        print(f"  {k:<26} {v}")


if __name__ == "__main__":
    main()
