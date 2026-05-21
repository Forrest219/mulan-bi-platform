# 生产修复计划：Agent 监控不可见与 fallback 回复丢失

## 目标

修复 fallback/error 场景下的观测记录与会话历史不一致问题：

1. `bi_agent_runs` 能记录标准 fallback run，Agent 监控页面可见。
2. 前端通过 SSE 收到的 assistant 回复必须能在刷新后从会话历史恢复。
3. telemetry 写入失败不得导致用户可见 assistant message 丢失。
4. 错误码、状态、响应类型的数据模型长度与实际系统常量一致。

## 非目标

- 不改变 Agent 监控页面的数据源，仍以 `bi_agent_runs` 为事实源。
- 不补造 Tableau MCP 或业务查询结果。
- 不把失败 run 从消息表反推为成功 run。
- 不引入新的 Agent action DSL、registry 或独立观测链路。

## 修复范围

### 数据库契约

- 将 `bi_agent_runs.error_code` 从 `varchar(16)` 扩展为 `varchar(128)`。
- 审查同表和相关表的短字段：
  - `bi_agent_runs.status`
  - `bi_agent_runs.response_type`
  - `agent_conversation_messages.response_type`
  - `bi_agent_steps.step_type`
- 只对明确存在生产风险的字段扩容；不做无关 schema 重排。

### 持久化链路

- 加固 `_write_standard_fallback_run`。
- fallback path 返回 SSE `done` 前，必须确保 assistant message 已可持久化，或返回结构化错误。
- telemetry 写入失败时记录结构化日志，包含 `conversation_id`、`trace_id`、`run_id`、`error_code`。
- 不允许因为监控记录失败而让前端历史丢 assistant 回复。

### 测试与发布

- 增加 migration/schema 测试。
- 增加 fallback stream 回归测试。
- 增加 Agent admin run 可见性测试。
- 容器重建后用真实页面路径验证：
  - `http://localhost:3000/?conv=dddc13f8-8348-404a-a0e5-83a0ffbb5fcb&connection=4`
  - 新建请求 `你有哪些看板？`

## 推荐实施顺序

1. OpenSpec change：建立 proposal/tasks/design，锁定生产边界。
2. 数据库 migration：扩容 `error_code` 等必要字段。
3. fallback 持久化链路：调整事务边界，保证 assistant message 不丢。
4. 测试补齐：覆盖 DB、stream、admin runs。
5. 本地验证：py_compile、targeted pytest、必要时全量 data_agent tests。
6. 容器验证：重建 backend，触发真实问题，确认监控和历史一致。
7. 历史数据处理：默认不自动补偿；如需补偿，单独人工确认。

## 风险控制

- migration 必须可回滚，但生产回滚前要检查是否已有超过旧长度的数据。
- 事务边界调整要避免重复插入 assistant message。
- 不能吞掉 telemetry 写入错误；只能降级为不阻断用户历史。
- 不允许把 fallback error code 截断后写入，避免监控语义丢失。

## 验收标准

- `ROUTER_CLARIFY_REQUIRED` 可成功写入 `bi_agent_runs.error_code`。
- fallback run 出现在 Agent 监控页面。
- 刷新会话后 assistant fallback 回复仍存在。
- 后端日志不再出现 `StringDataRightTruncation`。
- 测试覆盖新增失败链路。
