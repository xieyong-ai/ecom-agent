#!/usr/bin/env python
"""为手工订单补标注字段（gold 标准答案）。

背景：
    gold 样本的作用不是统计，而是验证规则逻辑写对了没有。
    因此它必须覆盖全部 10 个判定分支，否则某个分支写错了也发现不了。

    原始 12 条覆盖 7 个分支，缺 SUPPORT_EXCHANGE 与 SUPPORT_REFUND_ONLY；
    新增 R-502 后又缺 REJECT_CLOSED_ORDER。本脚本补齐这三条，并给所有订单打上：
        expected_decision  期望判定
        label_quality      标注质量（gold = 人工确认）
        expected_evidence  是否已提供凭证（影响 R-103 分支）

用法：
    python tools/label_gold.py
"""

from __future__ import annotations

import json
from pathlib import Path

ORDERS = Path("data/orders.json")

# 订单号 -> (期望判定, 是否已提供凭证, 命中的规则)
LABELS: dict[str, tuple[str, bool, list[str]]] = {
    "ORD10001": ("SUPPORT_RETURN", False, ["R-101", "R-301"]),
    "ORD10002": ("NEED_EVIDENCE", False, ["R-103"]),
    "ORD10003": ("REJECT_OVERDUE", False, ["R-105"]),
    "ORD10004": ("NEED_HUMAN", False, ["R-402"]),
    "ORD10005": ("GUIDE_REJECT_ON_DELIVERY", False, ["R-202"]),
    "ORD10006": ("REJECT_EXEMPT_CATEGORY", False, ["R-102"]),
    "ORD10007": ("REJECT_EXEMPT_CATEGORY", False, ["R-102"]),
    "ORD10008": ("REJECT_DUPLICATE", False, ["R-501"]),
    "ORD10009": ("NEED_HUMAN", False, ["R-402"]),
    "ORD10010": ("NEED_HUMAN", False, ["R-402"]),
    "ORD10011": ("SUPPORT_RETURN", True, ["R-103", "R-301"]),
    "ORD10012": ("REJECT_EXEMPT_CATEGORY", False, ["R-102"]),
    "ORD10013": ("SUPPORT_REFUND_ONLY", False, ["R-201"]),
    "ORD10014": ("SUPPORT_EXCHANGE", True, ["R-104"]),
    "ORD10015": ("REJECT_CLOSED_ORDER", False, ["R-502"]),
    "ORD10016": ("NEED_HUMAN", False, ["R-503"]),
    "ORD10017": ("REJECT_OVERDUE", False, ["R-106"]),
}

# 例外类目需要结构化标记，规则引擎读字段而非猜商品名
EXEMPT_REASONS: dict[str, str] = {
    "ORD10006": "生鲜易腐类",
    "ORD10007": "按用户要求定制",
    "ORD10009": "数码产品已激活",
    "ORD10012": "已拆封个护用品",
    "ORD10014": None,  # 非例外类目
}

# 每条 gold 订单配套一句用户话术。
# 这是评测语义层的唯一输入——没有真实表述，就测不出意图识别准不准。
USER_INPUTS: dict[str, str] = {
    "ORD10001": "我前天买的那双鞋不想要了，能退吗",
    "ORD10002": "电磁炉面板上有划痕，能退吗",
    "ORD10003": "这个包我上个月买的，现在不喜欢了，退了吧",
    "ORD10004": "手机不要了，帮我取消订单",
    "ORD10005": "T 恤还没收到，我不想要了",
    "ORD10006": "车厘子不想要了，可以退吗",
    "ORD10007": "相册不想要了，退掉吧",
    "ORD10008": "上周那个保温杯的退款怎么还没到账，你们是不是没退",
    "ORD10009": "笔记本不想要了，退了吧",
    "ORD10010": "洗衣机转起来有异响，质量问题，我要退",
    "ORD10011": "鞋底开胶了，质量问题要退货，照片已经传了",
    "ORD10012": "洗发水不想要了",
    "ORD10013": "袜子还没发货，我不想要了",
    "ORD10014": "马克杯收到的时候杯口崩了，想换一个，照片传了",
    "ORD10015": "那单我已经取消了，钱怎么还没退给我",
    "ORD10016": "物流显示签收了，可我根本没收到货，退钱",
    "ORD10017": "这个我不想要了，能退吗",
}

# 缺失的两个分支，需要新建订单
NEW_ORDERS = [
    {
        "order_id": "ORD10013",
        "user_id": "U1013",
        "user_name": "许静",
        "phone": "137****4410",
        "status": "待发货",
        "created_at": "2026-10-27 20:15",
        "paid_at": "2026-10-27 20:17",
        "shipped_at": None,
        "delivered_at": None,
        "amount": 158.0,
        "payment_method": "微信支付",
        "address": "安徽省合肥市蜀山区望江西路 500 号 6 栋 1203",
        "items": [
            {
                "sku": "SKU14001",
                "name": "透气网面运动袜 3 双装 均码",
                "qty": 3,
                "price": 52.67,
                "category": "服饰",
                "is_fresh": False,
                "is_custom": False,
                "sealed": True,
                "exempt_reason": None,
            }
        ],
        "logistics": None,
        "after_sale": [],
        "remark": "仓库尚未出库，用户下单后想取消",
    },
    {
        "order_id": "ORD10014",
        "user_id": "U1014",
        "user_name": "马超",
        "phone": "188****7733",
        "status": "已签收",
        "created_at": "2026-10-21 09:20",
        "paid_at": "2026-10-21 09:22",
        "shipped_at": "2026-10-22 10:00",
        "delivered_at": "2026-10-23 16:40",
        "amount": 268.0,
        "payment_method": "支付宝",
        "address": "江西省南昌市红谷滩区赣江中大道 1288 号 3 栋 902",
        "items": [
            {
                "sku": "SKU15001",
                "name": "陶瓷马克杯 350ml 磨砂白",
                "qty": 1,
                "price": 268.0,
                "category": "家居日用",
                "is_fresh": False,
                "is_custom": False,
                "sealed": False,
                "exempt_reason": None,
            }
        ],
        "logistics": {
            "company": "圆通速递",
            "tracking_no": "YT4455667788",
            "traces": [
                {"time": "2026-10-22 10:00", "desc": "已揽收"},
                {"time": "2026-10-23 16:40", "desc": "已签收，签收人：本人"},
            ],
        },
        "after_sale": [],
        "remark": "用户已上传杯口崩瓷照片，要求换货",
    },
    {
        "order_id": "ORD10015",
        "user_id": "U1015",
        "user_name": "邓倩",
        "phone": "139****2288",
        "status": "已取消",
        "created_at": "2026-10-26 11:05",
        "paid_at": "2026-10-26 11:06",
        "shipped_at": None,
        "delivered_at": None,
        "amount": 459.0,
        "payment_method": "微信支付",
        "address": "福建省厦门市思明区软件园二期观日路 12 号 4 栋 501",
        "items": [
            {
                "sku": "SKU16001",
                "name": "无线蓝牙耳机 降噪版 白色",
                "qty": 1,
                "price": 459.0,
                "category": "数码配件",
                "is_fresh": False,
                "is_custom": False,
                "sealed": True,
                "exempt_reason": None,
            }
        ],
        "logistics": None,
        "after_sale": [],
        "remark": "用户在发货前自行取消，交易已终止",
    },
    {
        "order_id": "ORD10016",
        "user_id": "U1016",
        "user_name": "宋涛",
        "phone": "186****9912",
        "status": "已签收",
        "created_at": "2026-10-18 15:40",
        "paid_at": "2026-10-18 15:41",
        "shipped_at": "2026-10-19 09:00",
        "delivered_at": "2026-10-21 18:20",
        "amount": 336.0,
        "payment_method": "支付宝",
        "address": "河北省石家庄市裕华区槐安东路 66 号 2 栋 1802",
        "items": [
            {
                "sku": "SKU17001",
                "name": "筋膜枪 静音款 4 档",
                "qty": 1,
                "price": 336.0,
                "category": "运动户外",
                "is_fresh": False,
                "is_custom": False,
                "sealed": True,
                "exempt_reason": None,
            }
        ],
        "logistics": {
            "company": "中通快递",
            "tracking_no": "ZT1122334455",
            "traces": [
                {"time": "2026-10-19 09:00", "desc": "已揽收"},
                {"time": "2026-10-21 18:20", "desc": "已签收，签收人：门卫代收"},
            ],
        },
        "after_sale": [],
        "remark": "用户否认收到货，签收人为门卫代收，事实存疑",
        # 用户主张未收到货：与签收记录冲突，触发 R-503
        "logistics_disputed": True,
    },
    {
        "order_id": "ORD10017",
        "user_id": "U1017",
        "user_name": "韩雪",
        "phone": "135****6677",
        "status": "已签收",
        "created_at": "2026-10-09 10:20",
        "paid_at": "2026-10-09 10:22",
        "shipped_at": "2026-10-10 08:30",
        "delivered_at": "2026-10-12 14:10",
        "amount": 288.0,
        "payment_method": "微信支付",
        "address": "江苏省苏州市工业园区星湖街 328 号 5 栋 902",
        "items": [
            {
                "sku": "SKU18001",
                "name": "加厚冬季家居服 珊瑚绒 女款",
                "qty": 1,
                "price": 288.0,
                "category": "服饰",
                "is_fresh": False,
                "is_custom": False,
                "sealed": True,
                "exempt_reason": None,
            }
        ],
        "logistics": {
            "company": "韵达快递",
            "tracking_no": "YD9988776655",
            "traces": [
                {"time": "2026-10-10 08:30", "desc": "已揽收"},
                {"time": "2026-10-12 14:10", "desc": "已签收，签收人：本人"},
            ],
        },
        "after_sale": [],
        "remark": "签收 16 天，用户主张无理由退货，已过七天无理由期",
    },
]


def main() -> None:
    data = json.loads(ORDERS.read_text(encoding="utf-8"))
    orders = data["orders"]

    existing = {o["order_id"] for o in orders}
    for order in NEW_ORDERS:
        if order["order_id"] not in existing:
            orders.append(order)

    orders.sort(key=lambda o: o["order_id"])

    for o in orders:
        oid = o["order_id"]
        if oid not in LABELS:
            raise SystemExit(f"缺少标注: {oid}")
        decision, evidence, refs = LABELS[oid]
        o["expected_decision"] = decision
        o["expected_evidence"] = evidence
        o["expected_refs"] = refs
        o["label_quality"] = "gold"
        o["user_input"] = USER_INPUTS[oid]
        if oid in EXEMPT_REASONS:
            o["items"][0]["exempt_reason"] = EXEMPT_REASONS[oid]

    ORDERS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    from collections import Counter

    dist = Counter(o["expected_decision"] for o in orders)
    print(f"已标注 {len(orders)} 条 gold 订单 -> {ORDERS}")
    for k, v in sorted(dist.items()):
        print(f"  {k:<26} {v}")

    all_branches = {
        "SUPPORT_RETURN", "SUPPORT_EXCHANGE", "SUPPORT_REFUND_ONLY",
        "GUIDE_REJECT_ON_DELIVERY", "REJECT_OVERDUE", "REJECT_EXEMPT_CATEGORY",
        "REJECT_DUPLICATE", "REJECT_CLOSED_ORDER", "NEED_EVIDENCE", "NEED_HUMAN",
    }
    missing = all_branches - set(dist)
    print("\n分支覆盖:", f"全部 {len(all_branches)} 个分支已覆盖" if not missing else f"缺 {missing}")


if __name__ == "__main__":
    main()
