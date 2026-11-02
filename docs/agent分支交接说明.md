# 交接说明：给判责引擎的咨询分支实现工具调用 Agent

> 本文档是完整的开发任务书，面向接手的 AI 编程助手（Claude Code 等）。
> 项目已有完整实现与评测体系，本次只新增"咨询分支的 Agent 路径"，
> **不得改动现有判定逻辑**。动手前请先读完本文档并遵守所有约束。
>
> **实施备注（2026-11-02）**：任务书写于锁定 LangChain 1.4.7 之前。该版本已移除
> `create_tool_calling_agent` / `AgentExecutor`，官方替代为 `langchain.agents.create_agent`。
> 实际实现没有直接使用 `create_agent`，而是在 `core/agent.py` 按其三个契约
> （迭代上限 / 中间步骤留痕 / 解析错误回灌）手写最小执行器。详见
> `docs/咨询分支验收报告.md`。正文保留原始任务要求，仅作历史记录。

## 项目背景（30 秒）

电商售后判责引擎，位于本目录。核心原则：**Rule-first——规则引擎产生判定结论（decision），LLM 只做语义理解（意图识别、类目判定），模型无权产生 decision 字段**。

现有结构：

```
core/
├── schema.py     # 枚举、Verdict 判定单、不变量校验
├── facts.py      # 事实层：Facts/store()，订单查询、状态归并、天数计算
├── rules.py      # 规则引擎：judge()，18 条规则 13 层优先级仲裁
└── semantics.py  # 语义层：recognize_ex(text) -> (Intent, exchange, source)
app.py            # Streamlit 界面
eval/run_eval.py  # 212 条评测（data/eval_cases.jsonl）
eval/audit_matrix.py  # 9 维 13800 组合穷举审计
data/policies.md  # 规则库原文（### R-xxx 标题结构）
```

现有意图枚举中 **POLICY_QUERY（政策咨询）** 是唯一"开放式问答"类诉求，当前只回一句引导话术。本次任务：给这条分支接上真正的工具调用 Agent。

## 任务目标

工单意图为 POLICY_QUERY 时，走工具调用 Agent 路径，产出"咨询答复单"；**其他所有意图仍走现有 judge()，行为零变化**。（原文写的 `AgentExecutor` 在 LangChain 1.4.7 已移除，实际实现见文首"实施备注"。）

## 具体改动

### 1. 新增 `core/tools.py`

四个**只读**工具（用 `langchain_core.tools.tool` 装饰器）：

| 工具 | 功能 | 实现依据 |
|---|---|---|
| `query_order(order_id)` | 返回 status/days_since_delivery/amount/exempt_reason/is_duplicated | `core.facts.store().facts()` |
| `search_policy(question)` | 检索规则库，返回命中条款编号 + 原文 | 解析 `data/policies.md` 的 `### R-xxx` 结构做关键词/BM25 检索，**不引入向量库**（18 条规则用不上） |
| `calc_return_window(order_id)` | 计算七天无理由/质量期剩余天数 | 复用 facts 的 days_since_delivery |
| `check_logistics(order_id)` | 返回物流轨迹（模拟数据即可） | 可造一份静态 trace 数据 |

**硬约束：不提供任何写操作或退款工具**。工具的 docstring 要写清楚用途（Agent 靠它决定调不调）。

### 2. 新增 `core/agent.py`

- `create_tool_calling_agent` + `AgentExecutor`，参数：`max_iterations=6`、`return_intermediate_steps=True`、`handle_parsing_errors=True`。
  （这两个 API 在 LangChain 1.4.7 已移除；实际实现见文首"实施备注"。）
- 复用 `core/semantics.py` 的 `get_llm()`（DeepSeek，OpenAI 兼容）。
- 系统提示词要点：你是售后政策咨询助手；回答必须基于 `search_policy` 检索到的条款原文，检索不到就如实说"规则库未覆盖，建议转人工"，**禁止编造条款编号**；无 API Key 时此路径不可用（返回明确错误，不降级）。
- 返回结构化结果：`{"answer": str, "policy_refs": [...], "tool_trace": [...中间步骤...]}`，其中 policy_refs 只能来自 search_policy 的实际返回。

### 3. 修改 `core/semantics.py` 或新增路由函数

在 `decide()`（app.py）或其调用的模块中：`intent == POLICY_QUERY` 且语义层可用 → 走 Agent 路径；否则维持现状。**judge() 一行都不许改。**

### 4. 修改 `app.py` 展示

咨询类判定单展示：答复正文 + 引用条款（可展开原文，复用现有 `load_policy_text`）+ 工具调用 trace（第几步调了什么工具、参数、返回摘要）。

### 5. 评测扩展

- `data/eval_cases.jsonl` 中 case_type 含咨询类的用例，补 `expected_tools` 字段（如 `["query_order", "search_policy"]`）。
- `eval/run_eval.py`：Agent 路径增加"工具选择是否包含期望工具、是否调用了不存在的工具、policy_refs 是否真实"三项检查。
- **回归底线：非咨询类 212 条评测结果必须与改造前完全一致**（语义层 212/212 不许掉）。

## 验收标准

1. `python eval/run_eval.py`：非咨询用例全过、结果与改造前一致；
2. `python eval/audit_matrix.py`：13800 组合 0 违规（不应受影响，跑通即证）；
3. 手工验证 3 条咨询工单：答复引用了真实条款编号、trace 完整、无 API Key 时明确报错而非静默降级；
4. Streamlit 界面咨询路径可视化正常。

## 环境注意事项

- 用项目自带 `.venv/Scripts/python.exe`（Windows），依赖已锁定在 requirements-lock.txt，**不要升级 langchain**（当前 1.4.7）；
- API Key 在 `.env`，读法参考 `core/semantics.py` 的 `get_llm()`；
- 改完 `core/` 下代码后 Streamlit 需重启（`stop.bat` → `start.bat`）。

## 完成后同步文档

`docs/技术文档.md`（§5 语义层补 Agent 小节）、`docs/项目设计文档.md`（确认咨询分支状态为已落地）、`README.md`（架构图加路径 B）。
