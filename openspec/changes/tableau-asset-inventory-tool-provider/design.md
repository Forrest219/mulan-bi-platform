# Design: Tableau Asset Inventory Built-in Tool Provider

## Current Failure Chain

当前问题链路：

```text
question="你有哪些看板？"
-> Router Guardrail: advisory handoff
-> MCP Host / Tableau MCP Planner
-> Planner 可见工具缺少 dashboard/workbook/view asset inventory capability
-> Planner 认为需要 clarification
-> Planner 输出 needs_clarification=true 但缺少 clarification block
-> Runtime 报 "Planner 未能生成可执行计划"
```

这不是 Router 的单点问题，而是资产清单工具、权限边界和 Planner 合约处理三者共同缺口。

## Architecture Target

资产清单能力必须作为 Mulan built-in MCP Tool Provider 挂入工具目录，而不是写在 Proxy 私有分支中：

```text
agent.py / runner.py
-> mcp_proxy_main.py
-> MCP Host / Planner
-> MCPToolCatalog exposes:
     - Tableau MCP native tools
     - Mulan built-in asset inventory tools
-> Planner selects mulan-list-tableau-assets
-> MCPToolExecutor.execute()
-> BuiltInToolProvider.execute()
-> connection/user permission guardrail
-> scoped local catalog query
-> normalized asset_candidates response
```

`mcp_proxy_main.py` 保持 orchestration / transparent proxy 角色：

- 可以传递 context、advisory、tool catalog。
- 不直接写本地 `tableau_assets` 查询逻辑。
- 不生成资产清单业务响应。
- 不绕过 executor。

## Built-in Tool Schema

建议新增工具名：

```text
mulan-list-tableau-assets
```

工具职责：读取 Mulan 本地同步的 Tableau 资产目录，返回当前用户在当前连接下可见的资产候选。

输入 schema：

```json
{
  "connectionId": {
    "type": "integer",
    "required": true
  },
  "assetTypes": {
    "type": "array",
    "items": {
      "enum": ["dashboard", "workbook", "view", "datasource"]
    },
    "required": false
  },
  "query": {
    "type": "string",
    "required": false
  },
  "limit": {
    "type": "integer",
    "minimum": 1,
    "maximum": 100,
    "required": false
  }
}
```

输出 contract：

```json
{
  "response_type": "asset_candidates",
  "response_data": {
    "source": "tableau_asset_catalog",
    "connection_id": 4,
    "asset_type": "dashboard",
    "assets": [
      {
        "id": "local-or-tableau-id",
        "name": "资产名称",
        "asset_type": "dashboard",
        "workbook_name": "工作簿名",
        "project_name": "项目名",
        "tableau_url": "https://..."
      }
    ]
  }
}
```

约束：

- `asset_candidates` 是资产目录事实，不是业务问数结果。
- 不得返回 `response_type=query_result`。
- 不得生成 `fields/rows/table_display.columns`，除非真实 Tableau MCP query tool 返回了业务数据。

## Permission Boundary

本地 `tableau_assets` catalog 查询必须满足全部条件：

1. 当前请求必须有明确 `connection_id`。
2. 如果 `connection_id` 为空，返回 clarification 要求选择连接/站点。
3. 必须验证当前 `user_id` 对该 `connection_id` 有访问权限。
4. SQL/ORM 查询必须包含连接隔离条件：

```sql
WHERE connection_id = :connection_id
```

5. 查询必须排除已删除/不可见资产，例如：

```sql
AND is_deleted = false
```

6. 不允许任何未绑定连接权限的全局 asset list。
7. `limit` 必须有默认值和最大值，避免一次性枚举过多敏感目录。

如果连接不存在、未授权、已禁用或不健康：

- 未授权/不可见：返回权限错误或安全 clarification，不返回资产列表。
- 连接缺失：返回要求选择连接的 clarification。
- 连接服务不可用：返回结构化 `tool_unavailable`，不 fallback 到全局 catalog。

## Tool Catalog Integration

MCP Host / Planner 应看到两类工具：

1. Tableau MCP native tools
   - `list-datasources`
   - `get-datasource-metadata`
   - `query-datasource`
   - 其他真实 Tableau MCP Gateway 支持的工具

2. Mulan built-in tools
   - `mulan-list-tableau-assets`

Prompt 必须明确：

- Router Advisory 是全局路由 hint，不是事实。
- Compiler Advisory 是字段/工具编译 hint，不是事实。
- Asset inventory tools 只能回答资产目录问题。
- Business metric answers 必须使用 Tableau MCP query tools。
- 不得用 asset catalog 结果冒充业务问数成功。

## Unified Executor Funnel

所有工具调用必须进入统一 executor：

```text
MCPToolExecutor.execute(tool_name, args, context)
```

Executor 内部根据 tool 类型分派：

- Tableau MCP native tool -> Tableau MCP Gateway / client
- Mulan built-in tool -> BuiltInToolProvider

统一 trace 字段：

- `execution_source=llm_planner`
- `mcp_tool_name=mulan-list-tableau-assets`
- `tool_provider=mulan_builtin`
- `connection_id`
- `guardrail_decision`
- `permission_decision`
- `route_advisory`
- `compiler_advisory`

这保证资产清单能力不会绕过已有执行、审计和观测链路。

## Planner Clarification Contract

Planner 输出的结构化 contract 必须严格处理。

当 Pydantic/Schema validation 发现：

- `needs_clarification=true`
- 但缺少必需的 `clarification` block

Runtime 不得从模型 `reason` 拼装用户回复。正确流程：

```text
Planner raw output
-> ValidationError
-> retry once with explicit validation feedback:
     "The previous JSON was invalid. You set needs_clarification to true,
      but omitted the required clarification block. Return valid JSON."
-> if retry valid: continue
-> if retry invalid: return standard system clarification
```

标准系统 clarification：

```text
抱歉，我不太理解您的意图。您是想查询业务数据，还是想查找 Tableau 看板、视图或数据源？
```

监控要求：

- `planner_retry_attempted=true`
- `planner_retry_success=true|false`
- `planner_error_code=PLANNER_CONTRACT_FAILURE`
- `planner_validation_error`
- `planner_contract_failure_count`

模型 `reason` 可以进入内部 trace/log，但必须经过敏感信息与内部推理文本控制，不得直接作为前端答案。

## Response Type Boundary

资产目录响应：

- `asset_candidates`
- `asset_metadata`
- `asset_not_found`
- `tool_unavailable`
- `clarification`

业务问数响应：

- `query_result`
- 必须包含 `response_data.fields`
- 必须包含 `response_data.rows`
- 必须包含 `response_data.table_display.columns`
- `fields/rows` 必须来自真实 Tableau MCP query tool call

Renderer 只做展示归一化，不新增、不重算业务事实。

## Tests

必须覆盖：

- 有 connection 且 user 有权限时，`你有哪些看板？` 触发 `mulan-list-tableau-assets`。
- 无 connection 时返回 clarification，不查询 catalog。
- user 无 connection 权限时不返回 asset list。
- Catalog 查询包含 `connection_id` 约束。
- `mcp_proxy_main.py` 不出现本地 asset catalog 查询分支。
- Planner missing clarification block 会 retry 一次。
- Retry 仍失败时返回标准系统 clarification，并记录 `PLANNER_CONTRACT_FAILURE`。
- 模型 `reason` 不进入用户响应。
- 资产目录响应不会被渲染成 `query_result`。
