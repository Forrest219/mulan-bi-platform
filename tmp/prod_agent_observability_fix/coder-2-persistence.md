# coder-2：Agent stream/fallback 持久化链路加固

## 目标

修复 `/api/agent/stream` 在 fallback 分支中的持久化不一致问题：

- 当前链路会先持久化 `user` message。
- fallback run/step 写入失败时，异常被 catch 后 SSE 仍返回 `done`。
- 但 `assistant` message 未落库，刷新页面后只剩用户问题。

目标是保证：只要 SSE 返回 `done`，对应 assistant message 必须已经成功持久化；如果 assistant 持久化失败，则不返回假成功，改为可观测、可重试的错误事件。run/step telemetry 正常路径必须写入，但 telemetry 写入失败不得阻断用户可见回复落库。

## 涉及文件

- `backend/app/api/agent.py`
  - `/api/agent/stream`
  - `_write_standard_fallback_run`
  - fallback / deterministic route 的 `done` 发送前持久化逻辑
- `backend/services/data_agent/runner.py`
  - 标准 ReAct / MCP controlled path / error fallback 的 run、step、assistant message 写入顺序
- `backend/services/data_agent/session.py`
  - `SessionManager.persist_message`
  - 如需支持事务内复用，可新增默认不破坏现有行为的参数
- 相关测试：
  - `backend/tests/services/data_agent/test_runner.py`
  - `backend/tests/test_chat_ask_data_api.py`
  - 可新增 focused agent stream persistence 测试

## 实施步骤

1. 梳理所有会向 SSE 返回最终结果的分支：
   - clarification fallback
   - deterministic schema inventory success
   - deterministic schema inventory error
   - controlled data path answer/error
   - legacy ReAct answer/error
   - cancellation/exception error fallback

2. 调整 fallback 分支顺序：
   - `_write_standard_fallback_run(...)` 不应把 telemetry 失败和 assistant message 失败混在一个不可恢复的事务里。
   - 正常路径写入 `BiAgentRun`、`BiAgentStep`、`assistant message`。
   - 如果 run/step telemetry 写入失败，回滚 telemetry 事务，记录结构化日志，然后继续持久化 assistant message。
   - 只有 assistant message 持久化成功后才能发送 `done`。
   - assistant message 持久化失败时发送 `error` SSE，包含 `trace_id` 和 `retryable=true`。

3. 调整标准 answer 路径：
   - 避免先 `yield done` 后 `persist_message`。
   - 所有 answer 路径统一为：
     1. 写 run/step telemetry。
     2. 若 telemetry 失败，rollback telemetry 并记录结构化日志。
     3. 写 assistant message。
     4. yield `done`。

4. 可抽取小型 helper，减少分支重复：
   - 建议命名：`_persist_final_agent_response(...)` 或 `_persist_assistant_outcome(...)`。
   - helper 只做最终响应落库，不负责 SSE 组装。

5. 如需调整 `SessionManager.persist_message`：
   - 可增加 `commit: bool = True`。
   - 默认行为保持不变。
   - 最终响应事务可使用 `commit=False`，由外层统一提交。

6. 增加日志与可观测性：
   - 持久化失败必须 `logger.exception`。
   - 日志至少包含 `trace_id`、`conversation_id`、`run_id`、`user_id`、`response_type`。
   - 不输出完整用户问题或完整回答，最多截断摘要。

## 事务边界建议

- `user message` 可以继续作为独立事务提交。
  - 理由：请求已经被服务端接收，保留用户问题有审计价值。
  - 不要求在 assistant 失败时回滚 user message。
- 最终 assistant message 是用户可见历史的硬门槛：
  - `AgentConversationMessage(role="assistant")`
  - `agent_conversations.updated_at`
  - 以上必须 commit 成功后才能发送 SSE `done`。
- run/step telemetry 是观测链路：
  - `BiAgentRun` 最终状态更新
  - 最后一条 `BiAgentStep`
  - 正常情况下必须写入。
  - 失败时必须结构化日志告警，但不得导致 assistant message 丢失。
- SSE `done` 只能在 assistant message commit 成功后发送。
- 中间 step 的 `thinking`、`tool_call`、`tool_result` 可继续分步提交。

## 失败降级策略

- fallback 内容生成成功但 assistant message 持久化失败：
  - 不返回 `done`。
  - 返回 SSE `error`：
    - `type: "error"`
    - `error_code: "AGENT_PERSISTENCE_FAILED"` 或既有持久化错误码
    - `message: "回答生成成功但保存失败，请重试。"`
    - `trace_id`
    - `retryable: true`
- run/step telemetry 写入失败但 assistant message 尚未写入：
  - 回滚 telemetry 事务。
  - 记录结构化日志，包含 `trace_id`、`conversation_id`、`run_id`、`error_code`。
  - 继续持久化 assistant message。
  - assistant message 成功后可以返回 `done`，但日志中必须能解释 Agent 监控缺失。
- assistant message 写入失败：
  - 回滚 assistant message 事务。
  - 发送持久化错误 SSE。
  - 不发送 `done`。
- SSE 客户端已断开：
  - 不强行补写成功 assistant message，除非当前分支已完成最终响应事务。

## 风险

- 改动涉及 SSE 返回时序，需确认 `done` 后历史查询能立即看到 assistant message。
- `SessionManager.persist_message(commit=False)` 若新增参数，需要检查调用点并保持默认 `commit=True`。
- 多分支当前提交顺序不一致，只修 fallback 可能留下同类隐患。
- 如果数据库短暂不可用，用户会看到错误而不是已生成 fallback 答案；这是有意取舍，优先保证刷新后一致性。
- 如果只有 telemetry 短暂失败而 assistant message 成功，用户仍会看到完成回复，但 Agent 监控可能缺失；该情况必须通过结构化日志和告警追踪。
- 当前仓库可能已有其他人改动相关文件，实施时只修改本任务必要范围，不回滚他人改动。

## 测试命令

```bash
cd backend && python3 -m py_compile app/api/agent.py services/data_agent/runner.py services/data_agent/session.py
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/services/data_agent/test_runner.py -q -o addopts=''
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_chat_ask_data_api.py -q -o addopts=''
```

如新增 focused 测试：

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_agent_stream_persistence.py -q -o addopts=''
```

## 验收标准

- clarification fallback 正常成功时：
  - SSE 返回 `done`。
  - `agent_conversation_messages` 中存在对应 `user` 和 `assistant` 两条消息。
  - 刷新会话历史后能看到 fallback assistant 回答。
- 模拟 fallback assistant message 持久化失败时：
  - SSE 不返回 `done`。
  - SSE 返回可重试的 `error`。
  - 日志包含 `trace_id`、`conversation_id`、`run_id`。
  - 不出现“前端已显示完成但刷新后 assistant 消失”。
- 模拟 fallback run/step telemetry 写入失败但 assistant message 成功时：
  - SSE 可以返回 `done`。
  - 刷新后 assistant message 仍存在。
  - 日志清楚记录 telemetry 写入失败和定位字段。
- 标准 ReAct answer 路径中：
  - `assistant message` 持久化成功后才发送 `done`。
  - 测试覆盖 `persist_message` 抛异常时不会发送 `done`。
- 不新增数据库迁移。
- 不修改与本任务无关的业务逻辑、前端 UI 或他人已有改动。
