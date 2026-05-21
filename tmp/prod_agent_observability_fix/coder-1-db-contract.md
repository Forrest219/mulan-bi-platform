# coder-1：数据库契约与 migration 任务说明

## 目标

修复 `bi_agent_runs.error_code varchar(16)` 无法写入 `ROUTER_CLARIFY_REQUIRED` 的数据库契约问题，确保 Agent run 在触发澄清 fallback 时可以正常落库，并进入 Agent 监控链路。

本任务只负责数据库契约与 migration，不修改 Agent stream 业务流程，不做硬编码补偿。

## 涉及文件

- `backend/alembic/versions/*`
- `backend/services/data_agent/models.py`
- 相关 migration/schema 测试文件
- 如项目维护数据库字段说明文档，需同步更新

## 实施步骤

1. 定位 `bi_agent_runs` 表定义和现有 Alembic migration。
2. 确认生产库当前 `error_code` 字段类型为 `varchar(16)`。
3. 新增 Alembic migration，将字段长度扩展到 `varchar(128)`。
4. 审查同表和相关表短字段：
   - `bi_agent_runs.status`
   - `bi_agent_runs.response_type`
   - `agent_conversation_messages.response_type`
   - `bi_agent_steps.step_type`
5. 只扩容存在生产风险或已被当前错误码体系覆盖的字段。
6. 同步 ORM schema 中的字段长度声明。
7. 不新增针对 `ROUTER_CLARIFY_REQUIRED` 的硬编码补偿逻辑。
8. 不修改历史 run 数据。
9. 不回滚或覆盖他人已有改动，只提交本任务相关 migration/schema/test 变更。

推荐 migration 方向：

```sql
ALTER TABLE bi_agent_runs
  ALTER COLUMN error_code TYPE varchar(128);
```

## 风险

- `varchar(16)` 扩展到 `varchar(128)` 通常是低风险 DDL，但生产执行前仍需确认数据库锁表行为。
- 如果下游报表、同步任务或索引表达式假设 `error_code` 最大 16，需要同步评估。
- 如果字段参与索引，需确认扩容后索引大小不会影响性能。
- 该任务只修复数据库写入契约，不负责补写已经失败未落库的 assistant message。
- 若生产已有失败请求，需要另行评估是否需要数据修复任务，不能在 migration 中混入补偿逻辑。

## 测试命令

```bash
cd backend && alembic upgrade head
cd backend && python3 -m py_compile services/data_agent/models.py
```

数据库验证：

```sql
SELECT character_maximum_length
FROM information_schema.columns
WHERE table_name = 'bi_agent_runs'
  AND column_name = 'error_code';
```

写入验证应通过应用测试完成，不使用伪造业务数据污染生产。

## 验收标准

- `bi_agent_runs.error_code` 字段长度已从 `varchar(16)` 扩展到 `varchar(128)`。
- `ROUTER_CLARIFY_REQUIRED` 可以完整写入 `bi_agent_runs.error_code`。
- migration 可在本地或测试环境成功执行。
- ORM 定义与数据库字段长度一致。
- 未修改 Agent stream 业务流程。
- 未引入 error code 截断或硬编码补偿逻辑。
- 未混入他人无关改动。

## 回滚策略

- 若 migration 尚未发布，删除或修改本任务新增 migration，并保持 ORM 定义与数据库一致。
- 若 migration 已发布，优先不要直接缩回 `varchar(16)`，因为可能已有超过 16 字符的错误码写入。
- 如必须回滚，先执行数据检查：

```sql
SELECT COUNT(*)
FROM bi_agent_runs
WHERE length(error_code) > 16;
```

- 只有确认不存在超过 16 字符的 `error_code`，或完成单独批准的数据处理方案后，才允许执行收窄字段的回滚 migration。
- 回滚仅覆盖本任务新增的数据库契约变更，不要求回滚他人改动。
