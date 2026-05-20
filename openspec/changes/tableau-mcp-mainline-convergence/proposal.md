# Proposal: Tableau MCP Mainline Convergence

## 背景

当前 Tableau MCP 链路已经经历多轮演进，系统中同时存在多套入口、路由、资产解析、Planner、Guardrail、Fallback 和 Renderer 逻辑：

- `mcp_proxy_main.py` 作为新 MCP Proxy 入口。
- `mcp_first_main.py` 保留早期 MCP Host 主链路与 QuerySpec fallback。
- `schema_inventory` 在部分 Tableau MCP 场景下仍可能抢答资产类问题。
- `agent.py`、`runner.py`、`mcp_proxy_main.py`、`mcp_first_main.py` 中都有路由或决策逻辑。
- Guardrail 分散在 `mcp_args_guardrail.py`、`mcp_host/runtime.py`、`mcp_first_main.py`。
- 简单聚合问题仍可能进入昂贵的 LLM Planner。

这导致后续维护者难以判断“应该走哪条链路”，也让性能、稳定性和安全边界难以治理。

## 目标

将 Tableau MCP Agent 链路收敛为一条清晰主干：

```text
mcp_proxy_main
  -> strategy classifier
      -> asset flow
      -> deterministic plan compiler
      -> llm planner
  -> unified guardrail
  -> mcp runtime
  -> response normalizer
  -> renderer
```

核心原则：

1. **一个入口**：`mcp_proxy_main.py` 是 Tableau MCP controlled chain 唯一入口。
2. **一个 Resolver**：所有 Tableau datasource lookup 统一经过 deterministic resolver。
3. **一个 Runtime**：统一复用 `MCPToolCatalog` 与 `MCPToolExecutor`。
4. **一个 Guardrail**：连接权限、datasource 归属、tool allowlist、字段、limit、timeout、结果规模统一过一道安检门。
5. **一个 Response Normalizer**：统一输出 `asset_candidates`、`asset_metadata`、`query_result`、`tool_unavailable` 等扁平契约。
6. **一个 Fast Path 策略**：确定性聚合编译器只作为统一入口内的 strategy，不允许成为旁路。
7. **一个 Cache 层**：tools catalog 与 datasource metadata 有统一 TTL cache。
8. **一个删除策略**：技术路线确认替换的模块必须删除或明确归档，不长期保留可运行旧路径。

## 非目标

- 不新增独立 MCP Host 平台。
- 不新增通用 MCP Server Registry。
- 不新增自定义 Action DSL。
- 不改变 Tableau MCP Gateway 对外工具协议。
- 不改变非 Tableau MCP 类型行为。
- 不在本 change 中扩展 datasource-level ACL，仍以 connection 级权限与 datasource 归属校验为 MVP 边界。
- 不为了兼容历史链路保留长期双写或双执行。

## 删除优先原则

本 change 明确采用“替换后删除”的路线，不采用长期 feature flag 并存：

- 新主干覆盖并通过验收后，旧实现不得继续作为生产可达路径存在。
- 旧代码如仍有参考价值，应迁入 `archive`、测试 fixture 或文档，不保留在主执行路径。
- 删除范围必须有测试保护；不允许为了降低短期风险把旧链路留作隐性 fallback。
- 每个保留的 legacy adapter 必须有退出条件、删除任务和验收时间点。

## 验收摘要

- Tableau MCP 问答只有一个 controlled chain 入口。
- 资产清单、资产介绍、简单聚合、复杂查询都通过统一主干分流。
- `schema_inventory` 不再抢答 Tableau MCP 可回答的问题。
- 简单聚合问题不进入 LLM Planner，直接由 deterministic plan compiler 生成 `query-datasource` args。
- 复杂问题仍可进入 LLM Planner，但必须通过统一 Guardrail 与 Runtime 执行。
- tools catalog 与 datasource metadata 有 TTL cache，并有 cache hit/miss telemetry。
- 所有 response 都符合现有 Agent 契约：`done.response_type` 与 `done.response_data` 平级，不在 `response_data` 内再包 `data`。
- 被替换的 legacy 生产路径已删除或不可达，并有测试证明。

