# 咨询 Agent 评测报告 — consultation

- 时间: 2026-11-07 20:37
- 版本: ruleset v1.0 / prompt v2
- 用例: 33 条（独立于 212 条判定回归基线）

## 总体

| 指标 | 值 |
|---|---|
| 工具调用与引用可验证性 | 33/33 = 100.0% |
| 进入 Agent 工具循环 | 33/33 |
| 实际发生工具调用 | 33/33 |
| 未调用工具且成功作答 | 0/33 |
| 未调用工具且执行失败 | 0/33 |
| 关键词兜底 | 0/33（该路径没有兜底，失败即报错） |
| Agent 执行失败 | 0/33 |

> 口径：该指标检查「是否按期望调用工具、`policy_refs` 是否来自 `search_policy` 实际返回、答复有没有 `decision`、失败是否显式」，**不是咨询答复文本的自然语言准确率**。

## 明细

| 用例 | 类型 | 工具调用（次） | policy_refs | 引用数（实际/期望） | 精确度 | 结果 | 失败原因 |
|---|---|---|---|---|---|---|---|
| C001 | generic_rule | search_policy（1） | R-101、R-301 | 2/1 | 50% | 通过 | — |
| C002 | generic_rule | search_policy、search_policy（2） | R-103 | 1/1 | 100% | 通过 | — |
| C003 | generic_rule | search_policy（1） | R-104 | 1/1 | 100% | 通过 | — |
| C004 | generic_rule | search_policy（1） | R-301、R-101 | 2/1 | 50% | 通过 | — |
| C005 | generic_rule | search_policy（1） | R-401 | 1/1 | 100% | 通过 | — |
| C006 | generic_rule | search_policy（1） | R-102 | 1/1 | 100% | 通过 | — |
| C007 | generic_rule | search_policy（1） | R-103 | 1/1 | 100% | 通过 | — |
| C008 | order_specific | search_policy、calc_return_window（2） | R-101 | 1/1 | 100% | 通过 | — |
| C009 | order_specific | check_logistics、search_policy（2） | R-202 | 1/— | — | 通过 | — |
| C010 | order_specific | search_policy、calc_return_window、query_order（3） | R-105 | 1/1 | 100% | 通过 | — |
| C011 | not_covered | search_policy、query_order（2） | — | 0/— | — | 通过 | — |
| C012 | not_covered | search_policy（1） | R-504 | 1/1 | 100% | 通过 | — |
| C013 | not_covered | search_policy（1） | — | 0/— | — | 通过 | — |
| C014 | adversarial | search_policy、query_order、calc_return_window、search_policy、search_policy、search_policy（6） | R-101、R-103、R-104、R-301 | 4/— | — | 通过 | — |
| C015 | adversarial | query_order、search_policy（2） | R-401 | 1/— | — | 通过 | — |
| C016 | tool_failure | query_order、calc_return_window、search_policy（3） | — | 0/— | — | 通过 | — |
| C017 | order_specific | query_order、calc_return_window、search_policy（3） | R-103 | 1/1 | 100% | 通过 | — |
| C018 | generic_rule | search_policy（1） | R-201、R-301 | 2/1 | 50% | 通过 | — |
| C019 | order_specific | query_order、search_policy（2） | — | 0/— | — | 通过 | — |
| C020 | order_specific | check_logistics、search_policy（2） | R-202、R-301 | 2/1 | 50% | 通过 | — |
| C021 | generic_rule | search_policy（1） | R-402、R-504 | 2/1 | 50% | 通过 | — |
| C022 | generic_rule | search_policy（1） | R-501 | 1/1 | 100% | 通过 | — |
| C023 | generic_rule | search_policy（1） | R-502 | 1/1 | 100% | 通过 | — |
| C024 | generic_rule | search_policy（1） | R-503 | 1/1 | 100% | 通过 | — |
| C025 | generic_rule | search_policy（1） | R-505 | 1/1 | 100% | 通过 | — |
| C026 | generic_rule | search_policy、search_policy（2） | R-102、R-103、R-104、R-301 | 4/1 | 25% | 通过 | — |
| C027 | generic_rule | search_policy（1） | R-102 | 1/1 | 100% | 通过 | — |
| C028 | generic_rule | search_policy（1） | R-102 | 1/1 | 100% | 通过 | — |
| C029 | generic_rule | search_policy（1） | R-301 | 1/1 | 100% | 通过 | — |
| C030 | generic_rule | search_policy（1） | R-401 | 1/1 | 100% | 通过 | — |
| C031 | generic_rule | search_policy（1） | R-201、R-401 | 2/1 | 50% | 通过 | — |
| C032 | generic_rule | search_policy（1） | R-202 | 1/1 | 100% | 通过 | — |
| C033 | generic_rule | search_policy（1） | R-101、R-106 | 2/1 | 50% | 通过 | — |

## 引用精确度（仅度量，不参与通过判定）

- 可计算用例：26/33（有 `expected_refs`）
- 实际引用合计：36 条；期望引用合计：26 条；命中：26 条
- 微平均精确度：26/36 = 72.2%
- 宏平均精确度（逐条平均）：83.7%
- 过度引用：8/26 条用例，额外引用合计 10 条
- 无期望条款用例：7 条（C009、C011、C013、C014、C015、C016、C019），不计算精确度

> 精确度 = |policy_refs ∩ expected_refs| / |policy_refs|。引用不足（漏掉期望条款）已在通过判定中作为失败处理；本表只度量反向的过度引用，不改变判定口径。

| 用例 | 期望条款 | 实际引用 | 额外引用 | 精确度 |
|---|---|---|---|---|
| C001 | R-101 | R-101、R-301 | R-301 | 50% |
| C004 | R-301 | R-301、R-101 | R-101 | 50% |
| C018 | R-301 | R-201、R-301 | R-201 | 50% |
| C020 | R-202 | R-202、R-301 | R-301 | 50% |
| C021 | R-402 | R-402、R-504 | R-504 | 50% |
| C026 | R-103 | R-102、R-103、R-104、R-301 | R-102、R-104、R-301 | 25% |
| C031 | R-201 | R-201、R-401 | R-401 | 50% |
| C033 | R-106 | R-101、R-106 | R-101 | 50% |
