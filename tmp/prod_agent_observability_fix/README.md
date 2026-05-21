# Agent Observability Fallback Persistence Fix

本目录是生产修复执行前的复核包，只包含计划、任务拆分与 coder 分工，不包含业务代码改动。

## 复盘摘要

- 触发会话：`dddc13f8-8348-404a-a0e5-83a0ffbb5fcb`
- 前端可见 run_id：`e7299b44-fe59-4182-8a11-8be5d17f48d5`
- 用户问题：`你有哪些看板？`
- 表现：前端曾收到 fallback 回复，刷新后只剩用户问题；Agent 监控页面查不到该 run。
- 根因：`bi_agent_runs.error_code` 为 `varchar(16)`，写入 `ROUTER_CLARIFY_REQUIRED` 时触发 `StringDataRightTruncation`。
- 连锁影响：fallback run 写入失败后，assistant message 持久化没有执行，但 SSE `done` 仍返回给前端。

## 文档索引

- `production_fix_plan.md`：生产级修复总体计划。
- `tasks.md`：可执行 task 清单与依赖顺序。
- `coder_assignments.md`：并行 coder 分工、写入范围与交付物。
- `coder-1-db-contract.md`：数据库契约与 migration 任务说明。
- `coder-2-persistence.md`：Agent stream/fallback 持久化链路加固任务说明。
- `coder-3-verification-rollout.md`：测试、发布验证与历史数据处置任务说明。

## 执行约束

- 当前阶段只允许复核文档，不执行代码修改。
- 正式开发前必须先通过 OpenSpec gate。
- 不通过截断 error code 解决问题。
- 不补造业务事实；历史数据补偿必须人工确认后执行。
- 所有代码改动必须按 task 拆分，避免和已有未提交改动混入。
