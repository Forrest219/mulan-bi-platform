# Agent 架构规划评审与修订

> 日期：2026-04-24
> 评审范围：`/Users/forrest/Documents/share_for_hermes/inbox@hermes/agent-architecture-planning.md`
> 代码基线：`/Users/forrest/Projects/mulan-bi-platform`

---

## 一、评审结论

原文档方向基本正确，但存在三类问题：

1. **事实层有偏差**
   - 目录结构与实际代码不完全一致。
   - 多处 LOC 统计口径混杂了“单文件 LOC”和“目录总 LOC”。
   - 前端菜单和首页交互状态有部分描述已过时。
   - `GET /api/chat/stream` 和 `POST /api/search/query` 并非“待确认”，二者都已实现。

2. **架构层有缺口**
   - 只提出“统一 Agent 基座”，但没有明确和现有 `search.py`、`conversations.py`、`capability.audit`、`task_runtime`、`tasks` 的衔接方式。
   - 没有区分“同步问答编排”和“异步长任务编排”。
   - 缺少权限委托、策略治理、审计、幂等、超时、回滚与降级设计。

3. **落地层不够稳**
   - 方案倾向于新建 `services/agents/` 后把现有能力整体搬迁，这会制造大范围重构风险。
   - 更合理的路径应是：**先做 Agent Orchestration 层，后做 Agent UI，再逐步接入 Data Agent**。

---

## 二、事实核验

### 2.1 目录结构核验

原文档中的核心判断大体成立，但需修正为：

```text
backend/services/
├── llm/                  # 已存在，NLQ 与 LLM 路由核心
├── sql_agent/            # 已存在，SQL Agent 已实现
├── metrics_agent/        # 已存在，指标相关服务已实现
├── tableau/              # 已存在，MCP 客户端与同步能力已实现
├── task_runtime/         # 已存在，非空，但仍是轻量状态机/模型层
├── mcp/                  # 已存在，仅模型层，不是“空目录”
├── tasks/                # 已存在，Celery 任务调度与任务管理已落地
├── audit_runtime/        # 已存在，trace/audit 运行时工具
├── capability/           # 已存在，能力调用审计
├── events/               # 已存在，事件与通知
├── knowledge_base/       # 已存在
├── dqc/                  # 已存在
├── requirements/         # 已存在
└── data_agent/           # 不存在
```

关键修正：

- `task_runtime/` 不是“仅占位 + pass”，而是已有状态枚举、数据类和状态机。
- `mcp/` 不是“空白”，而是已有 `McpServer` ORM 模型。
- `tasks/` 已是重要基础设施，不应在 Agent 规划中缺席。
- `data_agent/` 的确尚未实现。

### 2.2 LOC 核验

按当前代码库实际统计：

| 模块 | 原文档 | 实际 |
|------|--------|------|
| `backend/services/llm/service.py` | 598 LOC | 598 LOC |
| `backend/services/llm/nlq_service.py` | 1,143 LOC | 1,143 LOC |
| `backend/services/sql_agent/` | 977 LOC | 994 LOC |
| `backend/services/sql_agent/service.py` | 未拆分 | 436 LOC |
| `backend/services/sql_agent/executor.py` | 未拆分 | 164 LOC |
| `backend/services/sql_agent/models.py` | 未拆分 | 88 LOC |
| `backend/services/sql_agent/security.py` | 未拆分 | 289 LOC |
| `backend/services/metrics_agent/` | ~1,500 LOC | 2,189 LOC |
| `backend/services/tableau/` | 1,179 LOC | 2,726 LOC |
| `backend/services/tableau/mcp_client.py` | 1,179 LOC | 1,179 LOC |
| `backend/services/task_runtime/` | 195 LOC | 195 LOC |
| `backend/services/mcp/` | 31 LOC | 31 LOC |
| `backend/services/tasks/` | ~500 LOC | 2,192 LOC |

结论：

- 原文档对单文件 `service.py` 和目录总 LOC 混用，容易误导决策。
- `metrics_agent/` 和 `tasks/` 的规模被显著低估。
- `tableau/` 目录真实复杂度远高于“一个 MCP Client”。

### 2.3 前端菜单与入口核验

当前前端菜单确实是 **5 域**：

- `看板 / ops`
- `资产 / assets`
- `实验室 / lab`
- `治理 / governance`
- `设置 / system`

但原文档中“资产域”和“设置域”的子菜单描述不完整。实际菜单包括：

- `资产` 下已有 `连接总览`、`数据源管理`、`Tableau 连接`
- `设置` 下已有 `LLM 配置`、`MCP 配置`、`MCP 调试器`、`任务管理`、`操作日志`、`问数告警`

这意味着：

- Agent 管理后台若新增，最佳落点确实仍是 `设置 / system`。
- 但设计时必须考虑与已有 `LLM/MCP/任务/日志/告警` 页面形成一个完整运维闭环，而不是孤立新页面。

### 2.4 交互链路核验

原文档中“待确认”的两条链路都已存在：

- `GET /api/chat/stream` 已实现，位于 [backend/app/api/chat.py](/Users/forrest/Projects/mulan-bi-platform/backend/app/api/chat.py:1)
- `POST /api/search/query` 已实现，位于 [backend/app/api/search.py](/Users/forrest/Projects/mulan-bi-platform/backend/app/api/search.py:1317)

当前真实路径是：

```text
Home AskBar
  -> useStreamingChat / ask_data_contract
  -> GET /api/chat/stream
  -> chat.py 内部转发到 POST /api/search/query
  -> search.py 执行 NLQ / 元查询 / 数据源路由 / SQL 链路
```

另外：

- 首页 `USE_MOCK = false`，不是原文档中的 `USE_MOCK=true`
- AskBar 已支持连接选择、文件附件 UI、SSE 契约
- `conversations` API 已存在，说明 Agent 设计必须考虑会话持久化，而不是只处理一次性请求

---

## 三、原方案的主要问题

### 3.1 过早引入“大一统目录迁移”

原方案建议直接建立：

```text
services/agents/
├── registry.py
├── router.py
├── base.py
├── nlq_agent/
├── data_agent/
├── metrics_agent/
└── conversational/
```

这个方向可以保留，但**不应作为第一步的大范围搬迁**。原因：

- 现有 `llm/`、`sql_agent/`、`metrics_agent/`、`tableau/` 已在被 API 直接调用。
- 首页问答主链路当前集中在 `search.py`，而不在独立 agent adapter 中。
- 一次性重构会同时影响 API、审计、流式输出、conversation、权限控制，风险过高。

更稳妥的做法是：

- 第一步新增 **orchestration 层**，不搬迁原领域服务。
- 第二步把已有能力包装成 adapter。
- 第三步再把新入口逐步从 `search.py` 切到 `agents/router.py`。

### 3.2 没有区分“编排层”和“执行层”

当前平台里至少有三层职责：

1. **Domain Service**
   - 如 `llm/nlq_service.py`、`sql_agent/service.py`、`metrics_agent/registry.py`

2. **Agent Orchestrator**
   - 负责意图识别、路由、工具编排、上下文传递、trace、降级

3. **Task / Workflow Runtime**
   - 负责异步长流程、重试、定时触发、任务观测

原方案把这些混在了一起，容易出现两个误区：

- 把 `task_runtime` 误当成 Agent 引擎
- 把所有 Agent 都设计成同步 `run()`，无法承接长时分析任务

### 3.3 安全设计不够完整

原文档提到“模式选择”和“管理后台”，但没有覆盖以下高风险问题：

- 用户选择的 Agent 不等于有权使用该 Agent
- Agent 之间的内部调用需要服务身份认证
- Agent 不应信任上游传入的授权范围字段
- 多 Agent 编排会放大敏感字段泄漏、跨租户数据混用、Prompt Injection、工具滥用风险

### 3.4 缺少失败模型

Agent 系统不是“调用失败返回 500”这么简单，至少要定义：

- 意图识别失败
- 路由无命中
- Agent 不可用
- 下游工具超时
- 长任务中断
- 部分步骤成功、部分失败
- 流式输出中途断流
- 结果置信度过低

原文档没有把这些作为一等架构对象。

### 3.5 与现有平台能力衔接不足

当前代码库已经有这些可复用能力：

- `capability.audit`：能力调用审计
- `audit_runtime`：trace_id 继承与事件写入
- `conversations`：对话持久化与追问上下文
- `tasks`：Celery 调度、任务管理、手动触发、统计
- `events`：事件与通知

原文档没有把这些纳入 Agent 方案，会导致重复建设。

---

## 四、修订后的架构建议

### 4.1 目标定位

本次 Agent 架构的目标不应是“引入一个新目录”，而应是：

1. 建立统一的 **Agent Orchestration Layer**
2. 保持现有 Domain Service 目录基本不动
3. 为未来 `Data Agent` 留出标准接入位
4. 打通前端模式选择、后端路由、审计、任务、观测

### 4.2 推荐分层

```text
Frontend
  -> Home AskBar / Agent Mode Selector / Agent Admin UI

API Layer
  -> /api/agents/query              # 新统一入口（同步）
  -> /api/agents/stream             # 新统一流式入口
  -> /api/agents/tasks/*            # 长任务入口（异步）
  -> /api/agents/admin/*            # 注册表/路由/观测/配置

Agent Orchestration Layer
  -> registry
  -> router
  -> policy guard
  -> execution context builder
  -> tool gateway / adapter
  -> result normalizer

Domain Services
  -> llm/
  -> sql_agent/
  -> metrics_agent/
  -> tableau/
  -> knowledge_base/
  -> dqc/

Platform Runtime
  -> conversations
  -> capability.audit
  -> audit_runtime
  -> tasks / celery
  -> events / notifications
```

核心原则：

- **Agent 不替代 Domain Service**
- **Agent 是编排层，不是重写业务层**
- **异步任务和同步问答分开建模**

### 4.3 推荐目录结构

建议新增而不是迁移：

```text
backend/services/agents/
├── __init__.py
├── base.py                 # 抽象接口
├── context.py              # AgentExecutionContext / ActorContext
├── result.py               # AgentResult / ToolCallRecord / ErrorModel
├── registry.py             # Agent 注册表
├── router.py               # 路由与 fallback
├── policy.py               # 权限/能力/租户/敏感级别校验
├── observability.py        # trace / metrics / audit 封装
├── streaming.py            # SSE 事件标准化
├── adapters/
│   ├── nlq.py              # 适配 llm/nlq_service.py
│   ├── metrics.py          # 适配 metrics_agent/
│   ├── conversation.py     # 适配 conversations
│   ├── sql.py              # 适配 sql_agent/
│   └── knowledge.py        # 适配 knowledge_base/
└── implementations/
    ├── conversational.py   # 通用对话 agent
    ├── nlq.py              # 查询 agent
    ├── metrics.py          # 指标 agent
    └── data_agent.py       # 后续新增
```

不建议第一阶段做：

- 把 `backend/services/sql_agent/` 移到 `services/agents/sql_agent/`
- 把 `search.py` 一次性删除或大改
- 把 `task_runtime` 改造成 Agent 运行时

### 4.4 标准接口

推荐接口应覆盖同步、流式、长任务三种执行模式：

```python
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal


@dataclass
class ActorContext:
    user_id: int | None
    tenant_id: str | None
    role: str
    permissions: list[str] = field(default_factory=list)


@dataclass
class AgentExecutionContext:
    trace_id: str
    actor: ActorContext
    conversation_id: str | None = None
    selected_mode: str | None = None
    connection_id: int | None = None
    datasource_luid: str | None = None
    request_headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRecord:
    tool_name: str
    status: Literal["ok", "failed", "timeout", "denied"]
    latency_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    agent_name: str
    response_type: Literal["text", "number", "table", "chart", "report", "error"]
    answer: str
    data: Any = None
    confidence: float | None = None
    trace_id: str | None = None
    task_run_id: str | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    name: str
    display_name: str
    description: str
    supported_modes: list[str]
    supports_streaming: bool = False
    supports_async_task: bool = False

    async def run(self, query: str, ctx: AgentExecutionContext) -> AgentResult:
        raise NotImplementedError

    async def stream(self, query: str, ctx: AgentExecutionContext) -> AsyncIterator[dict]:
        raise NotImplementedError

    async def submit_task(self, query: str, ctx: AgentExecutionContext) -> AgentResult:
        raise NotImplementedError
```

相比原文档，新增了：

- `ActorContext`
- `AgentExecutionContext`
- `ToolCallRecord`
- `supports_streaming`
- `supports_async_task`

这能更好匹配当前平台的 SSE、对话历史和任务管理能力。

### 4.5 路由策略

路由优先级建议明确为：

1. 用户显式选择模式
2. 策略层校验是否允许该模式
3. 显式模式可用则直达对应 Agent
4. 否则进行轻量规则路由
5. 规则不确定时才调用 LLM 分类
6. 置信度低时回退到保守 Agent 或要求用户确认

```text
explicit mode
  -> policy check
  -> target agent

no explicit mode
  -> keyword/rule classifier
  -> if low confidence: llm classifier
  -> if still low confidence: conversational agent + switch suggestion
```

不建议：

- 每次都调用 LLM 进行意图识别
- 用户选了模式就完全绕过权限与策略校验
- 路由失败直接 500

### 4.6 前端交互建议

首页加模式选择是合理的，但建议改为“轻模式 + 默认自动”：

```text
[自动] [数据查询] [数据分析] [指标问答] [通用对话]
```

原因：

- 当前用户大概率不知道“Data Agent”和“Metrics Agent”的边界
- `自动` 模式可兼容当前首页入口习惯
- 对专家用户保留显式模式切换

建议返回的前端交互能力：

- 当前回答由哪个 Agent 处理
- trace_id
- 是否发生自动切换
- 低置信度提示
- 长任务时转成“后台运行”

### 4.7 后台管理建议

设置域新增 `Agent 管理` 是合理的，但内容建议拆成 4 个页签：

1. `注册表`
   - Agent 名称
   - 版本
   - 状态
   - 支持模式
   - 是否支持流式
   - 是否支持异步任务

2. `路由策略`
   - 模式到 Agent 的映射
   - 规则路由配置
   - LLM 分类开关
   - fallback 策略

3. `安全与治理`
   - 可用数据域
   - 工具白名单
   - 敏感字段策略
   - 结果发布策略

4. `观测与调试`
   - 调用量
   - 成功率
   - P95 延迟
   - 错误码分布
   - 最近 trace 查询

“训练任务”不建议作为 P0 的主概念。当前更现实的是：

- Prompt / policy / routing config 管理
- 语料与 few-shot 示例管理
- 任务日志与错误分析

---

## 五、关键缺失项补充

### 5.1 安全

Agent 方案至少应加入以下安全要求：

1. **权限不能由前端模式选择决定**
   - 前端只表达意图
   - 最终授权由服务端根据用户角色、连接权限、数据源权限决定

2. **Agent 间调用要有服务身份**
   - Data Agent 调 SQL Agent 必须走服务身份认证
   - 禁止仅凭请求体中的 `allowed_*` 作为授权依据

3. **租户隔离**
   - 所有 Agent 上下文都必须显式带 `tenant_id`
   - 会话、任务、审计、缓存都必须按租户隔离

4. **敏感字段与脱敏**
   - Agent 输出前必须走统一 redaction
   - sample rows、debug trace、tool logs 不得泄露敏感字段原值

5. **Prompt Injection / Tool Abuse 防护**
   - 工具调用必须走 allowlist
   - prompt 中不可直接暴露内部 secret、连接串、系统提示
   - 下游工具参数必须结构化校验

6. **IDOR / 越权访问**
   - conversation、task_run、analysis_session、query_log 必须按 user/tenant 过滤

### 5.2 错误处理

Agent 系统应定义统一错误模型：

```text
AGENT_ROUTE_NOT_FOUND
AGENT_POLICY_DENIED
AGENT_UNAVAILABLE
AGENT_TIMEOUT
AGENT_DOWNSTREAM_FAILED
AGENT_LOW_CONFIDENCE
AGENT_STREAM_ABORTED
AGENT_TASK_SUBMITTED
```

建议：

- 同步请求失败时返回结构化错误
- 流式请求失败时通过 SSE error event 返回
- 长任务失败时写入任务状态和审计事件
- 下游失败尽量映射为稳定错误码，而不是把原始异常直接暴露给前端

### 5.3 扩展性与性能

建议补充以下扩展设计：

1. **同步与异步分流**
   - `NLQ`、`Metrics QA` 以同步/流式为主
   - `Data Agent` 报告生成、主动洞察以异步任务为主

2. **超时分级**
   - 路由分类短超时
   - SQL 工具中超时
   - 长分析任务长超时 + checkpoint

3. **幂等**
   - 长任务必须有 `idempotency_key`
   - 重试不应重复生成会话与洞察

4. **缓存**
   - 意图分类可短时缓存
   - 指标定义、schema metadata、路由提示词可缓存
   - 结果缓存必须考虑用户/租户/权限边界

5. **配额与限流**
   - 按用户、Agent、工具类型分别限流
   - 对高成本 Agent 单独配额

6. **背压**
   - 并发高时优先降级到保守模式
   - Data Agent 长任务进入队列，不抢占实时问答通道

### 5.4 可观测性

建议明确以下 best practices：

- 每次 Agent 调用生成统一 `trace_id`
- 每个 tool call 记录 `latency_ms`、`status`、`error_code`
- 输出 `agent_name`、`route_reason`、`fallback_reason`
- 打通 `capability.audit` 与 `audit_runtime`
- 后续接入 metrics：QPS、成功率、P50/P95、工具失败率、路由命中率

### 5.5 数据与会话模型

建议不要在 P0 直接引入一套与 `conversations` 平行的全新会话体系，除非是 Data Agent 长任务确有需要。

推荐分层：

- 普通问答：继续复用 `conversations`
- 长分析任务：新增 `analysis_sessions`
- 二者通过 `conversation_id` / `task_run_id` / `trace_id` 关联

这样不会把全站对话系统一次性重构掉。

---

## 六、推荐实施顺序

### Phase 0：编排基座 + 可观测性

目标：

- 保留现有的 `search.py` 能力
- 新增 `services/agents/` 基座
- 新增统一入口 API
- 新增 Agent 可观测性核心表

交付：

- `services/agents/base.py`
- `services/agents/context.py`
- `services/agents/result.py`
- `services/agents/registry.py`
- `services/agents/router.py`
- `services/agents/implementations/conversational.py`
- `services/agents/implementations/nlq.py`
- `services/agents/implementations/metrics.py`
- 新 API：`/api/agents/query`、`/api/agents/stream`
- 数据库迁移：`bi_agent_runs`、`bi_agent_feedback`（MVP）

策略：

- `NlqAgent` 内部仍调用现有 `search.py` 或 `nlq_service`
- `MetricsAgent` 先接入已有 metrics service
- 首页先支持"自动 / 数据查询 / 指标问答 / 通用对话"
- 可观测性表在 Phase 0 一并创建，不留到后面补

### Phase 1：前端模式选择与管理后台

目标：

- 首页可显式选择模式
- 设置域新增 Agent 管理
- Agent 可观测性仪表盘上线

交付：

- 首页模式 selector
- Agent 注册表页
- 路由策略页
- **观测与调试页**（调用量 / 成功率 / P95 延迟 / trace 查询）

### Phase 2：Data Agent 最小版

目标：

- 先做“受控分析任务”，不要一步上完整 ReAct 14 工具

建议首版只支持：

- 归因分析
- 结构化输出
- 异步运行
- 结果回写 conversation

不建议首版就做：

- 主动洞察全量扫描
- 复杂多分支并行推理
- 用户可配置训练流程

### Phase 3：长任务与主动洞察

目标：

- Data Agent 与 `tasks/`、`events/`、`notifications` 打通
- 支持后台运行、回放、告警、发布

---

## 七、修订版规划文档

下面给出可替换原文档的修订版本。

---

# Agent 架构规划（修订版）

> 讨论时间：2026-04-24
> 目标：为 mulan-bi-platform 建立统一的 Agent 编排层，并为 Data Agent 落地预留可扩展架构

## 1. 现状分析

### 1.1 后端真实结构

当前与 Agent 相关的后端模块如下：

```text
backend/services/
├── llm/                  # LLM 路由与 NLQ 能力
├── sql_agent/            # SQL 执行与安全校验
├── metrics_agent/        # 指标定义、异常检测、一致性校验
├── tableau/              # Tableau/MCP 客户端与同步逻辑
├── task_runtime/         # 轻量 Task 状态机与数据结构
├── tasks/                # Celery 任务与任务管理
├── capability/           # 能力调用审计
├── audit_runtime/        # trace / audit runtime
├── events/               # 事件与通知
├── knowledge_base/       # 知识库与 embedding / retrieval
├── dqc/                  # 数据质量相关服务
└── mcp/                  # MCP Server ORM 模型
```

说明：

- `data_agent/` 目前不存在。
- `sql_agent/`、`metrics_agent/`、`llm/nlq_service.py` 已形成事实上的 Agent 能力，但还没有统一编排层。

### 1.2 前端真实入口

当前前端采用 5 域菜单结构：

- 看板（`/`）
- 资产（`/assets/*`）
- 实验室（`/dev/*` 与占位路由）
- 治理（`/governance/*`）
- 设置（`/system/*`）

首页仍是用户最自然的 Agent 交互入口。当前 AskBar 已具备：

- SSE 流式能力
- 连接选择
- conversation 上下文
- mock/real backend 切换能力

### 1.3 当前问答链路

```text
Home AskBar
  -> GET /api/chat/stream
  -> 内部转发 POST /api/search/query
  -> search.py 负责：
       - meta intent 识别
       - 数据源路由
       - NLQ
       - SQL 查询
       - 返回结构化结果
```

现状结论：

- 平台已经具备“幕后 Agent”能力
- 但还没有统一的 Agent 注册、路由、策略治理和管理能力

## 2. 核心问题

当前不足主要有 6 点：

1. 缺少统一 Agent 编排入口，能力散落在 `search.py`、`llm/`、`metrics_agent/` 等处
2. Data Agent 仅有 Spec，没有实现
3. 首页没有显式模式切换，用户无法理解“当前由谁回答”
4. Agent 无统一审计与观测模型
5. 长时分析任务没有纳入 Agent 设计
6. 缺少统一的安全治理、策略控制与错误模型

## 3. 架构目标

本次架构规划目标不是重写现有服务，而是建立一层 **Agent Orchestration Layer**：

- 统一注册已有和未来 Agent
- 提供统一的同步、流式、异步三种调用模式
- 把路由、权限、审计、fallback、可观测性标准化
- 为 Data Agent 接入提供稳定基座

## 4. 总体架构

### 4.1 分层模型

```text
Frontend
  -> Home AskBar / Agent Mode Selector / Agent Admin

API Layer
  -> /api/agents/query
  -> /api/agents/stream
  -> /api/agents/tasks/*
  -> /api/agents/admin/*

Agent Orchestration Layer
  -> registry
  -> router
  -> policy guard
  -> context builder
  -> result normalizer
  -> streaming adapter

Domain Services
  -> llm
  -> sql_agent
  -> metrics_agent
  -> tableau
  -> knowledge_base
  -> dqc

Platform Runtime
  -> conversations
  -> capability.audit
  -> audit_runtime
  -> tasks / celery
  -> events
```

### 4.2 目录建议

```text
backend/services/agents/
├── base.py
├── context.py
├── result.py
├── registry.py
├── router.py
├── policy.py
├── observability.py
├── streaming.py
├── adapters/
│   ├── nlq.py
│   ├── metrics.py
│   ├── sql.py
│   ├── conversation.py
│   └── knowledge.py
└── implementations/
    ├── conversational.py
    ├── nlq.py
    ├── metrics.py
    └── data_agent.py
```

原则：

- 先新增，不搬迁既有领域服务
- 通过 adapter 接入现有能力
- `search.py` 先桥接，后逐步下沉到 `agents/router.py`

## 5. Agent 标准接口

建议统一建模为：

- `ActorContext`
- `AgentExecutionContext`
- `AgentResult`
- `ToolCallRecord`

接口需要支持：

- 同步执行
- 流式执行
- 异步长任务提交

这比只定义 `run()` / `run_async()` 更适合当前平台。

## 6. 路由设计

### 6.1 路由优先级

1. 用户显式模式
2. 服务端策略校验
3. 规则路由
4. LLM 分类
5. fallback 到保守模式或请求用户确认

### 6.2 模式建议

首页建议支持：

- 自动
- 数据查询
- 数据分析
- 指标问答
- 通用对话

映射关系建议为：

| 模式 | Agent | 执行方式 |
|------|------|---------|
| 自动 | Router 决定 | 同步或流式 |
| 数据查询 | NlqAgent | 同步或流式 |
| 数据分析 | DataAgent | 优先异步 |
| 指标问答 | MetricsAgent | 同步 |
| 通用对话 | ConversationalAgent | 流式 |

## 7. 与现有模块的衔接

### 7.1 可复用资产

| 资产 | 现状 | 建议复用方式 |
|------|------|-------------|
| `llm/nlq_service.py` | 已实现 | 封装为 `NlqAgent` 能力核心 |
| `sql_agent/` | 已实现 | 作为 `NlqAgent` / `DataAgent` 的受控执行器 |
| `metrics_agent/` | 已实现 | 封装为 `MetricsAgent` |
| `frontend/src/api/ask_data_contract.ts` | 已实现 | 作为 Agent SSE 契约基础 |
| `conversations.py` | 已实现 | 继续承接普通问答上下文 |
| `capability.audit` | 已实现 | 复用为 Agent 调用审计底座 |
| `audit_runtime` | 已实现 | 复用为 trace / audit event 基础 |
| `tasks/` | 已实现 | 承接 Data Agent 长任务 |

### 7.2 不建议复用为 Agent 引擎的模块

- `task_runtime/`
  - 当前只适合作为轻量状态机或兼容模型
  - 不应直接承担 ReAct/Tool orchestration

## 8. 安全与治理要求

### 8.1 授权原则

- 用户选择 Agent 模式不等于自动获得权限
- 连接、数据源、指标、敏感字段的最终授权必须在服务端判定
- Agent 间调用必须使用服务身份认证

### 8.2 数据保护

- 所有 trace、sample rows、tool logs 必须支持脱敏
- 不得在 prompt、日志、调试输出中暴露 secret
- 会话、任务、审计、缓存都必须按租户隔离

### 8.3 工具安全

- 工具采用 allowlist
- 参数必须结构化校验
- 高风险工具需策略门控

## 9. 错误处理与降级

统一错误码建议包括：

- `AGENT_ROUTE_NOT_FOUND`
- `AGENT_POLICY_DENIED`
- `AGENT_UNAVAILABLE`
- `AGENT_TIMEOUT`
- `AGENT_DOWNSTREAM_FAILED`
- `AGENT_LOW_CONFIDENCE`
- `AGENT_STREAM_ABORTED`

降级策略：

- 路由低置信度时回退到通用对话或提示切换模式
- Data Agent 超时时转为后台任务
- 下游工具失败时返回结构化错误，而不是原始异常

## 10. 可扩展性设计

### 10.1 同步 / 异步分流

- `NlqAgent`、`MetricsAgent`：以同步/流式为主
- `DataAgent`：以异步任务为主

### 10.2 可靠性

- 长任务要有 `idempotency_key`
- 关键步骤要支持 checkpoint
- 重试不应重复生成洞察与报告

### 10.3 性能

- 意图分类短缓存
- schema/metric metadata 缓存
- 高成本 Agent 单独限流与配额

## 10b. Agent 可观测性与追踪模块

### 10b.1 必要性结论

**必须有专门的 Agent 可观测层**，但不是重建，而是在复用现有审计/事件基础设施之上扩展。

现有分散模块不足以支撑：

- 用户想知道"这个问题是哪个 Agent 回答的"
- 运维想知道"今天各个 Agent 的成功率是多少"
- 开发者想知道"为什么这个查询走了错误的路由"
- 产品想知道"Data Agent 的用户评分是多少"
- 未来 A/B 测试不同 Agent 版本需要分组统计

### 10b.2 数据模型

推荐新建 **3 张核心表**，不建大一统 mega-table：

```sql
-- bi_agent_runs：每次 Agent 调用的主记录
CREATE TABLE bi_agent_runs (
  id              BIGSERIAL PRIMARY KEY,
  trace_id        VARCHAR(64) UNIQUE NOT NULL,  -- 全链路追踪 ID
  agent_name      VARCHAR(64) NOT NULL,          -- nlq / metrics / data / conversational
  agent_version   VARCHAR(32),                   -- 支持 A/B 版本追踪
  mode            VARCHAR(32),                   -- auto / nlq / data / metrics / conversational
  user_id         BIGINT,
  conversation_id VARCHAR(64),

  -- 请求上下文
  query_preview   VARCHAR(256),                  -- 脱敏后的 query 前缀
  selected_mode    VARCHAR(32),                   -- 用户显式选择（若有）
  intent_detected VARCHAR(64),                   -- 系统识别出的意图
  intent_confidence FLOAT,                       -- 置信度 0~1

  -- 执行结果
  status          VARCHAR(16) NOT NULL,          -- success / failed / timeout / partial
  response_type   VARCHAR(16),                   -- text / number / table / chart / error
  latency_ms      INTEGER,
  fallback_occurred BOOLEAN DEFAULT FALSE,
  fallback_reason VARCHAR(128),

  -- 实验标记（支持 A/B testing）
  experiment_key  VARCHAR(64),
  variant_key     VARCHAR(32),

  -- 可观测性
  created_at      TIMESTAMP NOT NULL DEFAULT now()
);

-- bi_agent_run_steps：每个 Agent 内部的 tool call 记录
CREATE TABLE bi_agent_run_steps (
  id              BIGSERIAL PRIMARY KEY,
  trace_id        VARCHAR(64) NOT NULL REFERENCES bi_agent_runs(trace_id),
  step_index      INTEGER NOT NULL,
  step_name       VARCHAR(64),                   -- e.g. intent_classify / sql_execute / chart_render
  tool_name       VARCHAR(64),                   -- 实际调用的工具名
  status          VARCHAR(16),                   -- ok / failed / timeout / denied
  latency_ms      INTEGER,
  error_code      VARCHAR(32),
  metadata        JSONB,                         -- 工具返回摘要（不含敏感数据）

  -- 与平台现有日志的 linkage
  external_ref_type VARCHAR(32),                 -- query_log / task_run / analysis_session
  external_ref_id   BIGINT,
  created_at      TIMESTAMP NOT NULL DEFAULT now()
);

-- bi_agent_feedback：用户反馈（点踩/点赞/评分）
CREATE TABLE bi_agent_feedback (
  id              BIGSERIAL PRIMARY KEY,
  trace_id        VARCHAR(64) REFERENCES bi_agent_runs(trace_id),
  user_id         BIGINT,
  conversation_id VARCHAR(64),

  -- 反馈类型
  feedback_type   VARCHAR(16) NOT NULL,         -- thumb / rating / label
  thumb_vote      VARCHAR(4),                    -- up / down（thumb 时）
  rating          INTEGER,                       -- 1~5（rating 时）
  label           VARCHAR(64),                    -- judge_eval 等标签

  -- 反馈内容（可选的自由文本）
  comment         TEXT,
  reason          VARCHAR(128),                  -- 用户选择 thumb down 时的原因标签

  created_at      TIMESTAMP NOT NULL DEFAULT now()
);
```

### 10b.3 与现有系统的关系

| 现有系统 | 关系 | 复用方式 |
|---------|------|---------|
| `audit_runtime` | trace_id 基础 | 复用 trace_id 生成逻辑，不新建审计体系 |
| `events` | Agent 事件通知 bridge | Agent 内部事件通过 events/ 发布 |
| `conversations` | 上下文关联 | 加 `agent_mode` 扩展字段关联 trace_id |
| `tasks/` | Data Agent 长任务 | task_run.id 写入 `external_ref_id` |
| `message_feedback` | 已有反馈表 | 保持兼容，新增写入同时写 `bi_agent_feedback` |
| `query_feedback` | 已有反馈表 | 同上 |

**关键原则**：
- ❌ 不复制 full SQL、full prompt、reasoning trace 到新表（数据量爆炸）
- ❌ 不替换现有 `analysis_sessions` 等 Data Agent 内部表
- ✅ 只写 linkage 和脱敏摘要，原表作为 source of truth
- ✅ `trace_id` 是贯穿各表的唯一 key

### 10b.4 使用场景覆盖

```
使用分析（Usage Analytics）
  -> SELECT agent_name, COUNT(*), AVG(latency_ms)
     FROM bi_agent_runs GROUP BY agent_name

质量监控（Quality Monitoring）
  -> SELECT agent_name, status, COUNT(*)
     FROM bi_agent_runs
     JOIN bi_agent_feedback USING (trace_id)
     GROUP BY agent_name, status

A/B Testing
  -> SELECT variant_key, AVG(latency_ms), SUM(thumb_vote='up')
     FROM bi_agent_runs
     JOIN bi_agent_feedback USING (trace_id)
     WHERE experiment_key = 'nlq-v2'
     GROUP BY variant_key

深度调试（Deep Debugging）
  -> SELECT * FROM bi_agent_run_steps
     WHERE trace_id = 'xxx'
     ORDER BY step_index
     -> 再通过 external_ref_* 跳转到原域日志
```

### 10b.5 MVP 推荐

最小可行可观测栈只需两张表：

```
必需（Phase 0 必须）：
- bi_agent_runs（含 trace_id / agent_name / latency_ms / status / user_id）
- bi_agent_feedback（thumb up/down，关联 trace_id）

可选（Phase 1）：
- bi_agent_run_steps（debug 用，记录 tool_calls）
- per-agent 聚合 metrics（按 hour/day 滚动）
```

## 11. 前端方案

### 11.1 首页

在 AskBar 上方增加模式 selector：

```text
[自动] [数据查询] [数据分析] [指标问答] [通用对话]
```

前端显示：

- 当前 Agent
- trace_id
- 是否发生 fallback
- 长任务状态

### 11.2 设置域

新增 `Agent 管理`：

- 注册表
- 路由策略
- 安全治理
- 观测与调试

## 12. 实施顺序

### Phase 0：编排基座

- 新增 `services/agents/`
- 新增 `/api/agents/query`、`/api/agents/stream`
- 接入 `NlqAgent`、`MetricsAgent`、`ConversationalAgent`
- 复用现有审计、trace、conversation

### Phase 1：首页模式与后台管理

- 首页增加模式选择
- 设置域增加 Agent 管理页面

### Phase 2：Data Agent MVP

- 先实现受控的分析任务
- 优先异步
- 与 `tasks/`、`events/`、`conversations` 打通

### Phase 3：主动洞察与高级编排

- 主动扫描
- 发布与通知
- 更复杂的多步推理与并行验证

## 13. 最终建议

推荐采用 **“基座先行，渐进接入”** 方案：

- 不做一次性重构
- 先建立 Agent 编排层
- 先接入已有 `NLQ / Metrics / Conversational`
- 再实现 `Data Agent`

这是当前代码基线下风险最低、收益最高、最符合平台演进路径的方案。
