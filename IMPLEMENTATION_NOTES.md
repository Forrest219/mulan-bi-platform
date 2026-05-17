# IMPLEMENTATION_NOTES

## Scope

修复 Tableau 手动同步与系统任务历史的关联，按 `inbox/20260517-13-tableau-sync-task-history-fix-plan.md` 执行。

## Implemented

1. 手动同步 Celery 派发元信息
- `backend/app/api/tableau.py`
- 将单连接手动同步从 `delay(conn_id)` 改为 `apply_async(...)`。
- 写入 `kwargs={"trigger_type": "manual"}`，并通过 Celery headers 传递：
  - `trigger_type=manual`
  - `triggered_by=<current_user.id>`

2. 系统任务运行记录补充触发用户
- `backend/services/tasks/signals.py`
- `task_prerun` 从 headers 读取 `triggered_by`，做整数转换后写入 `BiTaskRun.triggered_by`。
- 非法或缺失值保持为 `None`，避免信号处理失败影响任务执行。
- `task_postrun` 在 `retval` 为 dict 时始终保留 `result_summary`。
- `retval.status == "error"` 时将 `BiTaskRun.status` 写为 `failed`，并写入 `error_message`，避免失败同步在系统执行历史中显示为成功。
- `retval.status == "skipped"` 映射为既有状态枚举 `cancelled`，不新增 `bi_task_runs.status` 状态值。

3. Tableau 同步任务结果补充关联字段
- `backend/services/tasks/tableau_tasks.py`
- 成功返回中补充 `connection_id`，保留 `sync_log_id`。
- Token 解密失败、连接失败达到最大重试、同步失败达到最大重试、普通异常失败返回中补充 `sync_log_id` 与 `connection_id`。
- 连接不存在和并发锁跳过路径至少返回 `connection_id`。

4. 系统任务执行历史展示关联同步日志
- `frontend/src/pages/admin/tasks/page.tsx`
- `/system/tasks` 顶层 Tab 文案从 `运行历史` 改为 `同步计划执行`。
- 系统任务子 Tab 从 `执行历史` 改为 `系统执行历史`。
- 系统执行历史表格新增 `关联日志` 列：
  - 有 `sync_log_id` 和 `connection_id` 时展示可点击 `#<sync_log_id>`，跳转到对应连接同步日志页。
  - 只有 `sync_log_id` 时展示纯文本。
  - 无关联信息时展示 `-`。

5. 同步日志页展示真实日志 ID
- `frontend/src/pages/tableau/sync-logs/page.tsx`
- 流水号旁新增 `#<log.id>`，便于与系统执行历史中的 `sync_log_id` 对齐。

6. 测试同步更新
- `backend/tests/test_tableau_mcp_degradation.py`
- 更新手动同步接口测试，从断言 `delay()` 改为断言 `apply_async()`，并覆盖 manual headers。
- `backend/tests/test_task_signals.py`
- 覆盖 `task_prerun` 写入 `triggered_by`、非法值降级为 `None`、`task_postrun` 将 error retval 映射为 failed 且保留 result_summary、skipped 映射为 cancelled。
- `backend/tests/test_tableau_sync_task_result.py`
- 覆盖 Tableau 同步任务成功、Token 解密失败、连接失败达到最大重试、同步异常达到最大重试时的返回字段。
- `frontend/src/pages/admin/tasks/SyncLogLink.test.tsx`
- 覆盖关联日志列双 ID 链接、仅 sync_log_id 文本、无关联展示 `-`。

## Validation

Executed:
- `python3 -m py_compile backend/app/api/tableau.py backend/services/tasks/signals.py backend/services/tasks/tableau_tasks.py backend/tests/test_tableau_mcp_degradation.py backend/tests/test_task_signals.py backend/tests/test_tableau_sync_task_result.py`: PASS
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_task_signals.py tests/test_tableau_sync_task_result.py tests/test_tableau_mcp_degradation.py::test_sync_endpoint_mcp_healthy_succeeds tests/test_tasks_api.py -q --no-cov`: PASS, 30 passed
- `cd frontend && npm run type-check`: PASS
- `cd frontend && npm run lint`: PASS, existing warnings only
- `cd frontend && npm test -- --run`: PASS, 1 file / 3 tests
- `cd frontend && npm run build`: PASS

Attempted:
- `cd backend && pytest tests/ -x -q`: failed because `pytest` is not on PATH in the default shell.
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/ -x -q`: ran 1612 tests successfully, then stopped at existing unrelated failure `tests/test_agent_conversations.py::TestConversationPersistence::test_get_user_conversations_returns_list`.

## Notes for Tester

- 手动触发 Tableau 连接同步后，检查 `bi_task_runs.trigger_type` 应为 `manual`，`triggered_by` 应为当前用户 ID。
- 对应 `bi_task_runs.result_summary` 应包含 `sync_log_id` 和 `connection_id`，可在 `/system/tasks` → `系统任务` → `系统执行历史` 的 `关联日志` 列查看。
- 失败同步的 `bi_task_runs.status` 应显示为 `failed`，不应再因 Celery SUCCESS state 被误标为 `succeeded`。
- 当前工作树中 `frontend/src/api/tableau.ts` 和 `frontend/src/pages/tableau/connections/page.tsx` 已有用户前置修改，本次未回滚。

---

## Scope — unify-tableau-mcp-entry

按 `openspec/changes/unify-tableau-mcp-entry/` 执行 UTM-01 至 UTM-12：以 `tableau_connections` 作为 Tableau 主配置，`mcp_servers` 作为自动绑定的 Agent 工具配置，MVP 使用 `TABLEAU_MCP_GATEWAY_URL` 作为共享 MCP Gateway。

## Implemented — unify-tableau-mcp-entry

1. Schema 与回填
- 新增迁移 `backend/alembic/versions/20260517_010000_unify_tableau_mcp_entry.py`。
- 为 `mcp_servers` 增加 `tableau_connection_id`、`binding_source`、`binding_status`、`last_binding_error` 与普通索引。
- 增加 best-effort legacy Tableau MCP backfill，冲突写 `binding_status='unbound'` 与 `last_binding_error`，不删除历史数据，不添加 active 唯一索引。

2. 后端绑定链路
- 更新 `services/mcp/models.py`、`services/tableau/models.py` 序列化字段。
- 新增 `services/tableau/mcp_binding_service.py`，集中处理 upsert / disable / get。
- `app/api/tableau.py` 创建/更新连接支持 `agent_enabled`，继续使用 `token_value`；Gateway 缺失返回 disabled，health check 失败返回 unhealthy，不阻断 200/201。
- `app/api/mcp_configs.py` 中 Tableau 类型默认绑定已有 Tableau 连接，高级模式才允许自定义 endpoint；新建 Tableau MCP 不再写入 `credentials.pat_value`。
- `services/tableau/mcp_client.py` 优先解析显式绑定 Gateway，并注入 `X-Mulan-Tableau-Connection-Id`、`X-Mulan-Mcp-Server-Id`、`X-Mulan-User-Id`、`X-Mulan-Trace-Id`。

3. 前端入口
- Tableau 连接表单增加“启用 Agent 访问”，展示 Agent 绑定状态，不暴露 MCP HTTP Endpoint。
- MCP 配置页 Tableau 类型显示来源 Tableau 连接，并弱化手工凭证录入。

4. 测试
- 新增 `backend/tests/test_tableau_mcp_binding.py` 覆盖 migration backfill 冲突、API 创建、Gateway 缺失、health check 失败、runtime header、PAT 不写入 MCP credentials。
- 新增 `frontend/src/pages/tableau/connections/page.test.tsx` 与 `frontend/src/pages/admin/mcp-configs/page.test.tsx` 覆盖前端提交字段、绑定状态展示与 MCP 来源连接展示。

## Validation — unify-tableau-mcp-entry

Executed:
- `cd backend && python3 -m py_compile app/api/tableau.py app/api/mcp_configs.py services/tableau/models.py services/mcp/models.py services/tableau/mcp_client.py`: PASS
- `cd backend && python3 -m py_compile app/api/tableau.py app/api/mcp_configs.py services/tableau/models.py services/mcp/models.py services/tableau/mcp_client.py services/tableau/mcp_binding_service.py services/common/settings.py services/query/query_service.py services/data_agent/mcp_proxy_main.py alembic/versions/20260517_010000_unify_tableau_mcp_entry.py tests/test_tableau_mcp_binding.py`: PASS
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_tableau_mcp_binding.py tests/services/tableau/test_mcp_client.py::TestContextvarsIsolation::test_connection_id_isolation -q --no-cov`: PASS, 6 passed
- `cd frontend && npm run type-check`: PASS
- `cd frontend && npm run lint`: PASS, existing warnings only
- `cd frontend && npm test -- --run`: PASS, 3 files / 6 tests

Attempted:
- `cd backend && pytest tests/ -x -q`: failed because `pytest` is not on PATH in the default shell.
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/ -x -q`: progressed to 1613 passed / 18 skipped, then stopped at existing unrelated failure `tests/test_agent_conversations.py::TestConversationPersistence::test_get_user_conversations_returns_list`.

## Notes for Tester — unify-tableau-mcp-entry

- 需要在环境中配置 `TABLEAU_MCP_GATEWAY_URL` 才会产生 `binding_status='bound'`；未配置时连接保存成功但绑定为 `disabled`。
- Gateway health check 异常时连接保存成功，绑定为 `unhealthy`。
- 历史迁移可能留下 `binding_status='unbound'` 的 Tableau MCP 记录，需要人工核对 URL + Site 冲突后再清理。

## Follow-up — unify-tableau-mcp-entry Taskbook confirmation

- 按确认口径调整 legacy backfill：唯一匹配成功的历史 Tableau MCP 记录会清理 `credentials.pat_value`，冲突/失败记录仍只标记 `unbound` 并保留历史数据。
- 新增数据迁移 `backend/alembic/versions/20260517_020000_cleanup_bound_tableau_mcp_pat_value.py`，用于清理已应用首版迁移的环境中成功 backfill 后仍残留的 `pat_value`。
- `TableauMcpBindingService` 改为两阶段 health check：主事务提交 Tableau connection + MCP binding 后，再调用 Gateway，并用单独事务更新 `binding_status` / `last_binding_error`。
- `get_tableau_mcp_gateway_url()` 只读取 `TABLEAU_MCP_GATEWAY_URL`，不再从 `TABLEAU_MCP_SERVER_URL` 回退。
- 补齐后端验收覆盖：migration column/index introspection、唯一匹配 backfill、disable agent API、duplicate 409、Tableau MCP 默认拒绝、非 Tableau MCP 回归、JSON-RPC params 不携带 runtime context。
- 补齐前端验收覆盖：unhealthy 绑定显示为连接已保存、Tableau 默认不暴露 MCP endpoint 输入、非 Tableau endpoint 仍可编辑。

Validation update:
- `cd backend && set -a && source .env && set +a && .venv/bin/python -m alembic upgrade head && .venv/bin/python -m alembic current`: PASS, `20260517_020000 (head)`.
- `cd backend && python3 -m py_compile app/api/tableau.py app/api/mcp_configs.py services/tableau/models.py services/mcp/models.py services/tableau/mcp_client.py`: PASS.
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_tableau_mcp_binding.py -q --no-cov`: PASS, 14 passed.
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/ -x -q`: same existing unrelated failure after 1614 passed / 18 skipped at `tests/test_agent_conversations.py::TestConversationPersistence::test_get_user_conversations_returns_list`.
- `cd frontend && npm run type-check`: PASS.
- `cd frontend && npm run lint`: PASS, 52 existing warnings.
- `cd frontend && npm test -- --run`: PASS, 3 files / 10 tests.
- Docker backend/Celery/frontend restarted; backend health 200, frontend 200, Celery ping OK, Docker Alembic current is `20260517_020000 (head)`.

## Follow-up — UAT blocker fixes from test report

- `docker-compose.yml` now mounts `./backend:/backend:ro` into `tableau-mcp-gateway`, and backend/celery/tableau-mcp-gateway were rebuilt and force-recreated.
- `tableau-mcp-gateway/requirements.txt` adds the minimal backend DB reader dependencies: `sqlalchemy`, `psycopg2-binary`, `cryptography`.
- `tableau-mcp-gateway/db.py` no longer imports backend ORM models. It uses `SessionLocal` plus SQLAlchemy text queries, so Gateway config loading does not pull in Celery/task package imports.
- `McpServer.to_dict()` scrubs Tableau `credentials.pat_value`, `credentials.token_value`, and `credentials.token_secret` before API responses.
- Removed the legacy `_sync_mcp_to_tableau` reverse bridge and its create/update/delete side effects from `app/api/mcp_configs.py`; legacy records are handled by migration/backfill only.

Validation update:
- `python3 -m py_compile backend/app/api/mcp_configs.py backend/services/mcp/models.py backend/tests/test_tableau_mcp_binding.py backend/tests/test_tableau_mcp_bridge.py tableau-mcp-gateway/db.py`: PASS.
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_tableau_mcp_binding.py tests/test_tableau_mcp_bridge.py -q --no-cov`: PASS, 21 passed.
- Runtime backend env check: `TABLEAU_MCP_GATEWAY_URL=http://tableau-mcp-gateway:3928/tableau-mcp`.
- Runtime Gateway check: `/backend/app` exists in container and `db.get_active_tableau_config()` returns a config.
- Runtime Gateway logs since rebuild show no `ModuleNotFoundError`, `Failed to load`, `ERROR`, or `Traceback`.
- Runtime MCP config scrub check through `/api/mcp-configs/`: PASS, temporary legacy Tableau MCP with `pat_value` / `token_value` / `token_secret` did not expose those keys.
- Backend `/health`: 200. Celery inspect ping: OK. Alembic current: `20260517_020000 (head)`. No extra local uvicorn process detected.
