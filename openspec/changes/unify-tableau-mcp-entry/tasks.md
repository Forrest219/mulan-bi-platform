# Tasks

- [ ] UTM-01: 新增 Alembic schema 迁移，为 `mcp_servers` 增加 nullable `tableau_connection_id`、`binding_source`、`binding_status`、`last_binding_error` 和普通索引；本阶段不得加 active 唯一索引。
- [ ] UTM-02: 增加 best-effort backfill 逻辑：按同名 + URL + Site 匹配历史 Tableau MCP，冲突时标记 `unbound` 并写 `last_binding_error`，不得自动删除历史记录。
- [ ] UTM-03: 更新 `services/mcp/models.py` / `services/tableau/models.py` 字段映射与序列化输出。
- [ ] UTM-04: 抽取后端服务 `TableauMcpBindingService`，集中处理 Tableau 连接与 MCP 绑定的事务一致性。
- [ ] UTM-05: 更新 Tableau 连接创建/更新 API，支持 `agent_enabled`，保持现有 `token_value` 字段，并自动 upsert/disable MCP 绑定。
- [ ] UTM-06: 明确 MCP Gateway endpoint 解析：使用 `TABLEAU_MCP_GATEWAY_URL`，禁止用户在 Tableau 连接表单填写 endpoint。
- [ ] UTM-07: 更新 Tableau MCP runtime context：`TableauMCPClient` 必须向 Gateway 注入 `X-Mulan-Tableau-Connection-Id`、`X-Mulan-Mcp-Server-Id`、`X-Mulan-User-Id`、`X-Mulan-Trace-Id`。
- [ ] UTM-08: 更新 MCP 配置 API，Tableau 类型默认绑定已有 Tableau 连接；独立录入和自定义 endpoint 仅保留高级模式。
- [ ] UTM-09: 更新前端数据连接表单，增加“启用 Agent 访问”开关和绑定状态展示，不暴露 MCP HTTP Endpoint 输入。
- [ ] UTM-10: 更新 MCP 配置页，Tableau 类型显示“来源 Tableau 连接”并弱化手工凭证录入。
- [ ] UTM-11: 增加后端单元/集成测试：迁移回填、创建、更新、停用、重复绑定、Gateway 未配置、MCP health check 失败、runtime header。
- [ ] UTM-12: 增加前端测试：新建 Tableau 连接启用 Agent、请求字段为 `token_value`、MCP 页绑定关系展示。

## Dependencies

- UTM-01 必须先于 UTM-02/UTM-03/UTM-04。
- UTM-04 是 UTM-05/UTM-08 的共享依赖。
- UTM-06 必须先于 UTM-05/UTM-07。
- UTM-09/UTM-10 依赖 UTM-05/UTM-08 的响应字段。

## Gate

- Tableau 连接与 MCP 绑定必须同事务 upsert。
- PAT Secret 只能以 `tableau_connections.token_encrypted` 为权威存储；Tableau 类型 MCP 不得复制一份 PAT Secret。
- MCP health check 失败不得回滚 Tableau 连接保存，只能将 Agent 绑定标记为失败或未启用。
- Tableau 连接 API 主字段必须是现有 `token_value`，不得改为 `token_secret`。
- `POST/PUT /api/tableau/connections` 中 MCP Gateway 未配置或 health check 失败必须返回 200/201 + `mcp_binding` 失败状态，不得用 4xx/5xx 阻断连接保存。
- 调用共享 MCP Gateway 时必须通过 `X-Mulan-*` headers 传运行时上下文，不得使用 query param 或污染 MCP tool params。
