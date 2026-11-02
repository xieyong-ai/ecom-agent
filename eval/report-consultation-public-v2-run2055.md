# 咨询 Agent 评测报告 — consultation-public-v2

- 时间: 2026-11-02 20:55
- 用例: 20 条（独立于 212 条判定回归基线）

## 总体

| 指标 | 值 |
|---|---|
| 工具调用与引用可验证性 | 20/20 = 100.0% |
| 进入 Agent 工具循环 | 20/20 |
| 实际发生工具调用 | 20/20 |
| 未调用工具且成功作答 | 0/20 |
| 未调用工具且执行失败 | 0/20 |
| 关键词兜底 | 0/20（该路径没有兜底，失败即报错） |
| Agent 执行失败 | 0/20 |

> 口径：该指标检查「是否按期望调用工具、`policy_refs` 是否来自 `search_policy` 实际返回、答复有没有 `decision`、失败是否显式」，**不是咨询答复文本的自然语言准确率**。

## 明细

| 用例 | 类型 | 工具调用（次） | policy_refs | 引用数（实际/期望） | 精确度 | 结果 | 失败原因 |
|---|---|---|---|---|---|---|---|
| P001 | public_seed | search_policy（1） | R-101、R-102、R-106、R-104 | 4/1 | 25% | 通过 | — |
| P002 | public_seed | search_policy（1） | R-301 | 1/1 | 100% | 通过 | — |
| P003 | public_seed | search_policy、search_policy（2） | R-103、R-301、R-102 | 3/1 | 33% | 通过 | — |
| P004 | public_seed | search_policy（1） | R-102 | 1/1 | 100% | 通过 | — |
| P005 | public_seed | search_policy（1） | R-102 | 1/1 | 100% | 通过 | — |
| P006 | public_seed | search_policy（1） | R-102、R-101 | 2/1 | 50% | 通过 | — |
| P007 | public_seed | search_policy（1） | R-102 | 1/1 | 100% | 通过 | — |
| P008 | public_seed | search_policy（1） | R-101、R-106 | 2/1 | 50% | 通过 | — |
| P009 | public_seed | search_policy（1） | R-103、R-104、R-105 | 3/1 | 33% | 通过 | — |
| P010 | public_seed | search_policy（1） | R-201、R-301、R-401 | 3/1 | 33% | 通过 | — |
| P011 | public_seed | search_policy（1） | R-202、R-301 | 2/1 | 50% | 通过 | — |
| P012 | public_seed | search_policy（1） | R-503 | 1/1 | 100% | 通过 | — |
| P013 | public_seed | search_policy（1） | R-501 | 1/1 | 100% | 通过 | — |
| P014 | public_seed | search_policy（1） | R-502 | 1/1 | 100% | 通过 | — |
| P015 | public_seed | search_policy、search_policy（2） | R-505 | 1/1 | 100% | 通过 | — |
| P016 | public_seed | search_policy（1） | R-402 | 1/1 | 100% | 通过 | — |
| P017 | public_seed | search_policy（1） | R-401 | 1/1 | 100% | 通过 | — |
| P018 | public_seed | search_policy（1） | R-104 | 1/1 | 100% | 通过 | — |
| P019 | public_seed | search_policy、search_policy（2） | R-103、R-301 | 2/1 | 50% | 通过 | — |
| P020 | public_seed | search_policy（1） | R-301 | 1/1 | 100% | 通过 | — |

## 引用精确度（仅度量，不参与通过判定）

- 可计算用例：20/20（有 `expected_refs`）
- 实际引用合计：33 条；期望引用合计：20 条；命中：20 条
- 微平均精确度：20/33 = 60.6%
- 宏平均精确度（逐条平均）：76.2%
- 过度引用：8/20 条用例，额外引用合计 13 条

> 精确度 = |policy_refs ∩ expected_refs| / |policy_refs|。引用不足（漏掉期望条款）已在通过判定中作为失败处理；本表只度量反向的过度引用，不改变判定口径。

| 用例 | 期望条款 | 实际引用 | 额外引用 | 精确度 |
|---|---|---|---|---|
| P001 | R-101 | R-101、R-102、R-106、R-104 | R-102、R-106、R-104 | 25% |
| P003 | R-103 | R-103、R-301、R-102 | R-301、R-102 | 33% |
| P006 | R-102 | R-102、R-101 | R-101 | 50% |
| P008 | R-106 | R-101、R-106 | R-101 | 50% |
| P009 | R-105 | R-103、R-104、R-105 | R-103、R-104 | 33% |
| P010 | R-201 | R-201、R-301、R-401 | R-301、R-401 | 33% |
| P011 | R-202 | R-202、R-301 | R-301 | 50% |
| P019 | R-103 | R-103、R-301 | R-301 | 50% |
