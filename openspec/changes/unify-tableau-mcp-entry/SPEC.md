# SPEC: Unify Tableau MCP Entry

> 版本：v0.1 | 状态：可交付 Coder | 关联提案：openspec/changes/unify-tableau-mcp-entry

## 1. Overview

**核心目标**：统一 Tableau 接入入口，大幅降低用户心智负担。将 `数据连接 / 新建 Tableau 连接` 提升为全系统唯一的标准入口。在后端实现主数据连接记录与 Agent 工具配置（MCP 服务器配置）的实体级一致性绑定。

**技术路线**：
- 以 `tableau_connections` 为唯一的权威凭证配置源。
- 采用内建的共享 MCP Gateway（通过环境变量 `TABLEAU_MCP_GATEWAY_URL` 配置），废弃普通用户手工填写 `MCP HTTP Endpoint` 的流程。
- 在 `mcp_servers` 表中引入强外键 `tableau_connection_id`，代理执行期间通过特定的 HTTP Header 将调用上下文（Connection ID、Mcp Server ID、用户 ID 等）传递至网关，实现透明代理。

**治理底线与 Data Agent 能力演示**：
尽管目前业务呼声倾向于在 Data Agent 链路中开放更多的原生 MCP Tool（如 `search-content` 等）以展现“自主探索”能力，但架构上绝不允许绕过现有基于业务的 `mcp_args_guardrail`。因此，本 SPEC 主要负责基础设施的统一，关于 MCP Host 主链路的切换将作为下阶段产品规划的一部分。

## 2. Non-Goals

- 不删除 `/api/mcp-configs` 和前端的“MCP 配置”页面（因要支持 StarRocks 或未来的外部独立 MCP 源）。
- 不在当前阶段废弃所有 Data Agent 的强路由和意图识别器（Intent Classifier）。
- 不修改原有的通过 `token_value` 建立连接的外部 API 结构（防止破坏正在使用这些接口的前端或其他集成）。
- MVP 不支持为每一个连接启动独立的本地 MCP Server 进程，必须复用统一的网关 URL。

## 3. Acceptance Criteria

1. **统一建站流程**：用户在 Tableau 数据连接页新建/更新连接，勾选“启用 Agent 访问”时，系统会在同一事务内自动 `upsert` 一条 `mcp_servers` 记录。
2. **唯一性及回滚防护**：同 `owner_id` 的 `server_url + site` 不会静默创建出重复的连接；若连接失败（400/409）不能生成无效连接；若 MCP Gateway 的 Health Check 失败，Tableau 连接**仍然能够保存**，但该 MCP Binding 状态会被标记为 `unhealthy`。
3. **消除冗余加密数据**：新的或回填的 `mcp_servers` 记录中，`credentials` 不应包含 `pat_value`，凭证统一通过 Gateway 取 `tableau_connections.token_encrypted` 获取。
4. **前端分离交互**：在“服务配置 / MCP 配置”页面，若列表类型为 `tableau`，只读展示其绑定的 Tableau 连接名；新增记录如果选择 Tableau 类型，必须强制选择一个关联的 `tableau_connection_id`（高级模式除外）。
5. **Gateway 请求头**：Data Agent 发起向 MCP 的查询时（`TableauMCPClient`），在 HTTP 请求头中必然且正确地传递 `X-Mulan-Tableau-Connection-Id` 等标识。

## 4. Change Budget

**可修改范围：**
- `backend/alembic/versions/*`：必须提供两阶段迁移脚本。
- `backend/services/tableau/models.py` / `backend/services/mcp/models.py`：变更数据模型与关联字段。
- `backend/services/tableau/mcp_binding_service.py`：负责处理关联生命周期。
- `backend/app/api/tableau.py` 与 `backend/app/api/mcp_configs.py`：修改视图层的持久化流程与兼容逻辑。
- `frontend/src/api/tableau.ts` 及前后端交互的模型定义。
- `frontend/src/pages/admin/mcp-configs/page.tsx`。
- `frontend/src/pages/tableau/connections/page.tsx`：完善现有的 `agent_enabled` 表单控件。
- 各个受影响模块的对应的单元测试文件。

**严禁修改的范围：**
- `backend/services/data_agent/` 目录下的核心 `runner.py` 与 Guardrail 判断逻辑（不能破坏当前的隔离与控制）。
- 前端核心流式输出组件 `useStreamingChat.ts`，不要动它的渲染缓冲区逻辑。
- 不得清理或删除历史存在业务记录的数据库表。

## 5. Design

### 5.1 数据模型变更 (Alembic)

为 `mcp_servers` 新增以下列：
- `tableau_connection_id` (Integer, Nullable, FK to `tableau_connections.id`)
- `binding_source` (VARCHAR(32), Default `'manual'`) - 允许值包括 `'auto_tableau_connection'`, `'manual'`, `'legacy_mcp_backfill'`
- `binding_status` (VARCHAR(32), Default `'unbound'`) - 可能值为 `bound`, `disabled`, `unhealthy`, `unbound`
- `last_binding_error` (TEXT, Nullable) - Gateway 异常日志

**迁移策略（两阶段落地）**：
1. **Schema Migration**：执行上述 DDL 新增列和外键。添加针对 `tableau_connection_id` 的普通索引。
2. **Best-effort Backfill**：编写 Python 脚本或 Alembic `data_upgrade`，遍历所有 `type='tableau'` 的 `mcp_servers`：
   - 提取 `credentials` 内的 `tableau_server` 与 `site_name`。
   - 在 `tableau_connections` 寻找匹配的 `server_url` 和 `site`。
   - 匹配成功：设置 FK，修改 `binding_source='legacy_mcp_backfill'`，并清洗掉 `credentials` 内的 `pat_value`。
   - 匹配冲突/失败：保留原有凭证，将状态标为 `unbound`，并在 `last_binding_error` 写入具体失败原因。
3. **后续约束 (Phase 2)**：首版迁移只做 nullable FK、普通索引、best-effort backfill 和冲突标记；待冲突清理完成后，另起变更再考虑 active 唯一约束或更强约束。

### 5.2 后端服务接口 (`TableauMcpBindingService`)

该服务必须在同一个事务中与 `tableau_connections` 被调用：
```python
# backend/services/tableau/mcp_binding_service.py 补充设计
class TableauMcpBindingService:
    def upsert_for_connection(self, connection, enabled: bool, owner_id: int, health_check: bool = True) -> McpBindingResult:
        # 1. 验证 TABLEAU_MCP_GATEWAY_URL 配置
        # 2. 如果不存在，报错并设置状态为 disabled
        # 3. 如果 enabled 为 False，停用记录。
        # 4. 如果 enabled 为 True，依据网关和 connection 信息，upsert mcp_servers。注意：连接与 mcp_servers 的 upsert 必须在同一数据库事务内。
        # 5. 清理 credentials 的 pat_value 避免泄露。
        # 6. 事务后置执行 external health_check (发送模拟 RPC 至网关)。必须设置短 timeout 并捕获异常，绝不允许因网络或 check 失败而引发异常抛出（导致回滚连接记录），仅更新 binding_status 即可。
        pass
```

### 5.3 `POST /api/tableau/connections` 流程改造

在 `backend/app/api/tableau.py` 中，`create_connection` 和 `update_connection` 的逻辑顺序：
1. 校验重名与 URL 重复。
2. 进行 Tableau Server 自身的 REST Login 检查。
3. `conn = TableauConnectionModel(...)` -> `db.add(conn)` -> `db.flush()` 获取自增的 ID。
4. 调用 `TableauMcpBindingService(db).upsert_for_connection(...)`。
5. 返回的结果 Payload 必须按照 Schema 将绑定状态通过 `mcp_binding` 返回前端。

### 5.4 剥离 MCP API 的冗余关联

- 移除 `app/api/mcp_configs.py` 中的 `_sync_mcp_to_tableau`。
- 如果用户通过 `/api/mcp-configs` 进行新建操作且选择了 Tableau，必须验证 `tableau_connection_id` 是否被传入，否则拒绝创建（除非该用户通过特殊标记指定了强行高级模式）。
- 禁止通过 `/api/mcp-configs` 重新提交明文的 PAT (Tableau Token Value)。

### 5.5 MCP 运行时的 Header 透传

确保 `TableauMCPClient` (负责向实际的 MCP Gateway 发送 JSON RPC 的调用客户端)，将以下变量加入 Header：
- `X-Mulan-Tableau-Connection-Id`: `str(connection_id)`
- `X-Mulan-Mcp-Server-Id`: `str(mcp_server_id)`
- `X-Mulan-User-Id`: `str(user_id)`
- `X-Mulan-Trace-Id`: `trace_id`

## 6. Mocks & Fixtures

此重构涉及核心表关联变动和外部网络请求，必须严格 Mock 网关依赖以保证流水线及测试的稳定性。

### 并行场景的 Fixtures：

**Python 侧 (backend/tests/api/test_tableau_mcp_binding.py)**

必须包括：
1. 模拟 `TABLEAU_MCP_GATEWAY_URL` 的存在与否：
   ```python
   # 使用 monkeypatch
   monkeypatch.setenv("TABLEAU_MCP_GATEWAY_URL", "http://fake-mcp-gateway:9000/mcp")
   ```
2. Mock Tableau Server REST Login (`_test_connection_rest`):
   ```python
   def mock_test_connection_rest(*args, **kwargs):
       return {"success": True, "message": "OK"}
   ```
3. Mock MCP Gateway Health Check：
   ```python
   # 拦截 requests.post 对网关的初始化协议调用
   class MockGatewayResponse:
       status_code = 200
       def json(self): return {"jsonrpc": "2.0", "result": {"protocolVersion": "2024-11-05"}}
   ```

**期望的测试覆盖验收点 (Acceptance Assertions)：**
- `test_create_tableau_connection_with_agent_enabled`: 断言返回 200/201，断言 DB 中生成了相关的 `mcp_servers` 记录，并且 `credentials` 字典不包含 `pat_value`。
- `test_create_connection_when_gateway_unreachable`: 当网关健康检查超时，连接本身应该返回 200/201，但返回结构的 `mcp_binding.binding_status` 应该断言为 `"unhealthy"`。
- `test_update_connection_disable_agent`: 更新接口发送 `agent_enabled: false` 后，对应的 `mcp_servers.is_active` 被修改为 False。