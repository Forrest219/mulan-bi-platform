# Task 清单

## Task 0：OpenSpec 门控

Owner：主 coder

交付：
- `openspec/changes/fix-agent-observability-fallback-persistence/proposal.md`
- `openspec/changes/fix-agent-observability-fallback-persistence/design.md`
- `openspec/changes/fix-agent-observability-fallback-persistence/tasks.md`

验收：
- 明确数据模型、Agent fallback path、测试和发布验证范围。
- 明确不补造业务事实、不改 Agent 监控事实源。

## Task 1：数据库契约与 migration

Owner：coder-1

目标：
- 修复 `bi_agent_runs.error_code varchar(16)` 与实际 error code 长度不一致。
- 用 Alembic migration 对齐生产 schema。

依赖：
- Task 0 完成并通过复核。

验收：
- migration 可升级。
- `ROUTER_CLARIFY_REQUIRED` 写入不再失败。
- 相关 schema 测试通过。

## Task 2：fallback 持久化链路加固

Owner：coder-2

目标：
- 确保 fallback SSE 回复与会话历史一致。
- telemetry 写入失败不阻断 assistant message 持久化。

依赖：
- Task 1 的字段扩容方案已确定。

验收：
- fallback assistant message 可刷新恢复。
- telemetry 失败有结构化日志。
- 不重复写 assistant message。

## Task 3：测试、发布验证与历史数据处置

Owner：coder-3

目标：
- 补足回归测试。
- 定义生产验证、日志检查、回滚和历史补偿策略。

依赖：
- Task 1、Task 2 的实现分支可运行。

验收：
- targeted tests 通过。
- 容器重建验证通过。
- 历史补偿默认不执行，必须有人工确认步骤。

## Task 4：集成复核

Owner：主 coder

目标：
- 合并各 coder 成果。
- 确认 OpenSpec、实现、测试、验证结果一致。

验收：
- 修改文件清单清晰。
- 验证命令和结果完整。
- 残余风险明确。
