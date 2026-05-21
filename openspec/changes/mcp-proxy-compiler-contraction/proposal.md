# Proposal: mcp-proxy-compiler-contraction

## Overview

本变更收缩并优化 `deterministic_plan_compiler` 在首页 Tableau 问数链路中的权限。

目标不是删除 compiler，也不是把它压缩到只能处理单指标；而是将它定位为：

- **受限 fast path planner**：支持单指标与简单显式多指标的高置信快速编译；
- **structured advisory provider**：无法安全编译时，把候选字段、歧义原因、已识别指标/维度作为结构化上下文传给后续 MCP Host / LLM Planner；
- **非安全组件**：不负责权限、limit、字段合规、datasource 归属等安全判断；
- **非最终事实源**：不得绕过 Tableau MCP 直接生成用户可见业务事实。
- **无状态字段匹配器**：不维护 `last_query_context`，不读取历史对话，不执行追问 delta 合并。

修订后的原则：

```text
Compiler / LLM Planner 只生产候选 MCP payload
-> 统一进入 MCPToolExecutor.execute()
-> Executor 内部调用 TableauMcpGuardrailService
-> Tableau MCP Server
-> response normalizer
-> table_display.columns
-> renderer
```

## Motivation

`run_id=33c1acd6-63ed-4381-9ac5-3fd9158e35c5` 暴露了一个 P0 质量问题。

用户问题：

```text
整体的销售额、利润、利润率、客户数、客单价是什么样子
```

首页实际结果：

- `response_type=clarification`
- `tools_used={context_resolver,deterministic_plan_compiler}`
- 未调用 `tableau_mcp`
- 返回「匹配到多个可能字段，请选择一个后继续。」

直接 Tableau MCP 对照可以一次返回：

```text
SUM(销售额)
SUM(利润)
利润率
客户数
客单价
```

因此问题不是 Tableau MCP 能力不足，而是 Mulan 在 MCP 之前由 `deterministic_plan_compiler` 抢跑并错误拦截。

同时，简单多指标是高频生产场景，例如：

```text
今天 A、B、C 部门的利润和销售额是多少
整体的销售额、利润、利润率、客户数、客单价是什么样子
```

Tableau MCP `query-datasource` 支持多个 aggregate/calculated fields。若所有多指标请求都落回慢速 LLM Planner，会显著恶化 P95 延迟。因此 compiler 应增强为支持 **simple explicit multi-metric fast path**，而不是一刀切 unsupported。

## Goals

1. 将 `deterministic_plan_compiler` 定位为 `limited_fast_path_planner + structured_advisory_provider`。
2. 支持简单单指标 fast path。
3. 支持简单显式多指标 fast path。
4. 强歧义必须返回 clarification，阻断执行，不能交给 LLM 随机猜。
5. 非强歧义、部分匹配、复杂语义等场景生成 structured advisory，并透传给 MCP Host / LLM Planner。
6. 从 compiler 中移除 `safety_rejected` 语义；安全与合规统一由 `TableauMcpGuardrailService` / executor 处理。
7. compiler 与 LLM Planner 生成的 payload 必须进入同一个 `MCPToolExecutor.execute()` 漏斗。
8. 所有成功问数答案必须有真实 Tableau MCP tool call trace。
9. 所有 table response 必须包含 `fields` / `rows` / `table_display.columns`。
10. 明确 compiler 无状态：追问上下文合并必须在进入 compiler 之前完成，并作为本轮一次性 analysis context / resolved intent 输入。

## Non-Goals

1. 不删除 `deterministic_plan_compiler`。
2. 不把多指标全部交给 LLM Planner。
3. 不新增通用 MCP Server Registry。
4. 不新增自定义 action DSL。
5. 不恢复 QuerySpec 作为新主链路 planning contract。
6. 不让 renderer、DCE 或 response assembler 计算业务事实。
7. 不让 compiler 承担权限、安全、limit、字段合规职责。
8. 不在 MCP unavailable 时 fallback 到 schema inventory / 字段枚举 / asset list 冒充成功。
9. 不让 compiler 维护 conversation state、读取历史 run、合并上一轮 query context。
10. 不让 compiler 实现 `add_breakdown` / `replace_breakdown` / `add_metric` 等追问 delta 运算。
11. 不在 planner parser 业务代码中静默补齐字段；可缺省字段必须通过 Pydantic Model / JSON Schema 声明 optional。

## Scope

主要涉及：

- `backend/services/data_agent/mcp_proxy_main.py`
- `backend/services/data_agent/tableau_mcp_plan_compiler.py`
- `backend/services/data_agent/mcp_host/runtime.py`
- `backend/services/data_agent/tableau_mcp_guardrail.py`
- `backend/services/data_agent/table_display.py`
- `backend/tests/services/data_agent/test_mcp_proxy_main.py`
- `backend/tests/services/data_agent/test_tableau_mcp_plan_compiler.py`

## Acceptance Summary

核心回归问题：

```text
整体的销售额、利润、利润率、客户数、客单价是什么样子
```

必须满足：

- 不返回 compiler clarification；
- 可作为 simple multi-metric fast path 直接生成 `query-datasource` payload；
- payload 进入统一 `MCPToolExecutor.execute()`；
- executor 内部经过 `TableauMcpGuardrailService`；
- 必须调用 Tableau MCP；
- `response_type=query_result`；
- `fields` 覆盖用户显式指标；
- `rows` 来自 Tableau MCP；
- `table_display.columns` 与 `fields` 一一对应。

强歧义问题必须满足：

- 多个 exact/alias 高置信候选且上下文无法消歧时，返回 clarification；
- 不交给 LLM Planner 猜测；
- 不调用 Tableau MCP。
