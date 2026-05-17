# Design

## Decision

MVP 采用内置共享 MCP Gateway：

> 用户只在 Tableau 连接入口填写 Tableau URL / Site / PAT。系统自动生成或绑定 MCP 工具配置，不向用户暴露 MCP HTTP Endpoint。

## ADR

### Context

当前系统同时存在 Tableau 连接和 MCP 配置两个入口。两者都可能录入 Tableau URL、Site 和 PAT，造成重复配置心智。现有代码中 `mcp_servers` 可桥接生成 `tableau_connections`，但桥接按名称去重，且不是强 FK 关系。

### Decision

- `tableau_connections` 是 Tableau 接入主实体。
- `mcp_servers` 是 Agent 工具绑定实体。
- Tableau 类型 MCP 通过 `tableau_connection_id` 关联主连接。
- 内置共享 MCP Gateway 的 HTTP endpoint 由后端配置生成，不由用户录入。
- MCP Gateway 运行时通过后端注入的 `X-Mulan-Tableau-Connection-Id` 等 HTTP headers 获取 Tableau 连接和凭证上下文。

### Consequences

- 用户入口合并，减少重复录入。
- DB 一致性从“名称桥接”升级为“显式 FK + transaction upsert”。
- MCP 仍保留为 Agent 工具层，但 Tableau 类型的创建体验变为绑定式。
- 需要迁移历史 `mcp_servers` 与 `tableau_connections` 的关系。

## Internal Model

```text
tableau_connections
  id
  server_url
  site
  token_name
  token_encrypted
  mcp_direct_enabled
  mcp_server_url

mcp_servers
  id
  type = tableau
  server_url = shared MCP Gateway endpoint
  tableau_connection_id -> tableau_connections.id
  is_active
  health_status
```

## Gateway Endpoint Strategy

推荐 MVP 使用统一 endpoint：

```text
TABLEAU_MCP_GATEWAY_URL=http://mcp-gateway:8080/mcp
```

每个 Tableau 连接不生成独立 HTTP 服务；`mcp_servers.server_url` 存统一 gateway URL，运行时通过 `tableau_connection_id` / `connection_id` 选择 Tableau 上下文。

Runtime headers:

```text
X-Mulan-Tableau-Connection-Id: <tableau_connections.id>
X-Mulan-Mcp-Server-Id: <mcp_servers.id>
X-Mulan-User-Id: <current_user.id>
X-Mulan-Trace-Id: <trace_id>
```

不使用 query param，也不把连接上下文塞入 MCP tool JSON-RPC params。

## Migration Strategy

MVP 迁移分两阶段：

1. 先新增 nullable `mcp_servers.tableau_connection_id`、绑定状态字段和普通索引，并做 best-effort 回填。
2. 对历史冲突只标记 `unbound` 和 `last_binding_error`，不自动删除、不阻塞 Alembic。
3. 等冲突清理完成后，后续迁移再添加 active Tableau MCP 绑定唯一约束。

## Failure Policy

- Tableau REST 连接测试失败：阻止保存或返回明确错误。
- MCP Gateway 缺失：允许保存 Tableau 连接，但 Agent 绑定为 `disabled`，提示管理员配置 gateway。
- MCP initialize / tools/list 失败：保存 Tableau 连接，MCP 绑定标记 `unhealthy`。
- 重复 URL + Site：返回已有连接或提示复用，禁止静默创建重复主连接。
