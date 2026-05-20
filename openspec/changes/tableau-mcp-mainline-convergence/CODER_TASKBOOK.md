# Coder Taskbook: Tableau MCP Mainline Convergence

## 开发目标

将 Tableau MCP Agent 从多路径历史实现收敛到单一主干，并在确认替代方案后删除旧生产路径，降低系统复杂度与后续误用风险。

目标主干：

```text
mcp_proxy_main
  -> strategy classifier
  -> datasource resolver
  -> asset flow / deterministic plan compiler / llm planner
  -> unified guardrail
  -> mcp runtime
  -> response normalizer
  -> renderer
```

## 不可破坏约束

- 不新增独立 MCP Host 平台。
- 不新增通用 MCP Server Registry。
- 不新增 Action DSL。
- 不改变非 Tableau MCP 类型行为。
- 不改变现有 Agent done 契约：`response_type` 与 `response_data` 平级。
- 不在 `response_data` 内包二级 `data`。
- Runtime context 必须通过 `X-Mulan-*` headers 传递，不得写入 query param 或 MCP tool JSON-RPC params。
- 不允许针对 run_id、具体字段名、具体问法写个性化修复。
- Fast Path 必须是统一入口内的 strategy，不得成为旁路。
- 被新主干替代的旧生产路径必须删除或标记为生产不可达。

## Package A: 主干可达路径盘点

交付：

- 画出当前 Tableau MCP 请求从 `agent.py` 到 MCP tool call 的所有生产可达路径。
- 标记每条路径的入口、是否调用 LLM、是否调用 MCP、是否使用 schema_inventory、是否使用 QuerySpec fallback。
- 输出删除清单，注明删除前置条件。

覆盖任务：

- TMC-01

## Package B: 唯一入口与 Response Normalizer

交付：

- `mcp_proxy_main.py` 成为唯一 Tableau MCP controlled chain 入口。
- `schema_inventory` 不再抢答 Tableau MCP 可回答的问题。
- 新增统一 response normalizer。
- 删除旧 normalizer / renderer 分支或转为不可达。

覆盖任务：

- TMC-02
- TMC-03
- TMC-04
- TMC-05
- TMC-06
- TMC-07

## Package C: Resolver 与 Guardrail

交付：

- 新增统一 `DatasourceCandidateResolver`。
- 新增统一 `TableauMcpGuardrailService`。
- 删除重复 resolver 与业务级 guardrail。
- Runtime 只保留基础 schema/resource cap。

覆盖任务：

- TMC-08
- TMC-09
- TMC-10
- TMC-11
- TMC-12
- TMC-13

## Package D: Deterministic Plan Compiler

交付：

- 新增确定性聚合编译器。
- 支持简单聚合、时间趋势、TopN、单指标过滤。
- Compiler 输出标准 `query-datasource` args。
- Compiler 输出必须经过统一 Guardrail。
- 字段歧义返回 clarification。
- 删除个性化规则。

覆盖任务：

- TMC-14
- TMC-15
- TMC-16
- TMC-17
- TMC-18
- TMC-19
- TMC-20
- TMC-21
- TMC-22

## Package E: LLM Planner 收敛

交付：

- LLM Planner 只处理复杂或多步问题。
- Planner 输出进入统一 Guardrail 与 Runtime。
- 设置 latency budget 与结构化失败。
- 删除旧 QuerySpec fallback 生产路径。

覆盖任务：

- TMC-23
- TMC-24
- TMC-25
- TMC-26
- TMC-27

## Package F: TTL Cache

交付：

- tools catalog TTL cache。
- datasource metadata TTL cache。
- cache key 包含 connection scope。
- response 与 telemetry 标记 cache hit/miss/source/freshness。

覆盖任务：

- TMC-28
- TMC-29
- TMC-30
- TMC-31
- TMC-32

## Package G: 删除与验收

交付：

- 删除被替代的旧生产路径。
- 删除重复 resolver、guardrail、normalizer、fallback 分支。
- 文档更新，禁止后续新增旁路。
- 测试更新。
- Docker smoke。

覆盖任务：

- TMC-33
- TMC-34
- TMC-35
- TMC-36
- TMC-37
- TMC-38

## 最低测试断言

后端必须覆盖：

- Tableau MCP 场景只进入 `mcp_proxy_main` controlled chain。
- schema_inventory 不抢答 Tableau MCP 资产类问题。
- “有哪些数据源”返回 `asset_candidates` 清单。
- “介绍 X 数据源”0 候选不返回全量列表。
- “介绍 X 数据源”1 候选直接调用 `get-datasource-metadata`。
- 多候选返回 clarification，不调用 query。
- 简单 `metric by dimension` 不进入 LLM Planner。
- 简单 `metric by time` 不进入 LLM Planner。
- TopN 聚合不进入 LLM Planner。
- Compiler 输出必须经过 Guardrail。
- 字段不存在时 Guardrail 拒绝。
- datasource 不属于 connection 时 Guardrail 拒绝。
- 未授权 connection 时 Guardrail 拒绝。
- Planner 超时返回结构化失败，不伪装成功。
- tools catalog cache 命中后不重复调用 `list_tools`。
- metadata cache 命中后不重复调用 `get-datasource-metadata`。
- `response_data` 内不出现二级 `data` 包裹。

前端必须覆盖：

- `asset_candidates` 清单结构化展示。
- 多候选 clarification 结构化展示。
- `asset_metadata` 字段和分析建议展示。
- `query_result.table_display.columns` 与 fields 一一对应。
- `tool_unavailable` 显示结构化失败，不伪装成成功结果。

## 提交前检查清单

- [ ] 是否删除了被新主干替代的旧生产路径。
- [ ] 是否有任何新旁路绕过 `mcp_proxy_main`。
- [ ] 是否有任何路径绕过统一 Guardrail。
- [ ] 是否有任何个性化正则或 run_id 特判。
- [ ] 是否有任何 Tableau MCP response 不符合扁平 Agent 契约。
- [ ] 是否记录 telemetry span。
- [ ] 是否运行后端相关测试。
- [ ] 是否运行前端结构化响应测试。
- [ ] 是否完成 Docker smoke。

