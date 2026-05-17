# RealWorld Risk Check

## Verdict

FAIL. 当前变更存在会误导运维判断的真实风险，且关键持久化路径覆盖不足。

## Blocking Risks

### 1. Tableau 同步失败会在系统执行历史中显示为成功

`sync_connection_task` 多个失败分支捕获异常后返回 `{"status": "error", ...}`，但没有让 Celery task 进入 FAILURE state。`task_postrun` 只根据 Celery state 映射 `bi_task_runs.status`，当 state 为 `SUCCESS` 时直接写为 `succeeded`。

结果：同步日志可能是 failed，但 `/system/tasks` 的系统执行历史会显示成功，同时 `result_summary.status = error` 被藏在 JSON 中。这会直接误导用户判断同步是否成功。

影响场景：

- Tableau token 解密失败
- Tableau 连接失败且达到最大重试
- 同步异常且达到最大重试
- 业务函数返回 error dict 但 Celery state 仍为 SUCCESS

### 2. 当前测试没有覆盖本次修复的关键落库效果

已新增测试可以证明 API 派发层会调用 `apply_async` 并传递 manual headers，这部分验证有效。但仍未覆盖：

- `on_task_prerun` 是否真的把 `triggered_by` 写入 `bi_task_runs`
- `on_task_postrun` 是否把 `sync_log_id` / `connection_id` 写入 `result_summary`
- 失败返回是否被系统执行历史正确标记为 failed
- 前端 `关联日志` 列是否在真实 API 响应下显示

### 3. 前端测试门控实际为空

`npm test -- --run` 失败原因是没有匹配 `src/**/*.{test,spec}.{ts,tsx}` 的测试文件。这是仓库当前测试门控现状，不是本次 UI 代码直接引入的失败。若本轮要求前端测试门控变绿，需要补一个最小渲染测试覆盖文案、列渲染和链接规则。

### 4. 交付范围与 active OpenSpec 不一致

当前 active SPEC 是 `unify-tableau-mcp-entry`，但本轮用户任务是同步历史关联修复。这里是流水线验收基准错误，不应作为 coder 本轮代码失败主因。

## Non-blocking Observations

- `SyncLogLink` 只接受 JSON number，当前 PostgreSQL JSONB 正常会返回 number；如果未来后端把 ID 序列化为字符串，前端会显示 `-`。
- 关联日志链接只跳到连接日志页，不定位具体 `sync_log_id`。这满足当前 fix plan 的最低要求，但排查效率仍有限。

## Verification Notes

后端定向测试需要在 `backend` 目录执行并设置 `PYTHONPATH=.`。在仓库根目录执行同类命令会因导入路径不同产生误导性失败。
