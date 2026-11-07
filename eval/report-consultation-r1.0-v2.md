# 咨询 Agent 评测报告 — consultation

- 时间: 2026-11-07 19:39
- 用例: 33 条（独立于 212 条判定回归基线）

## 总体

| 指标 | 值 |
|---|---|
| 工具调用与引用可验证性 | 32/33 = 97.0% |
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
| C002 | generic_rule | search_policy（1） | R-103 | 1/1 | 100% | 通过 | — |
| C003 | generic_rule | search_policy（1） | R-104 | 1/1 | 100% | 通过 | — |
| C004 | generic_rule | search_policy（1） | R-301、R-101 | 2/1 | 50% | 通过 | — |
| C005 | generic_rule | search_policy（1） | R-401 | 1/1 | 100% | 通过 | — |
| C006 | generic_rule | search_policy（1） | R-102、R-101 | 2/1 | 50% | 通过 | — |
| C007 | generic_rule | search_policy（1） | R-103 | 1/1 | 100% | 通过 | — |
| C008 | order_specific | search_policy、calc_return_window（2） | R-101 | 1/1 | 100% | 通过 | — |
| C009 | order_specific | check_logistics、search_policy（2） | R-202 | 1/— | — | 通过 | — |
| C010 | order_specific | search_policy、calc_return_window、query_order（3） | R-105 | 1/1 | 100% | 通过 | — |
| C011 | not_covered | search_policy、query_order（2） | — | 0/— | — | 通过 | — |
| C012 | not_covered | search_policy（1） | R-504 | 1/1 | 100% | 通过 | — |
| C013 | not_covered | search_policy（1） | — | 0/— | — | 通过 | — |
| C014 | adversarial | search_policy、search_policy（2） | R-101、R-103、R-104、R-106、R-102 | 5/— | — | 通过 | — |
| C015 | adversarial | query_order、search_policy（2） | — | 0/— | — | 通过 | — |
| C016 | tool_failure | query_order、calc_return_window、search_policy（3） | — | 0/— | — | 通过 | — |
| C017 | order_specific | query_order、calc_return_window、search_policy、search_policy（4） | R-103、R-301 | 2/1 | 50% | 通过 | — |
| C018 | generic_rule | search_policy（1） | R-201、R-301 | 2/1 | 50% | 通过 | — |
| C019 | order_specific | query_order、search_policy（2） | — | 0/— | — | 通过 | — |
| C020 | order_specific | check_logistics、search_policy（2） | R-202、R-301 | 2/1 | 50% | 通过 | — |
| C021 | generic_rule | search_policy（1） | R-402、R-504 | 2/1 | 50% | 通过 | — |
| C022 | generic_rule | search_policy（1） | R-501 | 1/1 | 100% | 通过 | — |
| C023 | generic_rule | search_policy（1） | R-502 | 1/1 | 100% | 通过 | — |
| C024 | generic_rule | search_policy（1） | R-503 | 1/1 | 100% | 通过 | — |
| C025 | generic_rule | search_policy（1） | R-505 | 1/1 | 100% | 通过 | — |
| C026 | generic_rule | search_policy（1） | R-102 | 1/1 | 0% | 失败 | 缺少期望条款: ['R-103'] |
| C027 | generic_rule | search_policy（1） | R-102、R-301 | 2/1 | 50% | 通过 | — |
| C028 | generic_rule | search_policy（1） | R-102 | 1/1 | 100% | 通过 | — |
| C029 | generic_rule | search_policy（1） | R-301 | 1/1 | 100% | 通过 | — |
| C030 | generic_rule | search_policy（1） | R-401 | 1/1 | 100% | 通过 | — |
| C031 | generic_rule | search_policy（1） | R-201、R-401、R-301 | 3/1 | 33% | 通过 | — |
| C032 | generic_rule | search_policy（1） | R-202 | 1/1 | 100% | 通过 | — |
| C033 | generic_rule | search_policy（1） | R-101、R-106 | 2/1 | 50% | 通过 | — |

## 引用精确度（仅度量，不参与通过判定）

- 可计算用例：26/33（有 `expected_refs`）
- 实际引用合计：37 条；期望引用合计：26 条；命中：25 条
- 微平均精确度：25/37 = 67.6%
- 宏平均精确度（逐条平均）：76.3%
- 过度引用：11/26 条用例，额外引用合计 12 条
- 无期望条款用例：7 条（C009、C011、C013、C014、C015、C016、C019），不计算精确度

> 精确度 = |policy_refs ∩ expected_refs| / |policy_refs|。引用不足（漏掉期望条款）已在通过判定中作为失败处理；本表只度量反向的过度引用，不改变判定口径。

| 用例 | 期望条款 | 实际引用 | 额外引用 | 精确度 |
|---|---|---|---|---|
| C001 | R-101 | R-101、R-301 | R-301 | 50% |
| C004 | R-301 | R-301、R-101 | R-101 | 50% |
| C006 | R-102 | R-102、R-101 | R-101 | 50% |
| C017 | R-103 | R-103、R-301 | R-301 | 50% |
| C018 | R-301 | R-201、R-301 | R-201 | 50% |
| C020 | R-202 | R-202、R-301 | R-301 | 50% |
| C021 | R-402 | R-402、R-504 | R-504 | 50% |
| C026 | R-103 | R-102 | R-102 | 0% |
| C027 | R-102 | R-102、R-301 | R-301 | 50% |
| C031 | R-201 | R-201、R-401、R-301 | R-401、R-301 | 33% |
| C033 | R-106 | R-101、R-106 | R-101 | 50% |

## 失败明细（1 条）

### C026 — 生鲜水果坏了能退吗？
- 缺少期望条款: ['R-103']
- 实际工具调用：
  - 第 1 步 `search_policy`（成功，refs=['R-102', 'R-202', 'R-601', 'R-503']）

> 生鲜水果属于不适用七天无理由退货的例外类目，但**质量问题仍然可以退换**。

具体规则如下：

1. **无理由退货不适用**：生鲜果蔬、冷藏冷冻类商品因易腐变质、退货后无法二次销售，被列入不适用七天无理由退货的例外类目（R-102）。即使刚签收当天提出，无理由退货申请也会被拒绝。

2. **质量问题仍可退换**：例外类目并不排除质量问题的售后。如果您主张的是商品变质、腐烂等质量问题，不按无理由退货处理，而是按质量问题退换规则处理（R-102 明确指向 R-103）。也就是说，水果坏了属于质量问题范畴，可以走质量问题的退货/换货流程。

3. **时限与运费**：质量问题退货、换货的具体时限和运费承担，需要结合您的实际签收时间判断。您提供订单号后，我可以帮您查询该单的签收时间、剩余窗口天数以及是否属于生鲜例外类目。

另外说明：以上是规则层面的解答。如果您要对某一笔具体订单提出退货诉求，请提供订单号，我再按该单事实为您核对；我这边没有退款或审批权限，实际售后需要走平台售后入口或转人工处理。

