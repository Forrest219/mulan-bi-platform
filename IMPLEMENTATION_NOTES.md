# IMPLEMENTATION_NOTES

## Scope — reconcile-tableau-mcp-fields

按 `openspec/changes/reconcile-tableau-mcp-fields/` 执行 RTMF-01 至 RTMF-12：区分 Tableau catalog fields 与 MCP queryable fields，资产页展示 Agent 可查询状态，Data Agent 在查询前阻止 catalog-only 字段进入 MCP 执行。

## Implemented — reconcile-tableau-mcp-fields

1. 字段能力模型与迁移
- 新增迁移 `backend/alembic/versions/20260517_030000_add_tableau_field_mcp_capability.py`。
- `tableau_datasource_fields` 增加 nullable MCP capability 字段：`mcp_queryable`、`mcp_field_name`、`mcp_field_caption`、`mcp_checked_at`、`mcp_last_error`。
- `mcp_queryable = null` 表示未校验，不使用 false 默认值。

2. Reconciliation 服务
- 新增 `backend/services/tableau/mcp_metadata_fields.py`，集中提供 MCP metadata 字段提取和字段名规范化。
- 新增 `backend/services/tableau/field_reconciliation.py`，实现 `TableauFieldReconciliationService`。
- 成功 reconciliation 只更新能力标记；MCP 失败只记录 `mcp_last_error`，不删除、不覆盖 catalog fields。

3. API 与同步
- `/api/tableau/assets/{asset_id}/fields` 和 `/api/tableau/datasources/{asset_id}/metadata` 保持对象响应外形，追加 `catalog_field_count`、`queryable_field_count`、`catalog_only_count`、`mcp_checked_at`、`mcp_status` 等字段。
- 字段行追加 `mcp_queryable` 和 `queryability_status`。
- Tableau datasource 字段同步和 metadata refresh 成功后 best-effort 触发 reconciliation。

4. Data Agent
- Datasource routing 保持 catalog fields 可用于匹配。
- MCP metadata 可用时 query planning 使用 MCP queryable fields；MCP metadata 不可用时，本地 fallback 只使用已标记 `mcp_queryable=true` 的字段，不再把完整 catalog fields 当成可执行字段。
- LLM 规划前增加 catalog-only preflight，用户明确提到 catalog-only 字段时返回解释，不进入 MCP 查询。
- MCP args guardrail 区分 `MCP_ARGS_CATALOG_ONLY_FIELD` 与 `MCP_ARGS_UNKNOWN_FIELD`，并给出保守替代字段候选。

5. 前端
- Tableau 资产字段页显示 `资产字段`、`Agent 可查询`、`仅资产目录`、`MCP 状态/异常`。
- 字段表新增 `Agent 状态` 列，展示 `Agent 可查询 / 仅资产目录 / 未校验 / MCP 异常`，不隐藏 catalog-only 字段。

6. 测试
- 新增 `backend/tests/test_tableau_field_reconciliation.py` 覆盖 422-like fixture：catalog 32、queryable 11、catalog-only 21。
- 新增 `backend/tests/services/data_agent/test_tableau_catalog_only_preflight.py` 覆盖 catalog-only preflight 和 queryable 放行。
- 更新 `backend/tests/services/data_agent/test_mcp_args_guardrail.py` 覆盖 catalog-only guardrail 错误码。
- 新增 `frontend/src/features/tableau-inspector/tabs/FieldsTab.test.tsx` 覆盖统计、状态标签和 MCP 异常提示。

## Validation — reconcile-tableau-mcp-fields

Executed:
- `cd backend && .venv/bin/python -m py_compile services/tableau/mcp_metadata_fields.py services/tableau/field_reconciliation.py services/tableau/models.py app/api/tableau.py services/tableau/sync_service.py services/data_agent/mcp_first_main.py services/data_agent/mcp_proxy_main.py services/data_agent/mcp_args_guardrail.py tests/test_tableau_field_reconciliation.py tests/services/data_agent/test_tableau_catalog_only_preflight.py`: PASS.
- `backend/.venv/bin/python -m py_compile $(git diff --name-only | grep '\.py$')`: PASS.
- `cd backend && .venv/bin/python -m pytest tests/test_tableau_field_reconciliation.py tests/services/data_agent/test_mcp_args_guardrail.py::test_rejects_catalog_only_field_with_specific_code_and_alternatives tests/services/data_agent/test_tableau_catalog_only_preflight.py tests/test_tableau.py::test_v2_metadata_cache_hit -q --no-cov`: PASS, 5 passed.
- `cd backend && .venv/bin/python -m alembic heads`: PASS, `20260517_030000 (head)`.
- `cd frontend && npm run type-check`: PASS.
- `cd frontend && npm run lint`: PASS, 52 existing warnings.
- `cd frontend && npm test -- --run`: PASS, 4 files / 11 tests.
- `cd frontend && npm test -- --run src/features/tableau-inspector/tabs/FieldsTab.test.tsx`: PASS.
- `cd frontend && npm run build`: PASS.

Attempted:
- `cd backend && .venv/bin/python -m pytest tests/services/data_agent/test_mcp_args_guardrail.py::test_rejects_catalog_only_field_with_specific_code_and_alternatives tests/services/data_agent/test_tableau_catalog_only_preflight.py -q`: behavior tests passed, but the subset run failed the repository-wide coverage threshold because only 3 tests were executed.
- `cd backend && .venv/bin/python -m pytest tests/ -x -q`: progressed to 1618 passed / 18 skipped, then stopped at existing unrelated failure `tests/test_agent_conversations.py::TestConversationPersistence::test_get_user_conversations_returns_list` (`MagicMock ... all()` is not a list).
- `cd backend && .venv/bin/python -m py_compile $(git diff --name-only | grep '\.py$')` from inside `backend/`: failed because `git diff --name-only` returns repo-root paths like `backend/app/api/tableau.py`; reran successfully from repo root.

Notes:
- Worktree also contains unrelated non-RTMF modifications in task/sync-history files and `frontend/auto-imports.d.ts`; this RTMF implementation did not modify those files.

## Fixer Update — reconcile-tableau-mcp-fields tester fail

Addressed `openspec/changes/reconcile-tableau-mcp-fields/TESTER_FAIL.md` findings:

1. Catalog-only preflight false positive
- `_catalog_queryable_context()` now treats fields as catalog-only only when `catalog_only_fields` is explicit/persisted, or when a non-empty queryable set is available for a catalog-minus-queryable comparison.
- Unknown/unreconciled/error states with empty queryable metadata are no longer converted into catalog-only.
- `mcp_args_guardrail` now applies the same rule: catalog fields are not considered catalog-only when the queryable set is unavailable.

2. MCP status display
- `FieldsTab` now renders cache status and MCP status as separate badges.
- MCP status maps `ok / partial / unknown / error` to explicit labels instead of falling back to cache status.

3. Handoff boundary
- RTMF handoff scope remains limited to Tableau field reconciliation, Data Agent field preflight/guardrail, and Tableau asset field UI.
- Existing task/sync-history/router worktree changes are not part of RTMF validation scope and should be validated under their own change/handoff.

Validation update:
- `backend/.venv/bin/python -m py_compile backend/services/data_agent/mcp_first_main.py backend/services/data_agent/mcp_args_guardrail.py backend/tests/services/data_agent/test_tableau_catalog_only_preflight.py backend/tests/services/data_agent/test_mcp_args_guardrail.py`: PASS.
- `cd backend && ./.venv/bin/python -m pytest tests/test_tableau_field_reconciliation.py tests/services/data_agent/test_tableau_catalog_only_preflight.py tests/services/data_agent/test_mcp_args_guardrail.py -q -o addopts=''`: PASS, 29 passed.
- `cd frontend && npm test -- --run src/features/tableau-inspector/tabs/FieldsTab.test.tsx`: PASS, 2 passed.
- `cd frontend && npm run type-check`: PASS.
- `cd frontend && npm run lint`: PASS, 52 existing warnings.
- `cd frontend && npm test -- --run`: PASS, 4 files / 12 tests.

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

## Scope — mcp-proxy-compiler-contraction

按 `openspec/changes/mcp-proxy-compiler-contraction/` 实施 deterministic compiler 收缩：compiler 只做受限 fast path 与 structured advisory，不做安全/权限/归属判断，不作为事实源。

## Implemented — mcp-proxy-compiler-contraction

1. Compiler 语义
- `deterministic_plan_compiler` 状态收敛为 `matched_executable`、`unsupported`、`ambiguous`。
- `ambiguous` 增加 `ambiguity_level=hard|soft`。
- 移除 compiler 自有安全拒绝路径；未引入 `safety_rejected`。

2. Simple multi-metric fast path
- 支持用户显式提到多个 queryable Tableau 指标时生成一个 `query-datasource` payload。
- 非计算 numeric measure 使用字段 `defaultAggregation` 或 `SUM`。
- 已存在 Tableau calculated/queryable derived field 直接选择，不在 Mulan 计算公式。
- 任一显式指标缺失或存在强歧义时不部分执行。

3. Advisory 与 planner handoff
- `unsupported` 与 soft ambiguity 生成并传递 `compiler_advisory`。
- planner prompt 明确 advisory 是 hint，不是事实源，不覆盖 datasource metadata、queryable fields、tool schema 或 guardrail。
- hard ambiguity 返回 clarification，停止，不调用 Tableau MCP，不交给 LLM Planner 猜。

4. 统一执行漏斗
- compiler fast path 与 LLM Planner payload 都通过 `_execute_mcp_host_tool()` 进入 `MCPToolExecutor.execute()`。
- `MCPToolExecutor.execute()` 内部调用 `TableauMcpGuardrailService`，trace 记录 `execution_source`、`compiler_status`、`compiler_reason`、`compiler_advisory`、`guardrail_decision` 和 tool。
- query result 响应补充 `response_type=query_result`、`execution_source`、`compiler_*`、`mcp_tool_name`，并保留 MCP 返回的 `fields` / `rows` / `table_display.columns`。

## Validation — mcp-proxy-compiler-contraction

Executed:
- `cd backend && python3 -m py_compile services/data_agent/mcp_proxy_main.py services/data_agent/tableau_mcp_plan_compiler.py services/data_agent/mcp_args_guardrail.py services/data_agent/mcp_host/runtime.py`: PASS.
- `cd backend && python3 -m py_compile services/data_agent/mcp_proxy_main.py services/data_agent/tableau_mcp_plan_compiler.py services/data_agent/mcp_args_guardrail.py services/data_agent/mcp_host/runtime.py services/data_agent/tableau_mcp_response.py services/data_agent/tableau_mcp_planner.py`: PASS.
- `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/services/data_agent/test_mcp_proxy_main.py tests/services/data_agent/test_tableau_mcp_plan_compiler.py -q -o addopts=''`: PASS, 40 passed.
- `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/services/data_agent/ -x -q -o addopts=''`: PASS, 513 passed, 28 skipped.
- `docker compose up -d --build backend`: PASS; refreshed `mulan-bi-backend` because the running container had no source mount and was still serving the old compiler.
- Container smoke test for run `089471b2-6446-4135-a198-a1ad00b360f3` question: PASS; path calls `tableau_mcp`, returns `response_type=query_result`, fields `["SUM(销售额)", "SUM(利润)", "利润率", "客户数", "客单价"]`, one row, and five aligned `table_display.columns`.

Attempted:
- `cd backend && pytest tests/services/data_agent/test_mcp_proxy_main.py tests/services/data_agent/test_tableau_mcp_plan_compiler.py -q`: failed because `pytest` is not on PATH in the default shell.
- `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/services/data_agent/test_mcp_proxy_main.py tests/services/data_agent/test_tableau_mcp_plan_compiler.py -q`: test cases all passed, then failed repository-wide coverage threshold because the targeted subset covered 9.70% vs configured fail-under 30%.

## Debug Update — run 089471b2-6446-4135-a198-a1ad00b360f3

Root cause:
- The recorded run used the Docker backend image, not the host workspace code. The container had `CompileStatus = Literal["matched", "clarification", "unsupported"]` and no source mount, so it still returned the old compiler clarification.
- After refreshing the container, the same question reached Tableau MCP, but MCP returned table data as `data: [{...}]`; the response normalizer only handled explicit `fields` / `rows`, so it produced empty `fields` / `rows`.

Fix:
- Rebuilt/restarted `mulan-bi-backend` with the current compiler changes.
- Updated `TableauMcpResponseNormalizer.query_result()` to normalize MCP `data: [{...}]` into MCP-backed `fields` / `rows` without recalculating facts.
- Preserved `table_display.columns` alignment with the normalized fields.

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
