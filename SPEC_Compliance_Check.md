# SPEC Compliance Check

## Verdict

FAIL. 当前实现不能进入 shipper，但失败主因不是 coder 偏离 `unify-tableau-mcp-entry`。

## Scope Checked

- Active SPEC: `openspec/changes/unify-tableau-mcp-entry/SPEC.md`
- Coder handoff: `IMPLEMENTATION_NOTES.md`
- Actual diff in current working tree
- Supplemental fix plan: `inbox/20260517-13-tableau-sync-task-history-fix-plan.md`

## Primary Finding

本轮用户明确要求按 `inbox/20260517-13-tableau-sync-task-history-fix-plan.md` 执行，而当前 active OpenSpec 是 `unify-tableau-mcp-entry`。两者不是同一工作包。

因此这里应判定为“流水线验收基准未对齐”，不应把 `unify-tableau-mcp-entry` 的未完成 AC 作为 coder 本轮交付失败主因。若要切回该 OpenSpec，应先回到 pm/architect 明确切换任务。

## Acceptance Criteria Coverage

| SPEC AC | Status | Evidence |
|---|---:|---|
| 管理员可在新建 Tableau 连接中勾选“启用 Agent 访问” | N/A | 不属于本轮 fix plan 范围。 |
| 保存时后端自动使用 `TABLEAU_MCP_GATEWAY_URL` 生成或绑定 Tableau MCP 配置 | N/A | 不属于本轮 fix plan 范围。 |
| 同一个 `server_url + site + owner_id` 不静默创建重复 Tableau 主连接 | N/A | 不属于本轮 fix plan 范围。 |
| Tableau REST 连接测试失败时阻止保存并返回可理解错误 | N/A | 不属于本轮 fix plan 范围。 |
| MCP Gateway 未配置或 health check 失败时连接仍保存，绑定状态 `disabled/unhealthy` | N/A | 不属于本轮 fix plan 范围。 |
| MCP 配置中 Tableau 类型默认选择已有 Tableau 连接，高级模式才手工 PAT | N/A | 不属于本轮 fix plan 范围。 |
| Data Agent 调用 Tableau MCP 时可通过 `connection_id` 找到绑定 endpoint | N/A | 不属于本轮 fix plan 范围。 |
| PAT Secret 只以 `tableau_connections.token_encrypted` 为权威存储，MCP 不再复制 PAT | N/A | 不属于本轮 fix plan 范围。 |

## Supplemental Fix Plan Coverage

按本轮用户明确要求，以 `inbox/20260517-13-tableau-sync-task-history-fix-plan.md` 作为验收基准，当前实现为部分通过，但仍有阻塞项：

| Fix Plan AC | Status | Evidence |
|---|---:|---|
| 手动同步 Celery 任务写入 `trigger_type=manual` 和 `triggered_by` headers | ✅ 已实现 | `backend/app/api/tableau.py` 使用 `apply_async(..., headers={...})`。 |
| `bi_task_runs.trigger_type` 应为 `manual` | ⚠️ 部分实现 | API 派发 headers 已覆盖，仍缺少 signal 写库级测试。 |
| `bi_task_runs.triggered_by` 应为当前用户 ID | ⚠️ 部分实现 | `task_prerun` 读取 headers，仍缺少端到端或 signal 单测。 |
| `result_summary.sync_log_id` 和 `connection_id` 存在 | ⚠️ 部分实现 | 成功/多条失败返回路径已补字段，但连接不存在、锁跳过路径无 `sync_log_id`；失败任务状态另有阻塞风险。 |
| `/system/tasks` 顶层 Tab 改名为 `同步计划执行` | ✅ 已实现 | `frontend/src/pages/admin/tasks/page.tsx` 已改文案。 |
| 系统执行历史展示关联同步日志 | ✅ 已实现 | 新增 `关联日志` 列和链接展示。 |
| 同步日志页显示真实日志 ID | ✅ 已实现 | `frontend/src/pages/tableau/sync-logs/page.tsx` 显示 `#<log.id>`。 |

## Validation Re-run

- `python3 -m py_compile backend/app/api/tableau.py backend/services/tasks/signals.py backend/services/tasks/tableau_tasks.py backend/tests/test_tableau_mcp_degradation.py`: PASS
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_tableau_mcp_degradation.py::test_sync_endpoint_mcp_healthy_succeeds tests/test_tasks_api.py -q --no-cov`: PASS, 21 passed
- `cd frontend && npm run type-check`: PASS
- `cd frontend && npm run lint`: PASS, 52 existing warnings
- `cd frontend && npm run build`: PASS
- `cd frontend && npm test -- --run`: FAIL, no Vitest test files matched
