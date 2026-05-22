# Proposal: Tableau Asset Inventory Built-in Tool Provider

## Problem

Run `c864e1e2-ee15-474e-bb70-83b2bce62fe0` 暴露了一个与 Router Guardrail 不同的生产问题。

用户问题：

```text
你有哪些看板？
```

当前链路已经收到 `route_advisory` 并进入 Tableau MCP Planner，但 Planner 未能生成可执行计划：

- `planner_received_route_advisory=true`
- `tools_used={context_resolver,tableau_mcp_llm_planner}`
- 无真实 Tableau MCP tool call
- Planner 输出 `needs_clarification=true`，但缺少必需的 `clarification` block
- 前端最终看到「Tableau MCP Planner 未能生成可执行计划」

底层原因不是单句路由误判，而是能力边界缺口：

1. 当前 Planner 可见工具主要围绕 datasource metadata/query，不具备标准化的 Tableau asset inventory 工具。
2. 本地 `tableau_assets` catalog 虽然有资产数据，但直接在 `mcp_proxy_main.py` 查询会绕过权限边界，也破坏 Transparent MCP Proxy 定位。
3. Planner clarification 合约失败时，不能把模型内部 `reason` 拼成用户回复，否则会掩盖 Prompt/Schema 缺陷并泄露不专业的内部推理文本。

## Goals

1. 为 Tableau 看板、工作簿、视图、数据源等资产清单提供标准工具能力。
2. 将资产清单能力封装为 Mulan built-in MCP Tool Provider，而不是写入 `mcp_proxy_main.py` 私有分支。
3. 所有资产清单查询必须强制绑定 `connection_id`，并验证当前 `user_id` 对该连接可用。
4. 查询本地 `tableau_assets` catalog 时必须按连接隔离，不允许返回全局资产列表。
5. 内置工具与 Tableau MCP 原生工具一样进入 `MCPToolExecutor.execute()` 统一漏斗。
6. Planner 合约失败时采用一次 retry + 标准系统 clarification + Error 级监控，不暴露模型内部 `reason`。
7. 保持业务数据事实与资产目录事实的边界清晰：业务问数事实仍必须来自 Tableau MCP query tool call。

## Non-Goals

1. 不在 `mcp_proxy_main.py` 中新增本地资产 SQL 分支。
2. 不允许未绑定 connection/user 权限的全局 asset list。
3. 不把本地 asset catalog 作为业务数据事实源。
4. 不新增通用 MCP Server Registry。
5. 不新增自定义 action DSL。
6. 不恢复 QuerySpec 作为主链路 planning contract。
7. 不通过代码层拼接 `reason` 来伪造 Planner clarification。
8. 不把 Planner 内部 reason、chain-of-thought 或调试说明直接返回给前端用户。

## Desired Behavior

### Asset inventory request with connection

当用户请求资产清单，且当前会话有可用 `connection_id`：

```text
你有哪些看板？
```

Planner 应能选择内置工具，例如：

```json
{
  "tool_name": "mulan-list-tableau-assets",
  "args": {
    "connectionId": 4,
    "assetTypes": ["dashboard"],
    "limit": 50
  }
}
```

执行路径必须是：

```text
LLM Planner
-> MCPToolExecutor.execute()
-> Mulan built-in tool provider
-> connection/user permission check
-> tableau_assets query scoped by connection_id
-> asset_candidates response
```

### Missing connection

如果用户问资产清单但当前请求没有绑定连接：

```text
你有哪些看板？
```

系统必须返回 clarification，要求用户选择 Tableau 连接/站点。不得查询或返回全局资产列表。

### Planner contract failure

如果 Planner 输出 `needs_clarification=true` 但缺少 `clarification` block：

1. Runtime 对 Planner 进行一次带 ValidationError 反馈的重试。
2. 如果重试成功，按有效 Planner 输出继续。
3. 如果重试仍失败，返回标准系统 clarification：

```text
抱歉，我不太理解您的意图。您是想查询业务数据，还是想查找 Tableau 看板、视图或数据源？
```

同时记录 `PLANNER_CONTRACT_FAILURE`。不得把模型 `reason` 原文暴露给用户。

## Acceptance

- `你有哪些看板？` 在有可用连接时可通过内置工具返回资产候选，而不是 Planner 不可执行错误。
- 资产清单查询必须携带 `connection_id` 并通过当前用户连接权限校验。
- 无连接时返回 clarification，不返回全局资产。
- `mcp_proxy_main.py` 不承担本地 asset catalog SQL 逻辑。
- 内置工具调用进入 `MCPToolExecutor.execute()`，并有统一 trace。
- Planner clarification 合约失败会 retry 一次；仍失败时返回标准系统 clarification 和 `PLANNER_CONTRACT_FAILURE` 监控。
- 前端用户响应不包含 Planner 内部 `reason` 或调试文本。
- 业务问数成功仍必须有真实 Tableau MCP query tool call，不能由 asset catalog 冒充。
