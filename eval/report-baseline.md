# 评测报告 — baseline

- 时间: 2026-11-07 20:07
- 版本: ruleset v1.0 / prompt v2
- 用例: 212 条（{'silver': 150, 'manual': 62}）
- 意图来源: 关键词降级（未调用模型）

## 总体

| 指标 | 值 |
|---|---|
| 判定准确率 | 203/212 = 95.8% |
| 转人工召回率 | 100.0% （37 条期望转人工） |
| 误转人工率 | 4.6% （8 条误转） |
| 对抗拦截率 | 86.7% （15 条对抗用例） |

## 分支准确率

| 期望分支 | n | 正确 | 准确率 |
|---|---|---|---|
| NEED_HUMAN | 37 | 37 | 100.0% |
| NEED_EVIDENCE | 34 | 28 | 82.4% |
| REJECT_OVERDUE | 29 | 29 | 100.0% |
| SUPPORT_RETURN | 28 | 27 | 96.4% |
| SUPPORT_EXCHANGE | 27 | 26 | 96.3% |
| SUPPORT_REFUND_ONLY | 24 | 24 | 100.0% |
| REJECT_EXEMPT_CATEGORY | 22 | 22 | 100.0% |
| GUIDE_REJECT_ON_DELIVERY | 4 | 4 | 100.0% |
| REJECT_CLOSED_ORDER | 3 | 3 | 100.0% |
| REJECT_DUPLICATE | 2 | 2 | 100.0% |
| POLICY_ANSWER | 2 | 1 | 50.0% |

## 按用例类型

| 类型 | n | 准确率 |
|---|---|---|
| normal | 177 | 98.9% |
| boundary | 9 | 88.9% |
| adversarial | 15 | 86.7% |
| colloquial | 8 | 50.0% |
| mixed | 3 | 100.0% |

## 混淆矩阵（行=期望，列=实际）

| 期望\实际 | G_R | N_EVIDENCE | N_HUMAN | POLICY_ANSWER | R_CLOSED_ORDER | R_DUPLICATE | R_EXEMPT_CATEGORY | R_OVERDUE | S_EXCHANGE | S_REFUND_ONLY | S_RETURN |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G_R | 4 | · | · | · | · | · | · | · | · | · | · |
| N_EVIDENCE | · | 28 | 5 | · | · | · | · | · | 1 | · | · |
| N_HUMAN | · | · | 37 | · | · | · | · | · | · | · | · |
| POLICY_ANSWER | · | · | 1 | 1 | · | · | · | · | · | · | · |
| R_CLOSED_ORDER | · | · | · | · | 3 | · | · | · | · | · | · |
| R_DUPLICATE | · | · | · | · | · | 2 | · | · | · | · | · |
| R_EXEMPT_CATEGORY | · | · | · | · | · | · | 22 | · | · | · | · |
| R_OVERDUE | · | · | · | · | · | · | · | 29 | · | · | · |
| S_EXCHANGE | · | · | 1 | · | · | · | · | · | 26 | · | · |
| S_REFUND_ONLY | · | · | · | · | · | · | · | · | · | 24 | · |
| S_RETURN | · | · | 1 | · | · | · | · | · | · | · | 27 |
