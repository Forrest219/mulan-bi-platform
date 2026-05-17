# Coder Taskbook: Unify Tableau MCP Entry

> 状态：可交付 Coder
> 关联 SPEC：`openspec/changes/unify-tableau-mcp-entry/SPEC.md`
> 关联任务：`openspec/changes/unify-tableau-mcp-entry/tasks.md`

## 1. 开发目标

本次开发将 Tableau 资产连接作为唯一推荐入口，并自动维护与 MCP 工具配置的绑定关系。

核心交付：

- 用户在 Tableau 数据连接页创建或更新连接时，可通过 `agent_enabled` 启用/停用 Agent 访问。
- 后端以 `tableau_connections` 为 Tableau PAT 的唯一权威存储。
- 系统自动维护 `mcp_servers.tableau_connection_id` 绑定，不再依赖 MCP 名称反向同步 Tableau 连接。
- 共享 MCP Gateway 地址来自 `TABLEAU_MCP_GATEWAY_URL`，普通用户不填写 MCP HTTP Endpoint。
- `TableauMCPClient` 调用 Gateway 时通过 `X-Mulan-*` headers 传运行时上下文。
- Gateway 未配置或 health check 失败不得阻断 Tableau 连接保存。

## 2. 不可破坏约束

Coder 必须遵守以下边界：

- 不修改 `token_value` API 字段名，不改成 `token_secret`。
- 不在 `mcp_servers.credentials` 中新增或保留新的 Tableau `pat_value`。
- 不向前端响应、日志、异常消息暴露 `token_encrypted` 或 PAT 明文。
- 不删除 `/api/mcp-configs`，不删除 MCP 配置页。
- 不删除历史业务表或历史 MCP 记录。
- 不修改 `backend/services/data_agent/` 下核心 `runner.py` 与 Guardrail 判断逻辑。
- 不修改 `useStreamingChat.ts` 的流式渲染缓冲逻辑。
- 不使用 query param 或 JSON-RPC tool params 传递 Tableau connection context。

## 2.1 Coder 执行裁决

以下裁决用于消除 SPEC 与 Taskbook 的字面歧义，Coder 后续实现以本节为准：

1. **历史 `credentials.pat_value` 清理口径**
   - 唯一匹配并成功 backfill 的历史 Tableau MCP 记录，必须只清理 `credentials.pat_value` 这个敏感键。
   - 不得删除整条 `mcp_servers` 记录，不得删除整个 `credentials` 对象，不得清理非敏感兼容字段。
   - 匹配失败或存在冲突的历史记录不得强行清理凭证，先标记 `binding_status='unbound'` 并写入 `last_binding_error`，避免破坏人工排障与回滚。

2. **Health check 与事务边界**
   - `tableau_connections` 保存与 `mcp_servers` upsert/disable 必须在同一数据库事务中完成并先提交。
   - 只有外部 Gateway health check 必须在该事务提交后执行，并在单独的小事务中更新 `binding_status` 与 `last_binding_error`。
   - 如果 `TABLEAU_MCP_GATEWAY_URL` 未配置，不需要执行外部 health check，可在主事务内直接记录 `disabled` 或等价失败状态。
   - API 响应可以等待 health check 完成后返回最终 `mcp_binding` 状态，但 health check 失败不得回滚已保存的 Tableau connection。

3. **测试文件路径**
   - Taskbook 中的 `tests/api/test_tableau_mcp_binding.py` 是建议路径，不是强制路径。
   - 如果项目现有 Tableau API 测试主要位于 `backend/tests/` 根目录，则使用 `backend/tests/test_tableau_mcp_binding.py` 可接受。
   - 验收以测试覆盖的行为断言为准，不以文件目录名为准。

4. **后端测试覆盖**
   - 17 条后端测试用例是必须覆盖的验收点，但不要求逐条使用完全相同的测试函数名。
   - 可以通过合并测试覆盖多个断言，但交付说明必须给出覆盖映射。
   - 当前缺口必须补齐或在交付说明中给出明确不可测原因：migration column/index introspection、唯一匹配 backfill、disable agent API、duplicate 409、MCP config 默认拒绝、非 Tableau MCP 回归、JSON-RPC params 不含 context。

5. **前端测试覆盖**
   - 7 条前端测试用例是必须覆盖的验收点，但不要求完全同名。
   - 当前缺口必须补齐或在交付说明中给出明确不可测原因：unhealthy binding 不显示连接保存失败、Tableau MCP `server_url` 默认只读或不可见、非 Tableau MCP 编辑不回归。

6. **本地运行时**
   - Coder 验证本轮交付时应只保留 Docker 后端/前端/Celery 作为主运行时。
   - 若发现额外本地 `uvicorn` 监听 `127.0.0.1:8000`，确认进程属于本项目后应停止，避免 API 请求、日志和端口来源混淆。

## 3. 开发包拆分

### Package A: 数据模型与迁移

覆盖任务：UTM-01、UTM-02、UTM-03

交付文件：

- `backend/alembic/versions/*_unify_tableau_mcp_entry.py`
- `backend/services/mcp/models.py`
- `backend/services/tableau/models.py`

开发要求：

- 为 `mcp_servers` 增加 nullable `tableau_connection_id` FK。
- 增加 `binding_source`，默认 `manual`，允许值：`auto_tableau_connection`、`manual`、`legacy_mcp_backfill`。
- 增加 `binding_status`，默认 `unbound`，允许值：`bound`、`disabled`、`unhealthy`、`unbound`。
- 增加 `last_binding_error`。
- 为 `tableau_connection_id` 添加普通索引。
- 首版迁移不得新增 active 唯一索引。
- backfill 只做 best-effort：
  - 可唯一匹配历史 Tableau MCP 与 Tableau connection 时，设置 FK，`binding_source='legacy_mcp_backfill'`，清理 `credentials.pat_value`。
  - 匹配失败或冲突时，不删除记录，标记 `binding_status='unbound'`，写入 `last_binding_error`。

完成标准：

- Alembic upgrade 能成功执行。
- Alembic downgrade 不破坏已有表结构之外的数据。
- 历史冲突数据不会被静默合并或删除。

### Package B: 绑定服务

覆盖任务：UTM-04、UTM-06

交付文件：

- `backend/services/tableau/mcp_binding_service.py`
- 必要时更新 `backend/services/common/settings.py`

开发要求：

- 新增 `TableauMcpBindingService`，集中处理 Tableau connection 与 MCP server 的绑定生命周期。
- `tableau_connections` 保存和 `mcp_servers` upsert/disable 必须在同一 DB 事务内。
- Gateway endpoint 只读取 `TABLEAU_MCP_GATEWAY_URL`。
- `enabled=False` 时停用绑定记录，建议设置 `is_active=False`、`binding_status='disabled'`。
- `enabled=True` 但 Gateway 未配置时，保留 Tableau connection，绑定状态返回 `disabled` 或等价失败状态，并写清 `last_binding_error`。
- health check 必须在事务提交后执行，设置短 timeout，捕获所有网络/协议异常。
- health check 失败只更新 `binding_status='unhealthy'` 与 `last_binding_error`，不得回滚 Tableau connection。
- upsert 后的 Tableau MCP server credentials 不得包含 `pat_value`。

完成标准：

- 创建、更新、停用路径都通过绑定服务完成，不在 API 层散落重复逻辑。
- 服务层不反向依赖 `app.api`。
- Gateway 故障时 API 仍能返回成功保存连接的响应。

### Package C: Tableau 连接 API

覆盖任务：UTM-05

交付文件：

- `backend/app/api/tableau.py`
- 相关 schema/serializer 文件

开发要求：

- `POST /api/tableau/connections` 与 `PUT /api/tableau/connections/{id}` 接收 `agent_enabled`。
- 继续接收现有 `token_value`。
- Tableau REST login 校验失败时，仍按现有语义阻断连接保存。
- Tableau connection 保存成功后返回 `mcp_binding`。
- Gateway 未配置或 health check 失败时，返回 200/201 + `mcp_binding` 失败状态，不得返回 4xx/5xx。
- 重复连接校验需覆盖同 `owner_id` 下 `server_url + site`，不得静默生成重复连接。

建议响应字段：

```json
{
  "id": 123,
  "name": "tableau-prod",
  "agent_enabled": true,
  "mcp_binding": {
    "mcp_server_id": 456,
    "binding_status": "bound",
    "binding_source": "auto_tableau_connection",
    "last_binding_error": null
  }
}
```

完成标准：

- 成功创建连接并启用 Agent 时，数据库存在绑定的 `mcp_servers` 记录。
- 禁用 Agent 后，对应 MCP server 不再作为 active 工具暴露。
- API 响应不泄露凭证。

### Package D: MCP 配置 API 兼容

覆盖任务：UTM-08

交付文件：

- `backend/app/api/mcp_configs.py`
- 相关 schema/serializer 文件

开发要求：

- 移除或废弃 `_sync_mcp_to_tableau()` 的反向同步路径。
- Tableau 类型 MCP 配置默认必须绑定已有 `tableau_connection_id`。
- 未传 `tableau_connection_id` 的 Tableau MCP 创建请求应拒绝，除非显式进入高级模式。
- 高级模式不得写入 Tableau PAT 明文。
- 列表/详情接口返回 Tableau MCP 与 Tableau connection 的关联信息，供前端展示“来源 Tableau 连接”。
- StarRocks 或其他非 Tableau MCP 类型行为不得回归。

完成标准：

- 新链路由 Tableau connection 正向驱动 MCP binding。
- 旧 MCP 配置入口仍可服务非 Tableau MCP。
- Tableau MCP 手工入口不会制造第二套 PAT 权威数据。

### Package E: Runtime Header 透传

覆盖任务：UTM-07

交付文件：

- `backend/services/tableau/mcp_client.py`
- 相关调用方或测试 fixture

开发要求：

- `TableauMCPClient` 调用共享 Gateway 时必须注入：
  - `X-Mulan-Tableau-Connection-Id`
  - `X-Mulan-Mcp-Server-Id`
  - `X-Mulan-User-Id`
  - `X-Mulan-Trace-Id`
- Header 值必须来自运行时上下文，不得写入 JSON-RPC params。
- 不使用 query param 传递上述 context。
- Header 缺失时应有明确错误或降级行为，避免静默调用错误租户。

完成标准：

- 单元测试能捕获实际 HTTP request headers。
- JSON-RPC body 中不包含上述 context 字段。

### Package F: 前端 Tableau 数据连接

覆盖任务：UTM-09

交付文件：

- `frontend/src/api/tableau.ts`
- `frontend/src/pages/tableau/connections/page.tsx`
- 必要时新增局部测试文件

开发要求：

- 新建/编辑 Tableau 连接表单提供“启用 Agent 访问”开关。
- 表单不暴露 MCP HTTP Endpoint 输入。
- 提交 payload 使用 `token_value` 和 `agent_enabled`。
- 保存成功后展示 `mcp_binding.binding_status`。
- Gateway 未配置或 health check 失败时，页面应提示 Agent 绑定异常，但不得把 Tableau 连接保存结果显示为失败。

完成标准：

- 成功保存连接和绑定异常两种场景都有明确 UI 状态。
- 类型定义与后端响应一致。
- 不引入 `token_secret` 字段。

### Package G: 前端 MCP 配置页

覆盖任务：UTM-10

交付文件：

- `frontend/src/pages/admin/mcp-configs/page.tsx`
- 必要时更新 API 类型文件

开发要求：

- Tableau 类型 MCP 列表展示“来源 Tableau 连接”。
- Tableau 类型的 `server_url` 默认只读，来自 `TABLEAU_MCP_GATEWAY_URL` 对应的系统绑定。
- 新建 Tableau MCP 时默认要求选择已有 Tableau connection。
- 高级模式入口需要清晰隔离，不作为普通用户默认流程。
- 非 Tableau MCP 配置交互不得回归。

完成标准：

- 用户能从 MCP 配置页识别哪些记录来自 Tableau connection 自动绑定。
- 普通流程无法手工录入 Tableau MCP endpoint 和 PAT。

## 4. 后端测试用例

### Migration tests

1. `test_migration_adds_nullable_binding_columns`
   - Given: 执行 Alembic upgrade。
   - Expect: `mcp_servers` 存在 `tableau_connection_id`、`binding_source`、`binding_status`、`last_binding_error`。
   - Expect: `tableau_connection_id` 为 nullable，并存在普通索引。
   - Expect: 不存在 active 唯一索引。

2. `test_backfill_binds_legacy_tableau_mcp_when_unique_match`
   - Given: 历史 `mcp_servers(type='tableau')` credentials 含 `tableau_server`、`site_name`、`pat_value`，且唯一匹配一条 Tableau connection。
   - Expect: 设置 `tableau_connection_id`。
   - Expect: `binding_source='legacy_mcp_backfill'`。
   - Expect: `credentials` 不再包含 `pat_value`。

3. `test_backfill_marks_unbound_on_conflict_without_deleting_records`
   - Given: 历史 MCP 可匹配多条 Tableau connection 或无法匹配。
   - Expect: `tableau_connection_id` 为空。
   - Expect: `binding_status='unbound'`。
   - Expect: `last_binding_error` 有可诊断原因。
   - Expect: 历史 MCP 记录仍存在。

### Binding service tests

4. `test_upsert_for_connection_enabled_creates_bound_mcp_server`
   - Mock: `TABLEAU_MCP_GATEWAY_URL` 存在，health check 成功。
   - Expect: 创建或更新一条 `mcp_servers`。
   - Expect: `tableau_connection_id` 指向 connection。
   - Expect: `binding_source='auto_tableau_connection'`。
   - Expect: `binding_status='bound'`。
   - Expect: `credentials` 不包含 `pat_value`。

5. `test_upsert_for_connection_disabled_deactivates_binding`
   - Given: 已存在 active Tableau MCP binding。
   - When: `enabled=False`。
   - Expect: `is_active=False`。
   - Expect: `binding_status='disabled'`。

6. `test_upsert_without_gateway_does_not_raise`
   - Mock: `TABLEAU_MCP_GATEWAY_URL` 缺失。
   - Expect: 不抛出导致连接回滚的异常。
   - Expect: 返回 binding 失败状态。
   - Expect: `last_binding_error` 说明 Gateway 未配置。

7. `test_health_check_failure_marks_unhealthy_after_connection_saved`
   - Mock: Gateway timeout 或返回非 2xx。
   - Expect: Tableau connection 已持久化。
   - Expect: MCP binding 标记 `unhealthy`。
   - Expect: 错误被捕获并写入 `last_binding_error`。

### Tableau API tests

8. `test_create_tableau_connection_with_agent_enabled`
   - Mock: Tableau REST login 成功，Gateway health check 成功。
   - POST: `/api/tableau/connections`，payload 包含 `token_value`、`agent_enabled=true`。
   - Expect: HTTP 200/201。
   - Expect: response 包含 `mcp_binding.binding_status='bound'`。
   - Expect: DB 中存在绑定的 `mcp_servers`。
   - Expect: response 和 MCP credentials 不包含 PAT 明文。

9. `test_create_connection_when_gateway_unreachable`
   - Mock: Tableau REST login 成功，Gateway timeout。
   - Expect: HTTP 200/201。
   - Expect: Tableau connection 已保存。
   - Expect: response `mcp_binding.binding_status='unhealthy'`。

10. `test_create_connection_when_tableau_login_fails_does_not_create_binding`
    - Mock: Tableau REST login 失败。
    - Expect: HTTP 400 或现有失败语义。
    - Expect: 不创建 Tableau connection。
    - Expect: 不创建 MCP binding。

11. `test_update_connection_disable_agent`
    - Given: 已有 Tableau connection 与 active MCP binding。
    - PUT: `agent_enabled=false`。
    - Expect: HTTP 200。
    - Expect: `mcp_servers.is_active=False`。
    - Expect: `binding_status='disabled'`。

12. `test_duplicate_owner_server_url_site_rejected`
    - Given: 同 owner 已有相同 `server_url + site` 的 Tableau connection。
    - POST: 再次创建相同连接。
    - Expect: HTTP 409 或现有重复错误语义。
    - Expect: 不新增 MCP binding。

### MCP config API tests

13. `test_create_tableau_mcp_requires_tableau_connection_id_by_default`
    - POST: `/api/mcp-configs`，`type='tableau'`，未传 `tableau_connection_id`。
    - Expect: HTTP 400/422。
    - Expect: 不创建记录。

14. `test_create_tableau_mcp_with_connection_id_does_not_store_pat_value`
    - POST: `/api/mcp-configs`，`type='tableau'`，传 `tableau_connection_id`。
    - Expect: 创建成功。
    - Expect: `credentials` 不包含 `pat_value`。

15. `test_non_tableau_mcp_configs_keep_existing_behavior`
    - POST/PUT: 非 Tableau 类型 MCP。
    - Expect: 现有字段与行为不回归。

### Runtime client tests

16. `test_tableau_mcp_client_sends_required_context_headers`
    - Mock: HTTP client post。
    - Expect headers 包含：
      - `X-Mulan-Tableau-Connection-Id`
      - `X-Mulan-Mcp-Server-Id`
      - `X-Mulan-User-Id`
      - `X-Mulan-Trace-Id`

17. `test_tableau_mcp_client_does_not_put_context_in_jsonrpc_params`
    - Mock: HTTP client post。
    - Expect: JSON-RPC body params 不包含 `tableau_connection_id`、`mcp_server_id`、`user_id`、`trace_id` 或对应 `X-Mulan-*` 字段。

## 5. 前端测试用例

1. `tableau connection form submits token_value_and_agent_enabled`
   - Render: Tableau connection create/edit form。
   - Action: 输入 PAT、打开“启用 Agent 访问”、提交。
   - Expect: API payload 包含 `token_value` 和 `agent_enabled=true`。
   - Expect: payload 不包含 `token_secret`。

2. `tableau connection form hides mcp_endpoint_for_normal_user`
   - Render: 普通模式 Tableau connection form。
   - Expect: 不出现 MCP HTTP Endpoint 输入框。

3. `tableau connection save shows_bound_status`
   - Mock: API 返回 `mcp_binding.binding_status='bound'`。
   - Expect: 页面显示 Agent 访问已启用或绑定成功状态。

4. `tableau connection save with_unhealthy_binding_is_not_failure`
   - Mock: API 返回 200/201，`mcp_binding.binding_status='unhealthy'`。
   - Expect: 页面提示 Agent 绑定异常。
   - Expect: 不显示 Tableau 连接保存失败。

5. `mcp configs page displays_source_tableau_connection`
   - Mock: MCP 列表包含 `type='tableau'`、`tableau_connection_id`、connection name。
   - Expect: 列表展示“来源 Tableau 连接”。

6. `mcp configs page makes_tableau_server_url_readonly_by_default`
   - Render: Tableau MCP 编辑弹窗或表单。
   - Expect: `server_url` 不可编辑或普通模式不可见。

7. `mcp configs page keeps_non_tableau_config_editable`
   - Render: 非 Tableau MCP 表单。
   - Expect: 原有 endpoint/credentials 编辑能力不回归。

## 6. 最小验证命令

后端：

```bash
cd backend
python3 -m py_compile app/api/tableau.py app/api/mcp_configs.py services/tableau/mcp_binding_service.py services/tableau/mcp_client.py services/mcp/models.py services/tableau/models.py
python3 -m pytest tests/api/test_tableau_mcp_binding.py tests/test_tableau_mcp_degradation.py tests/test_task_signals.py
```

前端：

```bash
cd frontend
npm run type-check
npm run lint
npm test -- --run
```

迁移：

```bash
cd backend
alembic upgrade head
```

如果本地测试库包含重要数据，执行迁移前必须先使用测试库或备份库，不得直接在生产样例库上试验 destructive downgrade。

## 7. Coder 提交前检查清单

- [ ] `SPEC.md` 的 5 个 Acceptance Criteria 全部满足。
- [ ] `tasks.md` 的 UTM-01 到 UTM-12 已完成或明确标注未完成原因。
- [ ] `token_value` 字段保持兼容。
- [ ] `mcp_servers.credentials` 不包含新的 Tableau PAT。
- [ ] Gateway 未配置或 health check 失败不阻断 Tableau connection 保存。
- [ ] Runtime context 只通过 `X-Mulan-*` headers 传递。
- [ ] 普通用户路径不再填写 Tableau MCP HTTP Endpoint。
- [ ] Guardrail 和 Data Agent runner 未被破坏性修改。
- [ ] 后端相关测试通过。
- [ ] 前端 type-check/lint/测试通过，若无测试文件匹配需在交付说明中注明。
