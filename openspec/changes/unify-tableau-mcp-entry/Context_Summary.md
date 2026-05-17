# Context Summary

## 1. Relevant Files

- `backend/services/tableau/models.py`：定义 `TableauConnection`，已包含 `mcp_direct_enabled` 与 `mcp_server_url` 字段。
- `backend/services/mcp/models.py`：定义 `McpServer`，需要新增 `tableau_connection_id` 等绑定字段。
- `backend/app/api/mcp_configs.py`：当前包含 `_sync_mcp_to_tableau()` 内联同步逻辑，需要重构并迁移出 API 层。
- `backend/app/api/tableau.py`：Tableau 连接管理的 API，创建和更新接口当前接受 `token_value`。
- `backend/services/tableau/mcp_binding_service.py`：新抽离的绑定服务，用于处理 Tableau 连接与 MCP 代理网关的绑定关系。
- `frontend/src/api/tableau.ts`：前端对应的数据连接 API 接口定义，包含 `agent_enabled` 等新增状态。
- `frontend/src/pages/tableau/connections/page.tsx`：前端数据连接管理页面，已初步增加了“启用 Agent 访问”表单项。
- `frontend/src/pages/admin/mcp-configs/page.tsx`：前端 MCP 配置管理页面，需要适配新的来源 Tableau 连接绑定展示与高级模式。
- `backend/services/data_agent/mcp_host/`：MCP Host 的运行时目录，包含 `planner.py`，决定了 Data Agent 的探索链路。

## 2. Current Behavior

- **入口割裂**：当前系统拥有 `数据连接 / 新建 Tableau 连接`（用于资产接入）和 `服务配置 / MCP 配置`（用于 Agent 工具配置）两个入口，这导致用户配置心智负担重，甚至会出现重复配置或配置不一致。
- **关联薄弱**：目前的机制是通过 `mcp_configs.py` 中的 `_sync_mcp_to_tableau()` 函数，基于名字（name）将 MCP 记录反向同步（桥接）到 Tableau 连接，并未建立强外键（FK）关联。
- **Agent 主链路**：根据前期的 `RETROSPECTIVE.md`，目前 Mulan 首页主要依赖强路由和 Guardrail（`mcp_args_guardrail.py`），对原生 MCP 的 `tools/list` 探索能力（如 `search-content` 等）利用不足。
- **Token 传输**：在创建或更新连接时，前后端交互的主字段为 `token_value`。

## 3. Existing Constraints

- **入口唯一性**：MVP 必须将 `数据连接 / Tableau` 作为用户唯一推荐的入口，不再要求普通用户填写复杂的 MCP HTTP Endpoint。
- **安全与凭证管理**：PAT Secret 必须以 `tableau_connections.token_encrypted` 为权威存储。Tableau 类型的 MCP 记录不得单独冗余存储一份明文 PAT。
- **向前兼容性**：不能直接删除历史的 `mcp_server_url`，同时 API 必须继续接收 `token_value`。修改字段语义必须十分谨慎。
- **边界与权限**：必须保留底层的 Data Agent Guardrail，不能无限制地将所有大模型流量引导至开放的探索循环（ReAct），以免造成严重的 TTFB 延迟恶化及不可控的查询。
- **分层规范**：遵循项目约束，`services` 层绝不能反向依赖 `app.api` 层。

## 4. Dependency/Call Chain

**重构前链路（基于反向桥接）：**
```text
用户操作：服务配置 / MCP 配置
→ POST /api/mcp-configs
→ backend/app/api/mcp_configs.py: create_mcp_server()
→ 写入 mcp_servers
→ 调用 _sync_mcp_to_tableau()
→ 调用 TableauDatabase.ensure_connection_from_mcp()
→ 依据 mcp_name 匹配，创建/更新 tableau_connections
```

**重构后目标链路（正向驱动与一致性绑定）：**
```text
用户操作：数据连接 / 新建 Tableau 连接 (勾选"启用 Agent 访问")
→ POST /api/tableau/connections
→ backend/app/api/tableau.py: create_connection()
→ 验证 Tableau REST
→ 同事务保存 tableau_connections
→ 调用 TableauMcpBindingService.upsert_for_connection()
→ 基于系统环境变量/配置 TABLEAU_MCP_GATEWAY_URL 创建或更新 mcp_servers(tableau_connection_id)
→ 返回包含 `mcp_binding` 状态的结果给前端
```

## 5. Potential Risks

- **历史数据冲突**：历史数据可能存在 `name` 相同但实际上指向不同站点的情况，在 Alembic 迁移和回填（Backfill）时必须处理好去重和冲突，不能使用激进的删除策略。
- **连接可用性解耦**：当共享的 MCP Gateway 配置错误或 Health Check 失败时，绝不能阻断基础的 Tableau 资产连接的保存。MCP 失败应该仅体现为 `binding_status='unhealthy'` 或 `disabled`。
- **Token 泄漏风险**：在去除冗余的 MCP `credentials.pat_value` 时，切记不可在接口日志或暴露给前端的响应体中泄漏 `token_encrypted`。
- **前端交互同步**：需确保在 MCP 配置页的列表中，如果属于 `tableau` 类型的 Server，用户无法修改 `server_url`（除非开启高级模式），并能直观看到它来自于哪个 `tableau_connections`。