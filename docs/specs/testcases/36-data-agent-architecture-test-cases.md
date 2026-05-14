# Data Agent 架构 — 测试用例

> 关联 Spec：36-data-agent-architecture-spec.md
> 日期：2026-04-24
> 更新：2026-04-25（Phase 3 可观测性 + 反馈端点）

---

## 1. 单元测试：ReAct Engine

### TC-ENG-001：单步直接回答（闲聊场景）

**前置条件**：注册 0 个工具（或 QueryTool）
**输入**：`query = "你好"`
**预期**：
- Engine 第一步 Think 判定为闲聊
- 不调用任何工具
- 直接 yield `AgentEvent(type="answer")`
- `steps_count == 1`
- `tools_used == []`

---

### TC-ENG-002：单工具调用（查询场景）

**前置条件**：注册 MockQueryTool（返回固定 `ToolResult(success=True, data={"value": 3200})`）
**输入**：`query = "Q4 销售额是多少"`
**预期事件序列**：
1. `AgentEvent(type="thinking", ...)`
2. `AgentEvent(type="tool_call", content={"tool": "query", ...})`
3. `AgentEvent(type="tool_result", ...)`
4. `AgentEvent(type="answer", ...)`
- `tools_used == ["query"]`
- `steps_count <= 3`

---

### TC-ENG-003：max_steps 熔断

**前置条件**：注册 MockTool（永远返回需要继续推理的结果），`max_steps=3`
**输入**：`query = "分析一下趋势"`
**预期**：
- 恰好执行 3 步后停止
- 最后一个事件为 `AgentEvent(type="answer")`，内容包含"已达到最大推理步数"
- 不抛异常

---

### TC-ENG-004：工具执行失败

**前置条件**：注册 MockTool（`execute()` 抛 `RuntimeError`），`max_tool_retries=1`
**输入**：`query = "查询数据"`
**预期**：
- 工具重试 1 次
- 仍失败后 yield `AgentEvent(type="error", content={"error_code": "AGENT_003", ...})`
- 不暴露内部异常信息

---

### TC-ENG-005：step_timeout 超时

**前置条件**：注册 MockTool（`execute()` sleep 40s），`step_timeout=30`
**输入**：`query = "查询"`
**预期**：
- 30s 后工具调用被取消
- yield error 事件，`error_code == "AGENT_001"`

---

## 2. 单元测试：ToolRegistry

### TC-REG-001：注册 + 获取工具

**操作**：`registry.register(QueryTool())` → `registry.get("query")`
**预期**：返回 QueryTool 实例

---

### TC-REG-002：获取不存在的工具

**操作**：`registry.get("nonexistent")`
**预期**：抛 `KeyError` 或返回 `None`（按实现约定）

---

### TC-REG-003：重复注册同名工具

**操作**：注册两个 `name="query"` 的工具
**预期**：抛异常或后者覆盖前者（按实现约定，建议抛异常）

---

### TC-REG-004：get_tool_descriptions 格式

**前置条件**：注册 QueryTool + SchemaTool
**预期**：返回 list[dict]，每项包含 `name`, `description`, `parameters_schema`

---

## 3. 集成测试：QueryTool

### TC-QT-001：正常查询

**前置条件**：真实 nlq_service 可用，数据源连接正常
**输入**：`params = {"question": "Q4 总销售额", "connection_id": 1}`
**预期**：
- `ToolResult.success == True`
- `ToolResult.data` 包含 `answer`, `type`（number/table/text）
- `execution_time_ms > 0`

---

### TC-QT-002：无效 connection_id

**输入**：`params = {"question": "...", "connection_id": 99999}`
**预期**：
- `ToolResult.success == False`
- `ToolResult.error` 包含权限或连接相关错误

---

### TC-QT-003：NLQ 服务异常

**前置条件**：mock nlq_service 抛异常
**预期**：
- QueryTool 捕获异常
- 返回 `ToolResult(success=False, error="查询服务暂时不可用")`
- 不暴露内部堆栈

---

## 3b. 集成测试：SchemaTool

### TC-SCHEMA-001：connection_id 缺失

**输入**：`params = {}`，`context.connection_id = None`
**预期**：`ToolResult.success == False`，error 包含 "connection_id is required"

---

### TC-SCHEMA-002：DataSource 不存在

**输入**：`params = {}`，`context.connection_id = 9999`
**预期**：`ToolResult.success == False`，error 包含 "not found"

---

### TC-SCHEMA-003：成功查询表列表（PostgreSQL）

**前置条件**：mock DataSource（PostgreSQL），mock 远程数据库返回 2 张表
**输入**：`params = {"limit": 100}`
**预期**：
- `ToolResult.success == True`
- `data["tables"]` 包含 2 个表名
- `data["db_type"] == "postgresql"`

---

### TC-SCHEMA-004：成功查询指定表字段

**输入**：`params = {"table_name": "sales"}`
**预期**：
- `data["fields"]["sales"]` 包含各字段的 name、type、is_nullable、is_primary_key
- 主键字段 `is_primary_key == True`

---

### TC-SCHEMA-005：数据库连接异常

**前置条件**：mock 远程 DB `execute()` 抛 Exception
**预期**：`ToolResult.success == False`，error 包含 "查询表结构失败"，不暴露内部堆栈

---

### TC-SCHEMA-006：MySQL 场景

**前置条件**：mock DataSource（`db_type="mysql"`）
**预期**：`data["db_type"] == "mysql"`，使用 mysql+pymysql 驱动

---

### TC-SCHEMA-007：SQL Server 场景

**前置条件**：mock DataSource（`db_type="sqlserver"`）
**预期**：`data["db_type"] == "sqlserver"`，使用 mssql+pymssql 驱动

---

## 3c. 集成测试：MetricsTool

### TC-METRICS-001：无筛选条件查询

**输入**：`params = {}`
**预期**：
- `ToolResult.success == True`
- `data["total"]` 为活跃指标总数
- `data["metrics"]` 为列表，每项含 name、name_zh、metric_type 等字段

---

### TC-METRICS-002：按 connection_id 过滤

**输入**：`params = {"connection_id": 10}`
**预期**：`data["filters"]["connection_id"] == 10`，仅返回对应数据源的指标

---

### TC-METRICS-003：按关键词搜索

**输入**：`params = {"keyword": "销售"}`
**预期**：`data["filters"]["keyword"] == "销售"`，返回名称/描述含"销售"的指标

---

### TC-METRICS-004：按 metric_type 过滤

**输入**：`params = {"metric_type": "gauge"}`
**预期**：仅返回 `metric_type == "gauge"` 的指标

---

### TC-METRICS-005：多条件组合过滤

**输入**：`params = {"connection_id": 1, "keyword": "sales", "metric_type": "gauge", "business_domain": "sales"}`
**预期**：filters 对象包含所有条件，结果为交集

---

### TC-METRICS-006：limit 参数

**输入**：`params = {"limit": 5}`
**预期**：返回最多 5 条，`data["total"]` 为匹配总数（可能 > 5）

---

### TC-METRICS-007：无匹配结果

**输入**：`params = {"keyword": "nonexistent"}`
**预期**：`data["total"] == 0`，`data["metrics"] == []`

---

### TC-METRICS-008：数据库异常

**前置条件**：mock `session.query` 抛 Exception
**预期**：`ToolResult.success == False`，error 包含 "查询指标定义失败"

---

### TC-METRICS-009：context.connection_id 作为默认值

**输入**：`params = {}`，`context.connection_id = 5`
**预期**：自动使用 `connection_id=5` 过滤

---

## 3d. connection_id 权限校验

### TC-PERM-001：connection_id 为 None 时跳过校验

**请求**：`POST /api/agent/stream`，`connection_id` 为空
**预期**：正常执行，不触发权限检查

---

### TC-PERM-002：数据源不存在或已停用

**请求**：`connection_id = 99999`（不存在）
**预期**：404，`error_code: "AGENT_004"`，message 包含"数据源不存在或已停用"

---

### TC-PERM-003：admin / data_admin 可访问任意活跃数据源

**前置条件**：当前用户 role = admin，数据源 owner 为其他用户
**预期**：正常执行，不报 403

---

### TC-PERM-004：analyst 仅可访问自身 owner 的数据源

**前置条件**：当前用户 role = analyst（id=1），数据源 owner_id = 999
**预期**：403，`error_code: "AGENT_005"`

---

### TC-PERM-005：analyst 访问自身数据源

**前置条件**：当前用户 role = analyst（id=1），数据源 owner_id = 1
**预期**：正常执行

---

## 3e. 历史截断

### TC-HIST-001：token 估算

**输入**：纯中文 "你好世界"（4 字符）
**预期**：估算 ≈ 4 tokens

---

### TC-HIST-002：混合文本 token 估算

**输入**："Hello 世界 123"
**预期**：ASCII 部分按 4 字符/token，中文按 1 字符/token

---

### TC-HIST-003：短历史不截断

**输入**：3 条消息，总 token < budget
**预期**：返回全部 3 条消息

---

### TC-HIST-004：超长历史截断

**输入**：20 条消息，总 token >> budget
**预期**：
- 最后 2 条消息始终保留（最近上下文）
- 截断后总 token ≤ budget
- 返回的消息按原顺序

---

## 4. API 测试：POST /api/agent/stream

### TC-API-001：正常 SSE 流

**请求**：
```json
{"question": "Q4 销售额是多少？", "connection_id": 1}
```
**预期**：
- 响应 Content-Type: `text/event-stream`
- 至少包含事件：`metadata` → `thinking`（可选）→ ... → `done`
- `done` 事件包含 `answer`, `trace_id`, `tools_used`, `response_type`
- 自动创建 conversation，`metadata` 事件返回 `conversation_id`

---

### TC-API-002：续接已有会话

**前置条件**：已有 conversation_id = "xxx"
**请求**：
```json
{"question": "环比呢？", "conversation_id": "xxx", "connection_id": 1}
```
**预期**：
- Engine 加载历史消息作为上下文
- 回答能引用上一轮的数据
- 消息写入同一 conversation

---

### TC-API-003：未认证请求

**请求**：无 cookie / token
**预期**：401 Unauthorized

---

### TC-API-004：user 角色（无权限）

**前置条件**：当前用户角色 = user（非 analyst+）
**预期**：403 Forbidden

---

### TC-API-005：空问题

**请求**：`{"question": "", "connection_id": 1}`
**预期**：400 Bad Request，`error_code: "AGENT_002"`

---

### TC-API-006：无效 conversation_id

**请求**：`{"question": "...", "conversation_id": "not-exist"}`
**预期**：404 Not Found，`error_code: "AGENT_004"`

---

## 5. API 测试：会话管理

### TC-CONV-001：列出会话

**请求**：`GET /api/agent/conversations`
**预期**：只返回当前用户的会话，按 updated_at DESC 排序

---

### TC-CONV-002：获取会话消息

**请求**：`GET /api/agent/conversations/{id}/messages`
**预期**：按 created_at ASC 返回消息列表，包含 role, content, response_type

---

### TC-CONV-003：归档会话

**请求**：`DELETE /api/agent/conversations/{id}`
**预期**：状态变为 archived，后续不在列表出现

---

### TC-CONV-004：跨用户访问会话

**前置条件**：会话属于 user_A
**请求**：user_B `GET /api/agent/conversations/{id}/messages`
**预期**：404 Not Found（非 admin 不可见）

---

## 6. 端到端测试

### TC-E2E-001：首页问数据完整链路

**步骤**：
1. 前端首页 AskBar 输入"Q4 销售额是多少"
2. 点击发送

**预期**：
- SSE 事件流正常接收
- 页面渲染出回答文本
- 回答包含数字结果
- 用户体感与改造前一致

---

### TC-E2E-002：首页闲聊

**步骤**：
1. 前端首页 AskBar 输入"你好"
2. 点击发送

**预期**：
- 不触发数据查询
- 直接返回友好文本回复
- 无 tool_call 事件

---

### TC-E2E-003：多轮对话

**步骤**：
1. 输入"Q4 各区域销售额"
2. 收到回答后输入"最高的是哪个区域？"

**预期**：
- 第二轮回答引用第一轮查询结果
- 两条消息属于同一 conversation

---

### TC-E2E-004：现有 API 兼容性

**步骤**：
1. 直接调用 `GET /api/chat/stream?q=test&connection_id=1`
2. 直接调用 `POST /api/ask-data`

**预期**：
- 两个端点仍正常工作（内部转发到 Agent）
- 响应格式与改造前兼容

---

## 7. 回归测试

### TC-REG-001：NLQ 直连链路不受影响

**前置条件**：`POST /api/search/query` 直接调用
**预期**：该端点独立于 Agent 层，不受改造影响

---

### TC-REG-002：Query 页面不受影响

**前置条件**：`/query` 页面使用 `/api/query/ask`
**预期**：该链路独立，不受 Agent 改造影响

---

### TC-REG-003：反馈 API 兼容

**前置条件**：`POST /api/ask-data/feedback`
**预期**：反馈 API 仍正常工作，trace_id 可追踪到 Agent 运行

---

## 8. Phase 3 可观测性测试

### TC-OBS-001：SSE 事件包含 run_id

**请求**：`POST /api/agent/stream`（正常问题）
**预期**：
- `metadata` 事件包含 `run_id` 字段，值为合法 UUID
- `done` 事件包含 `run_id` 字段，与 `metadata` 中一致
- 前端可据此调用 feedback 端点

---

### TC-OBS-002：Agent 运行记录落库

**前置条件**：完成一次正常流式对话
**预期**：
- `bi_agent_runs` 表新增一条记录
- `status = 'completed'`
- `question` 与请求一致
- `execution_time_ms > 0`
- `completed_at IS NOT NULL`
- `tools_used` 包含本次调用的工具名

---

### TC-OBS-003：Agent 步骤记录落库

**前置条件**：一次包含 thinking → tool_call → tool_result → answer 的完整对话
**预期**：
- `bi_agent_steps` 表新增 4 条记录（每种事件类型各一条）
- `step_number` 从 1 连续递增
- `step_type` 依次为 `thinking`, `tool_call`, `tool_result`, `answer`
- `tool_call` 步骤有 `tool_name` 和 `tool_params`
- `tool_result` 步骤有 `tool_result_summary`（截断至 500 字符）

---

### TC-OBS-004：引擎错误标记 run 为 failed

**前置条件**：Engine 返回 error 事件
**预期**：
- `bi_agent_runs.status = 'failed'`
- `bi_agent_runs.error_code` 与 error 事件的 `error_code` 一致
- `bi_agent_steps` 中有一条 `step_type = 'error'` 的记录

---

### TC-OBS-005：异常崩溃也标记 failed

**前置条件**：Engine 抛未捕获异常
**预期**：
- SSE 返回 `error` 事件（`AGENT_003`）
- `bi_agent_runs.status = 'failed'`
- `bi_agent_runs.error_code = 'AGENT_003'`

---

## 9. 反馈端点测试：POST /api/agent/feedback

### TC-OBS-006：正常提交反馈

**请求**：
```json
{"run_id": "<valid-uuid>", "rating": "up", "comment": "很有用"}
```
**预期**：
- 200，`{"status": "created", "feedback_id": <int>}`
- `bi_agent_feedback` 表新增一条记录

---

### TC-OBS-007：重复提交更新反馈

**前置条件**：同一 run_id + user_id 已有 rating="up"
**请求**：`{"run_id": "...", "rating": "down", "comment": "改主意了"}`
**预期**：
- 200，`{"status": "updated", "feedback_id": <int>}`
- 数据库中 rating 更新为 "down"，不新增记录

---

### TC-OBS-008：无效 run_id 格式

**请求**：`{"run_id": "not-a-uuid", "rating": "up"}`
**预期**：400，`error_code: "AGENT_007"`

---

### TC-OBS-009：不存在的 run_id

**请求**：`{"run_id": "<random-uuid>", "rating": "up"}`
**预期**：404，`error_code: "AGENT_004"`

---

### TC-OBS-010：无效 rating 值

**请求**：`{"run_id": "...", "rating": "meh"}`
**预期**：422 Validation Error（rating 必须为 up 或 down）

---

### TC-OBS-011：未认证请求

**请求**：无 cookie / token
**预期**：401 Unauthorized

---

### TC-OBS-012：非 analyst 角色

**前置条件**：当前用户角色 = user
**预期**：403 Forbidden
