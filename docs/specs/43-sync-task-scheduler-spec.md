# Spec 43: Tableau 三层同步调度模型

> 版本：v1.0  
> 状态：待实现  
> 关联：Spec 33（任务管理）、Spec 34（连接管理）

---

## 1. 背景与问题

### 1.1 现状

当前同步调度仅有两层：

```
BiSyncSchedule（计划模板）→ BiTaskRun（执行日志）
```

执行由 Celery Beat 直接触发 `sync_by_schedule()`，没有中间的"待执行任务"层。

### 1.2 已知问题

| 问题 | 根因 |
|------|------|
| `next_sync_at` 显示过去时间 | `to_dict()` 用 `last_sync_at + timedelta(interval)` 推算，从不滚动 |
| 展示与执行完全脱钩 | `next_sync_at` 是纯数学计算值，调度器不读取它 |
| 无法提前看到"今日任务清单" | 任务只有执行时才存在，之前不可见 |
| 执行日志无法溯源到"哪个计划的哪次调度" | `BiTaskRun` 不关联具体的计划执行时间点 |

---

## 2. 设计目标

1. **三层结构**：Schedule → Task（预生成）→ Run Log，对应 Tableau Server 的 Schedule → Task → Job
2. **next_sync_at 从数据库读取**，消除数学推算
3. **每个调度任务有唯一 ID**，可溯源
4. **每日提前生成任务清单**，用户可在执行前查看今日计划

---

## 3. 数据模型

### 3.1 新增表 `bi_sync_tasks`

```sql
CREATE TABLE bi_sync_tasks (
    id             BIGSERIAL PRIMARY KEY,
    schedule_id    INTEGER REFERENCES bi_sync_schedules(id) ON DELETE SET NULL,
    connection_id  INTEGER NOT NULL REFERENCES tableau_connections(id) ON DELETE CASCADE,
    scheduled_at   TIMESTAMP NOT NULL,           -- 计划执行时间（UTC）
    status         VARCHAR(16) NOT NULL DEFAULT 'pending',
    trigger_type   VARCHAR(16) NOT NULL DEFAULT 'scheduled',  -- scheduled / manual
    task_run_id    BIGINT REFERENCES bi_task_runs(id) ON DELETE SET NULL,
    error_message  TEXT,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_sync_task UNIQUE (schedule_id, connection_id, scheduled_at)
);

CREATE INDEX ix_sync_tasks_connection ON bi_sync_tasks (connection_id, scheduled_at);
CREATE INDEX ix_sync_tasks_schedule   ON bi_sync_tasks (schedule_id, scheduled_at);
CREATE INDEX ix_sync_tasks_status     ON bi_sync_tasks (status, scheduled_at);
```

### 3.2 状态机

```
pending → running → completed
                 ↘ failed
         ↘ skipped    （并发锁已持有时跳过）
```

字段约束：
- `status` ∈ `{pending, running, completed, failed, skipped}`
- `trigger_type` ∈ `{scheduled, manual}`
- `task_run_id` 在 `running` 时写入，之后不变

### 3.3 与现有模型的关系

```
BiSyncSchedule (1) ──< BiSyncTask (N) >── TableauConnection
                            │
                            └──> BiTaskRun（执行日志）
```

`BiSyncSchedule` 与 `BiSyncTask` 通过 `schedule_id` 关联；手动触发时 `schedule_id = null`。

---

## 4. 服务层

### 4.1 新增：`plan_daily_sync_tasks()`（`tableau_tasks.py`）

**触发时间**：每日 `0 5 * * *`（00:05），在 `bi_task_schedules` 注册 Beat entry。

**执行逻辑**：
```
for each enabled BiSyncSchedule s:
    fire_times = croniter(s.cron_expr, now).get_next_N(times_in_next_24h)
    for each fire_time in fire_times:
        for each connection c bound to s (auto_sync_enabled=True, is_active=True):
            INSERT INTO bi_sync_tasks
                (schedule_id, connection_id, scheduled_at, status, trigger_type)
            VALUES (s.id, c.id, fire_time, 'pending', 'scheduled')
            ON CONFLICT (schedule_id, connection_id, scheduled_at) DO NOTHING
```

**幂等性**：`UNIQUE` 约束 + `ON CONFLICT DO NOTHING`，重复执行安全。

**返回**：`{created: N, skipped: M, schedule_count: K}`，写入 `BiTaskRun` 记录。

---

### 4.2 修改：`sync_by_schedule()`（`tableau_tasks.py`）

RedBeat 按 `BiSyncSchedule.cron_expr` 触发此任务。

**修改后逻辑**：
```
1. 查询 BiSyncTask：
   WHERE schedule_id = schedule_id
     AND status = 'pending'
     AND scheduled_at BETWEEN (now - 10min) AND (now + 10min)
   ORDER BY connection_id

2. 若无匹配行（服务重启/planner 未运行）：
   → 现场创建 BiSyncTask 行，status='pending'

3. 对每个 task：
   UPDATE bi_sync_tasks SET status='running', updated_at=now WHERE id=task.id
   dispatch sync_connection_task.delay(conn_id, sync_task_id=task.id, trigger_type='scheduled')
```

**并发保护**：Redis 锁已存在，保持不变。

---

### 4.3 修改：`sync_connection_task()`（`tableau_tasks.py`）

新增可选参数 `sync_task_id: int = None`。

**执行完成回调**（成功/失败均执行）：
```python
if sync_task_id:
    task = db.query(BiSyncTask).filter_by(id=sync_task_id).first()
    if task:
        task.status = 'completed' | 'failed'
        task.task_run_id = run_id
        task.error_message = ...
        task.updated_at = datetime.now()
        db.commit()
```

---

### 4.4 修改：`TableauConnection.to_dict()`（`services/tableau/models.py`）

**当前（删除）**：
```python
# 双分支数学推算（interval / croniter），结果可能是过去时间
```

**修改后**：
`to_dict()` 增加可选 `db: Session = None` 参数。

```python
if db and self.auto_sync_enabled:
    next_task = db.query(BiSyncTask).filter(
        BiSyncTask.connection_id == self.id,
        BiSyncTask.status == 'pending',
        BiSyncTask.scheduled_at >= datetime.now(),
    ).order_by(BiSyncTask.scheduled_at).first()

    next_sync_at = (
        next_task.scheduled_at.strftime("%Y-%m-%d %H:%M:%S")
        if next_task else "待规划"
    )
else:
    next_sync_at = None
```

调用方（`TableauDatabase.get_all_connections()`、`get_connection()` 等）将 `session` 传入 `to_dict(db=session)`。

---

## 5. API

### 5.1 GET `/system/tasks/sync-tasks`

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `schedule_id` | int | 按计划过滤 |
| `connection_id` | int | 按连接过滤 |
| `status` | str | `pending/running/completed/failed/skipped` |
| `date` | str | `YYYY-MM-DD`，过滤 `scheduled_at` 所在日期；默认今日 |
| `page` | int | 默认 1 |
| `page_size` | int | 默认 50 |

**响应**：
```json
{
  "items": [
    {
      "id": 101,
      "schedule_id": 2,
      "schedule_name": "每日两次同步",
      "connection_id": 1,
      "connection_name": "Prod Tableau",
      "scheduled_at": "2026-05-12T00:00:00Z",
      "status": "completed",
      "trigger_type": "scheduled",
      "task_run_id": 55,
      "error_message": null,
      "created_at": "2026-05-11T00:05:01Z",
      "updated_at": "2026-05-12T00:03:22Z"
    }
  ],
  "total": 8,
  "page": 1,
  "page_size": 50
}
```

**权限**：`analyst` 及以上可查看

### 5.2 GET `/system/tasks/sync-tasks/{task_id}`

**响应**：在 5.1 单项基础上追加：
```json
{
  ...,
  "run": {
    "id": 55,
    "status": "completed",
    "started_at": "2026-05-12T00:00:05Z",
    "finished_at": "2026-05-12T00:02:41Z",
    "duration_ms": 156000,
    "result_summary": { "total": 243, "deleted": 2 }
  }
}
```

**权限**：`analyst` 及以上

---

## 6. Beat 注册

在 `bi_task_schedules` 表中新增：

| schedule_key | task_name | schedule_expr | cron_expr |
|---|---|---|---|
| `plan-daily-sync-tasks` | `services.tasks.tableau_tasks.plan_daily_sync_tasks` | `cron(0 5 * * *)` | `0 5 * * *` |

同时在 Celery Beat config 中硬编码兜底（防 DB 为空时缺失）。

---

## 7. 数据清理

`cleanup_tasks.py` 中新增：定期删除 `scheduled_at < NOW() - 30 days` 的 `bi_sync_tasks` 记录（`completed`/`failed`/`skipped` 状态），`pending` 超期行标记为 `skipped`。

---

## 8. 兼容性与迁移

- `sync_interval_hours` 字段已标注 deprecated，本次不删除，后续单独清理
- `scheduled_sync_all()` 保留作兜底，不影响新系统
- 历史 `BiTaskRun` 数据不迁移，`task_run_id` 对旧记录为 null

---

## 9. 验收标准

| # | 场景 | 预期结果 |
|---|------|----------|
| V1 | `plan_daily_sync_tasks` 执行后 | `bi_sync_tasks` 出现今日计划行，status=pending |
| V2 | 同一 (schedule, connection, time) 重复运行 planner | 不产生重复行 |
| V3 | 到达 cron 时间，`sync_by_schedule` 触发 | 对应 task status 变为 running → completed/failed |
| V4 | 执行完成 | `BiSyncTask.task_run_id` 指向正确的 `BiTaskRun.id` |
| V5 | 查看 Tableau 连接卡片 | `next_sync_at` 显示未来时间，非过去 |
| V6 | 无 pending task 时查卡片 | 显示"待规划"，不报错 |
| V7 | `GET /system/tasks/sync-tasks?date=today` | 返回今日任务清单含正确字段 |
| V8 | `GET /system/tasks/sync-tasks/{id}` | 返回任务详情含关联 run 日志 |
| V9 | planner 未运行时 `sync_by_schedule` 触发 | 自动现场创建 task 行并执行 |
| V10 | `npm run type-check` | 零新增错误 |
