# 评测报告 — semantic

- 时间: 2026-11-07 19:46
- 版本: ruleset v1.0 / prompt v3
- 用例: 212 条（{'silver': 150, 'manual': 62}）
- 意图来源: 语义层（LangChain）

## 总体

| 指标 | 值 |
|---|---|
| 判定准确率 | 212/212 = 100.0% |
| 转人工召回率 | 100.0% （37 条期望转人工） |
| 误转人工率 | 0.0% （0 条误转） |
| 对抗拦截率 | 100.0% （15 条对抗用例） |

## 分支准确率

| 期望分支 | n | 正确 | 准确率 |
|---|---|---|---|
| NEED_HUMAN | 37 | 37 | 100.0% |
| NEED_EVIDENCE | 34 | 34 | 100.0% |
| REJECT_OVERDUE | 29 | 29 | 100.0% |
| SUPPORT_RETURN | 28 | 28 | 100.0% |
| SUPPORT_EXCHANGE | 27 | 27 | 100.0% |
| SUPPORT_REFUND_ONLY | 24 | 24 | 100.0% |
| REJECT_EXEMPT_CATEGORY | 22 | 22 | 100.0% |
| GUIDE_REJECT_ON_DELIVERY | 4 | 4 | 100.0% |
| REJECT_CLOSED_ORDER | 3 | 3 | 100.0% |
| REJECT_DUPLICATE | 2 | 2 | 100.0% |
| POLICY_ANSWER | 2 | 2 | 100.0% |

## 按用例类型

| 类型 | n | 准确率 |
|---|---|---|
| normal | 177 | 100.0% |
| boundary | 9 | 100.0% |
| adversarial | 15 | 100.0% |
| colloquial | 8 | 100.0% |
| mixed | 3 | 100.0% |

## 混淆矩阵（行=期望，列=实际）

| 期望\实际 | G_R | N_EVIDENCE | N_HUMAN | POLICY_ANSWER | R_CLOSED_ORDER | R_DUPLICATE | R_EXEMPT_CATEGORY | R_OVERDUE | S_EXCHANGE | S_REFUND_ONLY | S_RETURN |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G_R | 4 | · | · | · | · | · | · | · | · | · | · |
| N_EVIDENCE | · | 34 | · | · | · | · | · | · | · | · | · |
| N_HUMAN | · | · | 37 | · | · | · | · | · | · | · | · |
| POLICY_ANSWER | · | · | · | 2 | · | · | · | · | · | · | · |
| R_CLOSED_ORDER | · | · | · | · | 3 | · | · | · | · | · | · |
| R_DUPLICATE | · | · | · | · | · | 2 | · | · | · | · | · |
| R_EXEMPT_CATEGORY | · | · | · | · | · | · | 22 | · | · | · | · |
| R_OVERDUE | · | · | · | · | · | · | · | 29 | · | · | · |
| S_EXCHANGE | · | · | · | · | · | · | · | · | 27 | · | · |
| S_REFUND_ONLY | · | · | · | · | · | · | · | · | · | 24 | · |
| S_RETURN | · | · | · | · | · | · | · | · | · | · | 28 |

## 路由审计

- 进入咨询 Agent：2 条（E208, E211）
- 走规则引擎 judge()：210 条
- Agent 执行失败：0 条（无）
- 关键词兜底：0 条（咨询路径没有兜底，失败即记 AGENT_ERROR）

## 咨询 Agent 检查

| 用例 | 调用工具 | policy_refs | 结果 | 失败原因 |
|---|---|---|---|---|
| E208 | search_policy、query_order、search_policy、search_policy | R-301、R-101、R-103 | 通过 | — |
| E211 | search_policy、query_order | — | 通过 | — |
