# Refactor Instructions

## Reviewer Decision

FAIL. 回退 fixer。不得进入 shipper。

## Required Fixes

1. 明确验收基准

- 本轮目标按用户最新明确指令，应以 `inbox/20260517-13-tableau-sync-task-history-fix-plan.md` 作为验收基准。
- `openspec/changes/unify-tableau-mcp-entry/SPEC.md` 属于另一工作包，不作为本轮 coder diff 的失败依据。
- 后续应由 pm/architect 补齐或对齐本轮修复对应的正式 OpenSpec 制品，避免阶段四再次混用验收基准。

2. 修正 `bi_task_runs.status` 与同步结果不一致的问题

- 位置：`backend/services/tasks/signals.py`
- 当 Celery state 是 `SUCCESS` 但 `retval` 是 dict 且 `retval["status"] == "error"` 时，`BiTaskRun.status` 必须标记为 `failed`，同时保留 `result_summary` 以便 UI 展示 `sync_log_id` / `connection_id`。
- 对 `skipped` 状态也需要明确产品语义，避免默认显示为成功。

修复示例方向：

```python
if isinstance(retval, dict):
    run.result_summary = retval
    if retval.get("status") == "error":
        run.status = "failed"
        run.error_message = retval.get("message")
```

3. 补测试

- 增加 `task_prerun` signal 单测：headers 中 `triggered_by` 为数字字符串/整数/非法值时的写库行为。
- 增加 `task_postrun` 单测：`retval.status == "error"` 时 `bi_task_runs.status == "failed"` 且 `result_summary` 不丢失。
- 增加 Tableau task 返回结果测试：成功、token 解密失败、连接失败达到最大重试、同步异常达到最大重试均包含 `sync_log_id` / `connection_id`。
- 增加前端渲染测试或提交明确测试门控例外说明。若补测试，覆盖 `关联日志` 列三种状态：有双 ID 显示链接、只有 sync_log_id 显示文本、无关联显示 `-`。

4. 重新验证

- `python3 -m py_compile backend/app/api/tableau.py backend/services/tasks/signals.py backend/services/tasks/tableau_tasks.py backend/tests/test_tableau_mcp_degradation.py`
- `cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_tableau_mcp_degradation.py tests/test_tasks_api.py -q --no-cov`
- `cd frontend && npm run type-check`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`
- 前端测试命令应变为可执行通过；若暂不补前端测试，fixer 必须明确说明这是仓库既有门控缺口而非本次 UI 代码引入。
