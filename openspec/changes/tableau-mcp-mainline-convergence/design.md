# Design: Tableau MCP Mainline Convergence

## 1. 总体架构

目标主干：

```text
agent.py
  -> runner.py
    -> mcp_proxy_main.py
      -> TableauMcpStrategyClassifier
      -> DatasourceCandidateResolver
      -> Strategy
          -> AssetFlow
          -> DeterministicPlanCompiler
          -> LlmPlanner
      -> TableauMcpGuardrailService
      -> MCPToolCatalog / MCPToolExecutor
      -> TableauMcpResponseNormalizer
      -> AnswerRenderer
```

`mcp_proxy_main.py` 是唯一 production 入口。其他历史模块不得绕开该入口直接调用 Tableau MCP。

## 2. Strategy 分层

### 2.1 Asset Flow

覆盖：

- “有哪些数据源”
- “列出数据源”
- “介绍 X 数据源”
- “X 数据源有什么字段”
- “X 数据源能做什么分析”

规则：

- list 问题调用 `list-datasources`。
- metadata 问题先走 `DatasourceCandidateResolver`。
- 0 候选返回 `asset_not_found` 或 `asset_candidates` clarification，不允许返回全量列表冒充成功。
- 1 候选直接调用 `get-datasource-metadata`。
- N 候选返回 `asset_candidates`，要求用户澄清。

### 2.2 Deterministic Plan Compiler

覆盖结构明确的简单问数：

- `metric by dimension`
- `metric by time`
- `top N metric by dimension`
- `single metric with filters`
- `metric trend by date part`

Compiler 职责：

- 基于 datasource metadata / catalog cache 匹配字段。
- 输出标准 `query-datasource` args。
- 标注 `compile_confidence` 与 `compile_reason`。
- 对字段歧义、指标缺失、维度缺失返回 clarification，不调用 LLM Planner 猜测。

Compiler 不得：

- 针对 run_id、具体字段名、具体问法写个性化分支。
- 绕过 Guardrail。
- 直接调用 Tableau MCP。
- 写入独立 response contract。

### 2.3 LLM Planner

只处理：

- 多步推理。
- 用户问题结构不明确但可通过上下文推断。
- 需要选择多个工具或修复工具参数的问题。
- Compiler 置信度不足且不适合直接澄清的问题。

LLM Planner 输出仍必须进入统一 Guardrail 与 Runtime，不允许直接拼接 MCP tool JSON-RPC params。

## 3. DatasourceCandidateResolver

MVP 规则：

1. Normalize exact match。
2. Normalize contains match。
3. 候选上限 5。
4. 多候选必须 clarification。
5. 不做中文同义词或语义相似度推断。

权限边界：

- 校验 `connection_id` 对当前用户可用。
- 校验 `datasource_luid` 属于该 `connection_id`。
- list 只允许当前 `connection_id` 范围，不跨连接。

## 4. Unified Guardrail

统一收口以下校验：

- connection 是否属于当前用户或当前角色可访问。
- datasource 是否属于 connection。
- tool 是否在 Tableau MCP allowlist。
- tool args 是否符合 schema。
- query fields 是否存在于 metadata/queryable fields。
- limit、timeout、字段数量、结果行数是否在上限内。
- runtime context 必须通过 `X-Mulan-*` headers 传递，不得进入 query param 或 MCP tool JSON-RPC params。

建议统一服务：

```text
TableauMcpGuardrailService.validate(request) -> GuardrailDecision
```

所有 strategy 都必须调用该服务。

## 5. MCP Runtime

继续复用：

- `MCPToolCatalog`
- `MCPToolExecutor`

调整方向：

- Runtime 只负责 MCP catalog/tool schema 与 tool call。
- Runtime 不再承担业务权限判断。
- Runtime 保留基础资源保护，如最大结果字节数、最大行数、超时兜底。
- 业务级 Guardrail 由 `TableauMcpGuardrailService` 负责。

## 6. Response Normalizer

统一输出：

- `asset_candidates`
- `asset_metadata`
- `asset_not_found`
- `query_result`
- `tool_unavailable`
- `clarification`

硬性契约：

```json
{
  "response_type": "query_result",
  "response_data": {
    "source": "mcp",
    "fields": [],
    "rows": [],
    "table_display": {
      "columns": []
    }
  }
}
```

不得出现：

```json
{
  "response_data": {
    "data": {}
  }
}
```

## 7. TTL Cache

### 7.1 tools catalog cache

Key：

```text
tableau_mcp:tools:{connection_id}:{gateway_version}
```

建议 TTL：5 到 15 分钟。

失效条件：

- MCP Gateway health/version 变化。
- Tableau MCP server binding 更新。
- 管理员手动刷新。

### 7.2 datasource metadata cache

Key：

```text
tableau_mcp:metadata:{connection_id}:{datasource_luid}:{schema_version}
```

建议 TTL：10 到 60 分钟。

metadata 必须包含 freshness：

- `source = "mcp"`：实时 MCP 结果。
- `source = "catalog_cache"`：本地 catalog cache 降级。
- `metadata_freshness`：asset/field 最近同步时间；没有则为 null。

## 8. Telemetry

每次 run 至少记录：

- `route_ms`
- `resolver_ms`
- `catalog_ms`
- `metadata_ms`
- `compile_ms`
- `planner_ms`
- `guardrail_ms`
- `query_ms`
- `normalize_ms`
- `render_ms`
- `cache_hit`
- `cache_key`
- `strategy`

目标是能回答：

- 慢在 catalog、metadata、planner 还是 query。
- 本次是否命中 deterministic compiler。
- 本次是否使用 catalog cache 降级。
- 本次是否进入 LLM Planner。

## 9. 删除与归档策略

### 必须删除或转为不可达的生产路径

- Tableau MCP 场景下 `schema_inventory` 的抢答路径。
- `mcp_first_main.py` 中与新主干重复的 QuerySpec fallback 生产路径。
- 重复 datasource resolver。
- 重复 response normalizer。
- 分散的业务级 guardrail。
- 面向旧链路的 hidden fallback。

### 临时保留规则

如某段 legacy 代码必须临时保留，必须满足：

- 只能由测试或 archive 文档引用，生产不可达。
- 文件头注明 removal target。
- `tasks.md` 中有明确删除任务。
- 不得被新代码继续依赖。

## 10. 迁移策略

采用三阶段推进：

1. 主干收敛：建立唯一入口、统一 normalizer、禁用 MCP 场景 schema_inventory 抢答。
2. 安全收口：统一 resolver 与 guardrail，删除重复校验点。
3. 性能快路径：引入 TTL cache 与 deterministic plan compiler，复杂问题保留 LLM Planner。

每阶段完成后必须删除对应旧路径，不允许长期双轨运行。

