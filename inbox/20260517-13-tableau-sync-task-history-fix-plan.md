# Tableau 手动同步与系统任务历史关联修复计划

## 背景

用户在以下页面看到 Tableau 同步流水：

- `/assets/tableau-connections/4/sync-logs`
- 展示流水号：`20260517-0001`

但在以下页面未能直观看到对应记录：

- `/system/tasks`
- 顶层 `运行历史`

排查后确认，同步没有丢失：

- `tableau_sync_logs` 已写入同步日志，例如 `id=14`、`connection_id=4`、`trigger_type=manual`、`status=success`
- `bi_task_runs` 已写入 Celery 运行记录，例如 `id=3900`、`task_name=services.tasks.tableau_tasks.sync_connection_task`、`status=succeeded`

问题是 UI 和任务元信息存在割裂：

- Tableau 同步日志页展示的是 `tableau_sync_logs`
- `/system/tasks` 顶层 `运行历史` 实际展示的是 `bi_sync_tasks`，即同步计划任务清单
- 系统任务子页 `执行历史` 展示的是 `bi_task_runs`
- 手动同步 Celery 任务在 `bi_task_runs.trigger_type` 中被误标为 `beat`
- 系统任务执行历史没有清晰展示对应的 Tableau 同步日志 ID

结论：这是实现/体验 bug，不是同步任务丢失。

## 修复目标

1. 手动同步在系统任务执行历史中标记为 `manual`，而不是 `beat`。
2. 系统任务执行历史能展示并关联对应 Tableau 同步日志。
3. `/system/tasks` 顶层 Tab 文案避免误导用户。
4. 修复可通过后端、前端和集成查询验证。

## 后端改动

### 1. 手动同步派发 Celery 时写入 headers

文件：

- `backend/app/api/tableau.py`

当前逻辑大致为：

```python
task = sync_connection_task.delay(conn_id)
```

建议改为：

```python
task = sync_connection_task.apply_async(
    args=[conn_id],
    kwargs={"trigger_type": "manual"},
    headers={
        "trigger_type": "manual",
        "triggered_by": current_user["id"],
    },
)
```

预期效果：

- `sync_connection_task` 收到 `trigger_type="manual"`
- `tableau_sync_logs.trigger_type` 保持 `manual`
- Celery signals 能将 `bi_task_runs.trigger_type` 写为 `manual`
- `triggered_by` 可以落入 `bi_task_runs`

### 2. Celery signal 记录 triggered_by

文件：

- `backend/services/tasks/signals.py`

当前只读取：

```python
trigger_type = headers.get("trigger_type", "beat")
```

补充读取并转换：

```python
triggered_by_raw = headers.get("triggered_by")
try:
    triggered_by = int(triggered_by_raw) if triggered_by_raw is not None else None
except (TypeError, ValueError):
    triggered_by = None
```

创建 `BiTaskRun` 时加入：

```python
triggered_by=triggered_by,
```

### 3. 同步任务返回结果包含 connection_id 和 sync_log_id

文件：

- `backend/services/tasks/tableau_tasks.py`

成功路径确保返回：

```python
{
    "status": result["status"],
    "total": result["total"],
    "deleted": result.get("deleted", 0),
    "duration_sec": result.get("duration_sec", 0),
    "sync_log_id": log_id,
    "connection_id": conn_id,
}
```

失败路径尽量补充：

```python
{
    "status": "error",
    "message": msg,
    "sync_log_id": log_id,
    "connection_id": conn_id,
}
```

重点覆盖：

- Token 解密失败
- 连接失败达到最大重试
- 同步异常达到最大重试
- 普通 exception 返回

说明：`task_postrun` 已会把 dict 返回值写入 `bi_task_runs.result_summary`，不需要新增数据库字段或迁移。

## 前端改动

### 1. 系统任务执行历史展示关联同步日志

文件：

- `frontend/src/pages/admin/tasks/page.tsx`

在 `systemTab === 'runs'` 的表格中新增一列：

```text
关联日志
```

读取：

```ts
const syncLogId = run.result_summary?.sync_log_id;
const connectionId = run.result_summary?.connection_id;
```

展示规则：

- 有 `syncLogId` 且有 `connectionId`：展示链接，跳转到 `/assets/tableau-connections/${connectionId}/sync-logs`
- 只有 `syncLogId`：展示 `#<syncLogId>` 文本
- 都没有：展示 `-`

### 2. 修正文案，避免把同步计划清单误认为全部运行历史

文件：

- `frontend/src/pages/admin/tasks/page.tsx`

将顶层 Tab：

```ts
['history', '运行历史']
```

改为：

```ts
['history', '同步计划执行']
```

将系统任务子 Tab：

```ts
['runs', '执行历史']
```

改为：

```ts
['runs', '系统执行历史']
```

### 3. 可选增强：同步日志页展示真实日志 ID

文件：

- `frontend/src/pages/tableau/sync-logs/page.tsx`

当前 `20260517-0001` 是前端按日期和列表顺序生成的展示流水号，不是数据库主键。

建议展示为：

```text
20260517-0001 · #14
```

其中 `#14` 是 `tableau_sync_logs.id`，便于和系统执行历史中的 `sync_log_id` 对齐。

## 验收标准

### 后端验收

点击 Tableau 连接同步后，数据库满足：

```text
tableau_sync_logs:
- 新增记录
- connection_id = 目标连接 ID
- trigger_type = manual
- status 最终为 success 或 failed

bi_task_runs:
- 新增记录
- task_name = services.tasks.tableau_tasks.sync_connection_task
- trigger_type = manual
- triggered_by = 当前用户 id
- status = succeeded 或 failed
- result_summary.sync_log_id 存在
- result_summary.connection_id = 目标连接 ID
```

### 前端验收

1. `/assets/tableau-connections/4/sync-logs` 能看到新的同步流水。
2. `/system/tasks` 顶层 Tab 不再显示误导性文案 `运行历史`，而是 `同步计划执行`。
3. `/system/tasks` -> `系统任务` -> `系统执行历史` 能看到同一次 `Tableau 单连接同步`。
4. 该行触发方式显示为 `手动`。
5. 该行展示关联同步日志 `#<sync_log_id>`，有 `connection_id` 时可跳转到对应连接同步日志页。

## 建议验证命令

后端语法检查：

```bash
cd backend
python3 -m py_compile app/api/tableau.py services/tasks/signals.py services/tasks/tableau_tasks.py
```

前端检查：

```bash
cd frontend
npm run type-check
npm run lint
```

集成启动：

```bash
./start-dev.sh
```

触发同步后查库：

```bash
docker exec mulan-bi-postgres psql -U mulan -d mulan_bi -c "
select id, connection_id, trigger_type, status, started_at, finished_at
from tableau_sync_logs
order by id desc
limit 3;
"
```

```bash
docker exec mulan-bi-postgres psql -U mulan -d mulan_bi -c "
select id, task_name, trigger_type, status, triggered_by, result_summary
from bi_task_runs
where task_name = 'services.tasks.tableau_tasks.sync_connection_task'
order by id desc
limit 3;
"
```

## 交付给 Coder 的一句话任务

修复 Tableau 手动同步与系统任务历史的关联：手动同步 Celery 任务写入 `trigger_type=manual` 和 `triggered_by`，任务结果包含 `connection_id/sync_log_id`，系统任务执行历史展示关联同步日志，并将 `/system/tasks` 顶层 `运行历史` 改名为 `同步计划执行` 以避免误导。
