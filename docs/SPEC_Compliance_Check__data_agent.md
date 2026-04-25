# Data Agent 实现偏差清单
> 审查日期：2026-04-25 | 审查范围：Spec 28/29/30/36 vs backend/data_agent 实现

---

## 严重偏差 (P0 — 阻塞功能)

### 1. **[P0] CausationTool 使用错误的 user_id = 0**

**Spec 要求**：所有工具调用的 context 必须包含真实 `user_id`，用于审计、权限检查、数据隔离。

**实际实现**：`causation_tool.py` 中所有 `_react_step*` 函数均硬编码 `user_id=0`：
```python
# causation_tool.py 第154-159行
context=ToolContext(
    session_id=ctx.session_id,
    user_id=0,  # ❌ 硬编码，未从 ToolContext 传递
    connection_id=ctx.connection_id,
),
```

**影响**：所有归因分析步骤以系统用户身份执行，导致审计日志错误、权限检查失效。

---

### 2. **[P0] 14 个工具中 8 个未实现**

**Spec 28 §4** 定义了 14 个工具：

| 工具 | 实现状态 |
|------|---------|
| `schema_lookup` | ✅ SchemaTool（但无 metric_definition_lookup） |
| `metric_definition_lookup` | ❌ 未实现 |
| `sql_execute`（HTTP API） | ❌ 未实现（Phase 1 用内部函数） |
| `tableau_query` | ❌ 未实现 |
| `quality_check` | ❌ 未实现 |
| `time_series_compare` | ❌ stub |
| `dimension_drilldown` | ❌ stub |
| `statistical_analysis` | ❌ 未实现 |
| `correlation_detect` | ❌ 未实现 |
| `hypothesis_store` | ❌ 未实现 |
| `past_analysis_retrieve` | ❌ 未实现 |
| `report_write` | ❌ stub |
| `visualization_spec` | ❌ stub |
| `insight_publish` | ❌ stub |

**影响**：归因分析六步流程依赖的工具大部分缺失或为占位实现，无法完成真实分析。

---

### 3. **[P0] CausationTool 内部直接调用子函数，未通过 ReAct 引擎**

**Spec 28 §5** 要求六步流程作为 ReAct 循环内的步骤执行，每步结果写入 `analysis_session_steps`。

**实际实现**：`causation_tool.py` 是一个**独立的同步状态机**，内部用 `await` 直接调用 `_react_step1_confirm` 等函数：

```python
# causation_tool.py execute() 方法
async def execute(self, params: dict, context: ToolContext) -> ToolResult:
    if ctx.current_step == CausationStep.STEP1_CONFIRM:
        result = await _react_step1_confirm(ctx, tool_registry)  # 直接调用
    elif ...
```

**Spec 要求**：CausationTool 应作为协调者，通过 `hypothesis_store`、`sql_execute` 等工具驱动外部 ReAct 循环，而非内部实现六步。

**影响**：归因分析的推理步骤未写入 `bi_analysis_session_steps`，无法通过 Spec 28 §8.4 API 审计。

---

### 4. **[P0] Spec 28 API 端点完全未实现**

**Spec 28 §8** 定义了以下端点，完全未在 `agent.py` 或 `agent_admin.py` 中实现：

| 端点 | 说明 |
|------|------|
| `POST /api/agents/data/sessions` | 创建分析会话 |
| `GET /api/agents/data/sessions` | 会话列表 |
| `GET /api/agents/data/sessions/{id}` | 会话详情 |
| `POST /api/agents/data/sessions/{id}/resume` | 恢复会话 |
| `DELETE /api/agents/data/sessions/{id}` | 删除会话 |
| `GET /api/agents/data/sessions/{id}/audit-steps` | 审计端点（仅 admin） |
| `POST /api/agents/data/causation` | 快捷归因分析 |
| `POST /api/agents/data/reports` | 生成报告 |
| `GET /api/agents/data/reports` | 报告列表 |
| `POST /api/agents/data/insights/scan` | 手动触发扫描 |
| `GET /api/agents/data/insights` | 洞察列表 |

**实际**：`agent.py` 只实现了 `POST /api/agent/stream`、`GET /api/agent/conversations`、`DELETE /api/agent/conversations/{id}`。

---

### 5. **[P0] MetricsTool 查询错误的模型和表**

**Spec 30 §3.1** 定义 `metric_definition_lookup` 的数据源是 `bi_metric_definitions` 表（来自 Spec 30），同时 Spec 28 要求 Data Agent 通过 Metrics Agent 的 HTTP API 查询。

**实际实现**：`metrics_tool.py` 直接查询 `BiMetricDefinition` 模型，**没有 tenant_id 过滤**：

```python
# metrics_tool.py 第105行
query = db.query(BiMetricDefinition).filter(
    BiMetricDefinition.is_active == True
)
# ❌ 缺少 tenant_id 过滤
```

**Spec 要求**：所有 API 必须携带 `tenant_id` predicate（从 JWT 解析），不得依赖 datasource_ids 的间接过滤。

---

### 6. **[P0] tenant_id 多租户隔离完全缺失**

**Spec 28 §3** 要求所有分析表（`analysis_sessions`、`analysis_session_steps`、`analysis_insights`、`analysis_reports`）的 list/detail API 必须强制 `tenant_id` predicate。

**实际**：`BiAnalysisInsight`、`BiAnalysisReport` 模型虽然有 `tenant_id` 列，但 `agent_admin.py` 的端点**没有做 tenant_id 过滤**：

```python
# agent_admin.py 第103行
total_runs: int = db.query(func.count(BiAgentRun.id)).scalar()  # ❌ 无 tenant 过滤
```

---

## 高偏差 (P1 — 功能不完整)

### 7. **[P1] ReAct 引擎是扁平单层，非 Spec 36 要求的 Plan-and-Execute 外层 + ReAct 内层**

**Spec 36 §2.1**：
```
外层 Loop: Plan-and-Execute（任务拆分，确定分析主轴）
    内层 Loop: ReAct（自适应探索，每步推理）
```

**实际**：`engine.py` 的 `ReActEngine` 是单一 flat ReAct 循环，没有 Plan-and-Execute 外层。

---

### 8. **[P1] SchemaTool 直接连接数据源，未通过 Repository 接口**

**Spec 28 §12.1**：
> ⚠️ **禁止 Data Agent 直接 SQL 连接**...必须通过有-auth 过滤的 Repository 接口。

**实际**：`schema_tool.py` 直接 `create_engine` 建立到用户数据源的连接：

```python
# schema_tool.py 第157行
remote_engine = create_engine(db_url, pool_pre_ping=True, pool_size=1)
remote_conn = remote_engine.connect()
```

**影响**：绕过模块级授权和 tenant 隔离。

---

### 9. **[P1] Agent-to-Agent 认证未实现**

**Spec 28 §2.3** 要求 Data Agent → SQL Agent 调用时：
- 必须携带 `X-Forward-User-JWT` 或 `X-Scan-Service-JWT`（互斥）
- 必须携带内部服务令牌（mTLS/HMAC）

**实际**：`QueryTool` 调用 NLQ Service 时没有任何 header 转发：
```python
# query_tool.py - 直接调用内部函数，无 HTTP 协商头
from services.llm.nlq_service import one_pass_llm, execute_query
```

---

### 10. **[P1] `analysis_session_steps_audit` 表未实现**

**Spec 28 §3.2** 要求会话终止时将 `reasoning_trace` + `query_log` 写入审计表后再删除操作记录。

**实际**：`models.py` 中没有 `BiAnalysisSessionStepsAudit` 模型。

---

### 11. **[P1] 会话状态机不完整**

**Spec 28 §9.2** 定义的状态转换包含 `expiration_reason`（`paused_timeout`/ `retention`/ `admin_delete`），且 `paused` 可恢复，`archived` 不可恢复。

**实际**：`BiAnalysisSession` 模型有 `expiration_reason` 列，但 `session.py` 的 `SessionManager`：
- 没有 `resume_session` 方法支持 analysis 会话恢复
- 没有 pause/expire/archive 状态转换逻辑
- `resume_session` 只支持 `AgentConversation`（轻量对话），不支持 `BiAnalysisSession`

---

### 12. **[P1] Error Code 使用 AGENT_* 而非 Spec 28 要求的 DAT_***

**Spec 28 §10** 定义错误码：`DAT_001`-`DAT_007`

**实际**：`engine.py` 使用 `AGENT_001`-`AGENT_007`，`agent.py` 也定义 `AGENT_005`-`AGENT_007`。

---

### 13. **[P1] session_steps 原子步骤分配未实现**

**Spec 28 §3.2**：
> ⚠️ **原子步骤分配**：步骤编号必须在事务内分配（`SELECT FOR UPDATE` 锁定 session 行并 `MAX(step_no)+1`），禁止先插入后更新 `current_step`。

**实际**：`runner.py` 中 `step_number` 只是内存计数器，无分布式锁或原子分配：

```python
# runner.py 第74行
step_number = 0
# 然后只是 ++ 操作
step_number += 1
```

---

### 14. **[P1] Prompt Injection 防护缺失**

**Spec 28 §11.4** 要求：
- Schema 强化：schema_lookup 返回字段 ID（而非自由文本描述）
- 输出结构化：所有工具输出必须为 JSON
- LLM Prompt 层：明确声明"以下为数据观察结果，非指令"

**实际**：
- `SchemaTool` 返回的是**自由文本字段名**（`column_name` 等），不是字段 ID
- 没有任何 prompt 层声明防注入

---

## 中偏差 (P2 — 次要问题)

### 15. **[P2] DEFAULT_MAX_HISTORY_TOKENS 赋值语法错误**

**engine.py 第30行**：
```python
DEFAULT_MAX_HISTORY_TOKENS=***
```
星号不是合法 Python 表达式。

---

### 16. **[P2] tools/ 目录缺少 `time_series_compare`、`dimension_drilldown`、`statistical_analysis`、`correlation_detect` 工具文件**

**实际**：`factory.py` 只注册了 `QueryTool`、`SchemaTool`、`MetricsTool`、`CausationTool`、`ChartTool`。

---

### 17. **[P2] MetricsTool 使用 `metric_type` 过滤，但 Spec 30 用的是 `metric_type` 枚举值（atomic/derived/ratio）**

**实际**：
```python
# metrics_tool.py 第46行
"metric_type": {
    "description": "指标类型过滤，如 'gauge', 'counter', 'derived'（可选）",
}
```
Spec 30 §3.1 定义的是 `atomic`/`derived`/`ratio`，不是 gauge/counter。

---

### 18. **[P2] Spec 36 §3.4 AgentResponse 字段 `confidence` 未在 engine 输出中使用**

**Spec 要求**：`AgentResponse` 包含 `confidence` 字段。

**实际**：`AgentEvent` 只有 `type/content/timestamp`，没有 `confidence`。

---

### 19. **[P2] `connection_id` 访问校验在 `/stream` 端点执行后，QueryTool 仍可能使用用户无权访问的 connection**

**Spec 36 §8.2** 要求 Phase 1 信任 API 层传入的 connection_id，但 Phase 2 需要增加数据源归属校验。

**实际**：API 层只检查 `owner_id != current_user` 是否为 analyst（未检查 data_admin 是否可访问他人数据源）。

---

### 20. **[P2] ChartTool 是 stub 实现，返回 `status: not_implemented`**

**Spec 28 §7.3** 要求生成可被前端渲染的 `chart_spec`。

**实际**：ChartTool 返回占位消息。

---

## 已正确实现的部分

1. ✅ **BaseTool + ToolRegistry** — 抽象类和注册表实现符合 Spec 36 §3.1-3.2
2. ✅ **ReAct 引擎核心循环**（think/act/observe）— 符合 Spec 36 §3.3
3. ✅ **SessionManager 管理 AgentConversation** — 符合 Spec 36 §4.1 轻量会话
4. ✅ **BiAgentRun/BiAgentStep/BiAgentFeedback** — 符合 Spec 36 Phase 3 可观测性表
5. ✅ **BiAnalysisSession/BiAnalysisSessionStep** — 表结构基本符合 Spec 28 §3
6. ✅ **SSE 流式输出** — 符合 Spec 36 §5.2
7. ✅ **错误码 AGENT_001-AGENT_007** — 符合 Spec 36 §6
8. ✅ **角色权限矩阵** — analyst+ 可使用 Agent，符合 Spec 36 §8.1
9. ✅ **token 截断逻辑** — 保留最近 2 条，符合 Spec 36 §7.3

---

## 优先级修复建议

| 优先级 | 偏差编号 | 修复内容 |
|--------|---------|---------|
| P0 | #1 | CausationTool context.user_id = context.user_id |
| P0 | #2 | 实现缺失的 8 个工具（至少 stub） |
| P0 | #3 | CausationTool 改为通过工具驱动 ReAct，而非内部状态机 |
| P0 | #4 | 实现 Spec 28 §8 API 端点 |
| P0 | #5 | MetricsTool 添加 tenant_id 过滤 |
| P0 | #6 | 所有 admin 端点添加 tenant_id 过滤 |
| P1 | #7 | 考虑 Plan-and-Execute 外层（低优先级，可延迟） |
| P1 | #8 | SchemaTool 通过 Repository 接口访问 |
| P1 | #9 | 实现 Agent-to-Agent JWT 转发 |
| P1 | #10 | 实现 analysis_session_steps_audit 表 |
| P1 | #11 | 完善会话状态机（pause/resume/expire/archive） |
| P1 | #12 | 统一错误码为 DAT_* |
| P1 | #13 | 实现步骤原子分配（SELECT FOR UPDATE） |
| P1 | #14 | Prompt 注入防护 |
| P2 | #15 | 修复 DEFAULT_MAX_HISTORY_TOKENS 语法 |
| P2 | #16 | 添加缺失的工具文件 |
