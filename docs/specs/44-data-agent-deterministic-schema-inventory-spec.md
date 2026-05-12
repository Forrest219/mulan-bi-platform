# Data Agent 确定性 Schema Inventory Skill 技术规格书

> 版本：v0.1 | 状态：Ready for Implementation | 日期：2026-05-12 | 关联模块：Data Agent / 首页问答

---

## 1. 概述

### 1.1 目的

将“有哪些数据源 / 有哪些表 / 当前连接包含什么”等 schema inventory 类问题从 LLM ReAct 自由生成链路中剥离，改为确定性 skill 路由、确定性工具调用、确定性结果归一化、确定性 Markdown 渲染和确定性校验，降低回答不稳定、计数不准确、资产遗漏和幻觉风险。

### 1.2 背景问题

当前首页问答中，用户询问：

```text
你有哪些数据源？
```

实际执行链路为：

```text
POST /api/agent/stream
-> ReActEngine 第 1 轮 LLM thinking
-> LLM 选择 schema 工具
-> SchemaTool 返回 Tableau 资产列表
-> ReActEngine 第 2 轮 LLM thinking
-> LLM 整理最终回答
```

该链路中 schema 查询结果本身是结构化且确定的，但最终分类、计数和展示仍由 LLM 自由生成，存在以下风险：

- 同一工具结果多次生成的 Markdown 不完全一致。
- 统计可能出现模糊表达，例如 `26+ 个视图`。
- LLM 可能补充工具结果中不存在的“建议表”或业务判断。
- 工具选择依赖 LLM thinking，关键词类问题仍可能误走 `query` 或其他工具。

### 1.3 范围

**包含：**

- 新增 deterministic schema inventory skill。
- 新增 schema inventory 意图识别规则。
- 对 `POST /api/agent/stream` 增加确定性分支。
- 复用现有 `schema` 工具查询 Tableau 资产。
- 对 `schema` 工具结果做归一化、排序、计数、渲染、校验。
- 复用现有 SSE 协议、会话消息表和可观测性表。
- 增加 coder 可执行任务清单和 tester 可验收测试清单。

**不包含：**

- 不替换整个 ReAct 引擎。
- 不改造趋势、对比、汇总、问数查询类问题。
- 不新增前端页面。
- 不新增数据库表。
- 不引入 Redis 或新的缓存层。
- 不改变 Tableau 资产同步逻辑。

### 1.4 关联文档

| 文档 | 路径 | 关系 |
|------|------|------|
| Data Agent 架构 | `docs/specs/36-data-agent-architecture-spec.md` | 上游架构，定义 ReAct、SSE、会话、可观测性 |
| Data Agent | `docs/specs/28-data-agent-spec.md` | Agent 能力边界 |
| Agents Skills Center | `docs/specs/agents_skills.md` | 技能中心概念；本 spec 不修改 DB 技能版本模型 |
| Tableau MCP V1 | `docs/specs/07-tableau-mcp-v1-spec.md` | Tableau 资产数据来源 |
| API 约定 | `docs/specs/02-api-conventions.md` | API 错误格式、认证约定 |
| 测试规范 | `docs/TESTING.md` | tester 验收规范 |

---

## 2. 现状审计

### 2.1 当前相关代码

| 文件 | 当前职责 |
|------|----------|
| `backend/app/api/agent.py` | `/api/agent/stream` SSE 入口，创建会话、保存用户消息、调用 fast path 或 `run_agent` |
| `backend/services/data_agent/runner.py` | 包装 ReAct 引擎，记录 `bi_agent_runs` / `bi_agent_steps`，保存 assistant 消息 |
| `backend/services/data_agent/engine.py` | ReAct 循环：thinking -> tool_call -> tool_result -> answer |
| `backend/services/data_agent/tools/schema_tool.py` | `schema` 工具；Tableau 连接下查询 `TableauAsset` / `TableauDatasourceField` |
| `backend/services/data_agent/session.py` | `SessionManager.persist_message()` 保存 `agent_conversation_messages` |
| `backend/services/data_agent/prompts.py` | 约束 LLM：schema 工具仅在用户明确询问表/字段时调用 |

### 2.2 当前真实事件序列

对于 conversation `dac681b4-0cd6-4032-8cee-f032def2843d`，实际落库步骤为：

```text
1. thinking
   用户询问有哪些数据源，应使用 schema 工具查询连接下的数据源信息。

2. tool_call
   tool = schema
   params = {}

3. tool_result
   schema 返回 Tableau Server 的资产列表。

4. thinking
   schema 已返回完整结果，可以按项目分类整理后直接回答。

5. answer
   LLM 输出最终 Markdown。
```

### 2.3 不稳定环节

| 环节 | 风险 | 本 spec 处理方式 |
|------|------|----------------|
| LLM 选择工具 | 可能误选 `query` 或绕过工具 | 用规则命中 `schema_inventory` |
| LLM 二次整理 | 计数、分类、排序不稳定 | 用归一化器 + 模板渲染 |
| LLM 生成补充建议 | 可能新增工具结果外内容 | 渲染模板禁止引入外部信息 |
| 回归测试 | 难断言自然语言完全一致 | 对 normalized payload 和模板片段做确定性断言 |

---

## 3. 目标架构

### 3.1 目标链路

```text
POST /api/agent/stream
-> 权限校验 / connection 校验
-> 保存 user message
-> DeterministicIntentRouter 命中 schema_inventory
-> SchemaInventorySkill 调用 registry.get("schema")
-> normalize_schema_inventory()
-> render_schema_inventory_markdown()
-> validate_schema_inventory_payload()
-> SSE 输出 token + done
-> persist assistant message
-> 写入 bi_agent_runs / bi_agent_steps
```

### 3.2 与 ReAct 的关系

schema inventory skill 是 ReAct 前置确定性分支：

- 命中 `schema_inventory` 时，不调用 LLM。
- 未命中时，保持现有 fast path / ReAct 逻辑不变。
- 工具仍复用 `ToolRegistry` 中已注册的 `schema` 工具，不绕开权限上下文。

### 3.3 建议目录结构

```text
backend/services/data_agent/deterministic/
  __init__.py
  intent.py
  schema_inventory.py
```

| 文件 | 职责 |
|------|------|
| `intent.py` | 纯函数：识别 deterministic intent |
| `schema_inventory.py` | skill 主体：工具调用、归一化、渲染、校验 |
| `__init__.py` | 导出稳定 API |

---

## 4. 数据模型

### 4.1 新增表

本 spec P0 不新增数据库表，不需要 Alembic 迁移。

### 4.2 复用表

| 表 | 写入要求 |
|----|----------|
| `agent_conversations` | 复用现有会话 |
| `agent_conversation_messages` | 保存用户消息和确定性 assistant 回答 |
| `bi_agent_runs` | 每次 deterministic skill 执行仍创建 run |
| `bi_agent_steps` | 记录 deterministic thinking、tool_call、tool_result、answer |

### 4.3 assistant message 字段约定

| 字段 | 值 |
|------|----|
| `role` | `assistant` |
| `content` | 确定性 Markdown |
| `response_type` | `schema_inventory` |
| `response_data` | 归一化后的 schema inventory payload |
| `tools_used` | `["schema"]` |
| `steps_count` | `1` |
| `sources_count` | `1`，若有 connection |
| `top_sources` | `[connection_name]`，例如 `["Tableau Server"]` |

`response_type = "schema_inventory"` 长度为 16，满足现有 `String(16)` 字段。

---

## 5. API 与 SSE 契约

### 5.1 API 端点

不新增 API，继续使用：

```text
POST /api/agent/stream
```

请求 schema 不变：

```json
{
  "question": "你有哪些数据源？",
  "conversation_id": "dac681b4-0cd6-4032-8cee-f032def2843d",
  "connection_id": 1
}
```

### 5.2 SSE 事件序列

命中 deterministic schema inventory 后，事件顺序必须稳定：

```text
metadata
thinking
tool_call
tool_result
token...
done
```

deterministic answer 虽然一次性生成完整 Markdown，但仍必须通过 `token` 事件分片输出，以保持与现有前端拼接逻辑兼容。

分片规则：

- 必须输出至少一个 `token` 事件，除非发生 error。
- 推荐按行分片；若单行过长，则按 20-50 个字符切片。
- 不允许只发送 `done` 而不发送 token。
- 是否增加短暂 sleep 由实现决定；如增加延迟，必须设置总耗时上限，避免大列表阻塞响应。

### 5.3 `thinking` 事件

`thinking` 事件不是 LLM 输出，而是用户可见的业务进度说明。禁止在用户可见文案中暴露 `schema_inventory`、deterministic branch、skill 命中等技术术语。

```json
{
  "type": "thinking",
  "content": "正在盘点当前连接 Tableau Server 下的可用数据源与视图资产..."
}
```

技术诊断信息必须写入日志或 `bi_agent_steps.content`，例如：

```text
[DETERMINISTIC_SKILL] intent=schema_inventory trace=t-xxx connection_id=1
```

### 5.4 `tool_call` 事件

```json
{
  "type": "tool_call",
  "tool": "schema",
  "params": {}
}
```

### 5.5 `tool_result` 事件

`summary` 只返回安全摘要，避免 SSE 中发送过长内容：

```json
{
  "type": "tool_result",
  "tool": "schema",
  "summary": "Tableau Server: datasource=24, view=26"
}
```

### 5.6 `done` 事件

```json
{
  "type": "done",
  "answer": "...确定性 Markdown...",
  "trace_id": "t-xxxx",
  "run_id": "...",
  "tools_used": ["schema"],
  "response_type": "schema_inventory",
  "response_data": {
    "connection": {
      "id": 1,
      "name": "Tableau Server",
      "type": "tableau"
    },
    "summary": {
      "datasource": 24,
      "view": 26
    },
    "groups": [
      {
        "asset_type": "datasource",
        "label": "数据源",
        "total_count": 24,
        "shown_count": 24,
        "omitted_count": 0,
        "projects": []
      }
    ]
  },
  "steps_count": 1,
  "execution_time_ms": 1234,
  "sources_count": 1,
  "top_sources": ["Tableau Server"]
}
```

---

## 6. 确定性业务逻辑

### 6.1 Intent 命中规则

新增纯函数：

```python
def detect_deterministic_intent(question: str, connection_type: str | None) -> str | None:
    ...
```

P0 只返回：

```text
schema_inventory
None
```

命中条件：

- 问题包含 schema inventory 关键词。
- 问题不是趋势、汇总、计算、排序、TopN、同比环比等分析类问题。
- 问题不包含复杂筛选、排除、排序、推荐、引用上一轮结果等附加条件。
- 当前请求已有 `connection_id`，或后端可解析出有效连接。

中文关键词：

```text
有哪些数据源
有什么数据源
有哪些表
有什么表
有哪些字段
当前连接
可用数据源
数据源列表
表列表
字段列表
schema
```

英文关键词：

```text
data sources
datasets
tables
fields
schema
available sources
```

排除关键词：

```text
销售额
收入
订单数
趋势
同比
环比
排名
top
增长
下降
分析
对比
汇总
统计
只
仅
过滤
包含
相关
匹配
名字里
字样
项目为
属于
排除
不要
推荐
第二个
```

复杂条件 fallback 规则：

- 如果问题包含“只 / 仅 / 过滤 / 包含 / 相关 / 匹配 / 名字里 / 字样 / 项目为 / 属于 / 排除 / 不要 / 推荐 / 第二个”等条件词，不命中 deterministic path，交给 ReAct 处理。
- 不使用固定字符长度作为唯一判断依据；中文自然问句可能较长，不能因长度本身误判。
- P0 deterministic path 只处理“列出全部当前连接资产”的简单 inventory 问题。

示例：

| 用户问题 | 结果 |
|----------|------|
| 你有哪些数据源？ | `schema_inventory` |
| 当前连接有哪些表？ | `schema_inventory` |
| orders 表有哪些字段？ | P1 支持；P0 可继续走 ReAct |
| 当前连接有哪些包含“销售”字样的数据源？ | `None` |
| 推荐刚才列表里的第二个数据源 | `None` |
| 最近 7 天销售额是多少？ | `None` |
| 按月份对比订单数 | `None` |

### 6.2 工具调用规则

命中 `schema_inventory` 后固定调用：

```python
tool = registry.get("schema")
result = await tool.execute(params={}, context=context)
```

禁止：

- 禁止调用 LLM 判断工具。
- 禁止直接查询 `TableauAsset` 绕过 `SchemaTool`。
- 禁止在 skill 内拼 SQL 查询业务指标。

### 6.3 归一化函数

新增纯函数：

```python
def normalize_schema_inventory(tool_data: dict) -> dict:
    ...
```

输入为 `SchemaTool` 返回的 `data`：

```json
{
  "connection_id": 1,
  "datasource_name": "Tableau Server",
  "db_type": "tableau",
  "tables": [
    {
      "name": "orders-订单明细表",
      "type": "datasource",
      "project": "数据源",
      "web_url": null
    }
  ],
  "asset_summary": {
    "datasource": 24,
    "view": 26
  }
}
```

输出：

```json
{
  "connection": {
    "id": 1,
    "name": "Tableau Server",
    "type": "tableau"
  },
  "summary": {
    "datasource": 24,
    "view": 26
  },
  "groups": [
    {
      "asset_type": "datasource",
      "label": "数据源",
      "total_count": 24,
      "shown_count": 24,
      "omitted_count": 0,
      "projects": [
        {
          "project": "数据源",
          "total_count": 8,
          "shown_count": 8,
          "omitted_count": 0,
          "items": []
        }
      ]
    }
  ]
}
```

排序规则必须稳定：

1. `asset_type` 固定顺序：`datasource` -> `view` -> `workbook` -> `flow` -> 其他。
2. `project` 按字符串升序，空项目归为 `未分组`。
3. `name` 按 `casefold()` 升序。

### 6.4 Markdown 渲染函数

新增纯函数：

```python
def render_schema_inventory_markdown(payload: dict) -> str:
    ...
```

渲染模板：

```markdown
当前连接 **{connection.name}（ID={connection.id}）** 包含以下资产：

## 统计汇总

| 类型 | 数量 |
|---|---:|
| 数据源 datasource | 24 |
| 视图 view | 26 |

## 数据源 datasource

### 项目：数据源（8）

| 名称 | 项目 | 类型 |
|---|---|---|
| orders-订单明细表 | 数据源 | datasource |

如需查看某个具体数据源的字段结构，请继续指定数据源名称。
```

硬性要求：

- 数量必须是整数，禁止使用 `+`、`约`、`多个` 等模糊表达。
- 资产名称只能来自 normalized payload。
- 不输出“常用核心表”“推荐表”等 LLM 推断内容。
- 不调用 LLM 改写 Markdown。
- 同一 payload 多次渲染必须字节级一致。

### 6.5 渲染数量上限

P0 默认每个 asset_type 最多展示 100 条。截断只作用于“展示层 payload”，不得改变原始总数。

字段语义：

| 字段 | 含义 |
|------|------|
| `total_count` | 截断前真实总数 |
| `shown_count` | 当前 response 中实际展示数量 |
| `omitted_count` | `total_count - shown_count` |
| `items` | 当前 response 中实际展示的资产 |

如果超过 100 条：

```markdown
（其余 37 个已省略，可通过筛选项目或指定名称继续查看。）
```

省略数量必须精确计算。

### 6.6 校验函数

新增纯函数：

```python
def validate_schema_inventory_payload(payload: dict) -> None:
    ...
```

校验规则：

- `summary[asset_type] == group.total_count`。
- `group.shown_count == sum(project.shown_count)`。
- `group.omitted_count == group.total_count - group.shown_count`。
- 每个 project 的 `shown_count == len(items)`。
- 每个 project 的 `omitted_count == project.total_count - project.shown_count`。
- 当任一 `omitted_count > 0` 时，Markdown 必须出现对应省略提示。
- 所有 item 的 `name` 非空。
- 所有 item 的 `type` 与所在 group 一致。
- `connection.id` 必须存在。

校验失败时：

- 不返回半成品答案。
- 产生 `error` SSE。
- `bi_agent_runs.status = failed`。
- 错误码复用 `AGENT_003`，message 为 `Schema inventory validation failed`。

---

## 7. 可观测性

### 7.1 Run 记录

命中 deterministic skill 时仍写入 `bi_agent_runs`：

| 字段 | 值 |
|------|----|
| `question` | 用户原始问题 |
| `status` | `completed` 或 `failed` |
| `steps_count` | `1` |
| `tools_used` | `["schema"]` |
| `response_type` | `schema_inventory` |
| `execution_time_ms` | 总耗时 |

### 7.2 Step 记录

必须写入以下步骤：

| step_number | step_type | 内容 |
|-------------|-----------|------|
| 1 | `thinking` | 确定性路由说明 |
| 2 | `tool_call` | `tool_name=schema`, `tool_params={}` |
| 3 | `tool_result` | 安全摘要，不超过 500 字 |
| 4 | `answer` | Markdown 前 500 字 |

`steps_count` 仍表示工具调用次数，因此为 `1`。

### 7.3 日志

新增 INFO 日志：

```text
[DETERMINISTIC_SKILL] intent=schema_inventory trace=t-xxx connection_id=1
[DETERMINISTIC_SKILL_DONE] intent=schema_inventory trace=t-xxx assets=50 elapsed_ms=1234
```

禁止在日志中打印完整资产列表。

---

## 8. 安全与权限

### 8.1 权限继承

必须复用 `/api/agent/stream` 当前权限链：

- `get_current_user`
- `_require_agent_role`
- `_resolve_agent_connection_id`
- `_validate_connection_access`

### 8.2 数据边界

- 只展示当前用户有权访问的 `connection_id` 下资产。
- 只展示 `SchemaTool` 返回内容。
- 不展示 `is_deleted = true` 资产。
- 不展示凭证、token、secret。

### 8.3 LLM 信任边界

命中 schema inventory 后禁止调用 LLM，因此：

- schema inventory 工具结果不会进入 LLM prompt。
- 最终回答不受 LLM 随机性影响。
- 用户输入只用于规则识别，不作为 SQL 片段拼接。

### 8.4 多轮上下文加载

当后续问题回到 ReAct 链路时，如果历史消息包含 `response_type = "schema_inventory"`，history builder 不应只让 LLM 从 Markdown 表格中反解析资产列表。

要求：

- 优先注入 compact structured context，而不是完整 `response_data`。
- compact context 来源于 `agent_conversation_messages.response_data`。
- 注入内容必须有 token 上限，P0 默认最多注入用户可见的前 100 条资产。
- 不注入 `web_url` 等可能较长且对语义引用无必要的字段，除非后续问题明确要求链接。

建议注入结构：

```json
{
  "type": "schema_inventory",
  "connection_id": 1,
  "connection_name": "Tableau Server",
  "summary": {"datasource": 24, "view": 26},
  "visible_items": [
    {"index": 1, "name": "orders-订单明细表", "type": "datasource", "project": "数据源"}
  ]
}
```

如果用户问“推荐刚才列表里的第二个数据源”，P0 不由 deterministic intent 处理；但 ReAct 应能通过上述 compact context 理解“第二个数据源”的引用。

---

## 9. 实施计划

### P0：Tableau 数据源/视图 Inventory 确定性回答

目标：解决首页“你有哪些数据源？”类问题的不稳定回答。

建议改动：

| # | 文件 | 动作 |
|---|------|------|
| 1 | `backend/services/data_agent/deterministic/intent.py` | 新增 intent 识别纯函数 |
| 2 | `backend/services/data_agent/deterministic/schema_inventory.py` | 新增 skill、normalize、render、validate |
| 3 | `backend/app/api/agent.py` | 在 fast path / ReAct 前增加 deterministic branch |
| 4 | `backend/tests/services/data_agent/test_schema_inventory_skill.py` | 新增纯函数单测 |
| 5 | `backend/tests/test_agent_schema_inventory_api.py` | 新增 API/SSE 集成测试 |

### P1：字段级 Inventory

支持：

```text
orders 表有哪些字段？
这个数据源字段结构是什么？
```

要求：

- 可解析 `table_name`。
- 调用 `schema` 工具时传入 `{"table_name": "..."}`。
- 字段列表也走 deterministic renderer。

### P2：前端结构化渲染

将 `response_data.groups` 用原生表格/折叠组件展示，Markdown 作为 fallback。

---

## 10. 验收标准

| AC 编号 | 验收内容 | 测试类型 |
|---------|----------|----------|
| AC-44-01 | 用户问“你有哪些数据源？”且带有效 `connection_id` 时，后端不调用 LLM | 单元 / API |
| AC-44-02 | 命中后固定调用 `schema` 工具一次，参数为 `{}` | 单元 / API |
| AC-44-03 | SSE 顺序为 `metadata -> thinking -> tool_call -> tool_result -> token... -> done` | API |
| AC-44-04 | `done.response_type == "schema_inventory"`，`tools_used == ["schema"]`，`steps_count == 1` | API |
| AC-44-05 | Markdown 中统计数量为精确整数，禁止出现 `+`、`约`、`多个` 等模糊计数词 | 单元 |
| AC-44-06 | 同一 normalized payload 连续渲染 3 次，输出完全一致 | 单元 |
| AC-44-07 | 回答中出现的资产名称全部来自 schema 工具结果 | 单元 |
| AC-44-08 | 无权限用户访问不属于自己的 connection，仍返回原有权限错误，不进入 deterministic skill | API |
| AC-44-09 | 非 inventory 问题，例如“最近 7 天销售额是多少”，不命中 deterministic branch，继续走现有路径 | 单元 |
| AC-44-10 | assistant 消息落库到 `agent_conversation_messages`，字段符合 §4.3 | 集成 |
| AC-44-11 | `bi_agent_runs` / `bi_agent_steps` 写入完整可观测记录 | 集成 |
| AC-44-12 | 当资产超过展示上限时，`total_count / shown_count / omitted_count` 精确，Markdown 出现省略提示 | 单元 |
| AC-44-13 | deterministic path 至少输出一个 `token` 事件，且 `done.answer` 与 token 拼接内容一致 | API |
| AC-44-14 | 含筛选/推荐/引用上一轮条件的问题不命中 deterministic path | 单元 |
| AC-44-15 | 后续 ReAct history 可读取 schema inventory 的 compact structured context | 单元 |

---

## 11. 测试策略

### 11.1 单元测试

文件：

```text
backend/tests/services/data_agent/test_schema_inventory_skill.py
```

测试用例：

| 用例 | 输入 | 断言 |
|------|------|------|
| `test_detect_schema_inventory_zh` | `你有哪些数据源？` | 返回 `schema_inventory` |
| `test_detect_schema_inventory_en` | `what data sources are available?` | 返回 `schema_inventory` |
| `test_detect_excludes_metric_query` | `最近 7 天销售额是多少？` | 返回 `None` |
| `test_normalize_groups_by_type_project` | 固定 tables payload | 分组、计数、排序正确 |
| `test_render_exact_counts_no_fuzzy_words` | normalized payload | 不含 `+` / `约` / `多个` |
| `test_render_is_deterministic` | 同一 payload 渲染 3 次 | 完全相等 |
| `test_validate_rejects_count_mismatch` | 人为篡改 count | 抛出校验异常 |
| `test_truncation_counts_are_consistent` | 150 条 datasource，展示上限 100 | `total_count=150`，`shown_count=100`，`omitted_count=50` |
| `test_render_omitted_marker_required` | `omitted_count > 0` | Markdown 出现“其余 50 个已省略” |
| `test_detect_excludes_filtered_inventory` | `当前连接有哪些包含“销售”字样的数据源？` | 返回 `None` |

### 11.2 API/SSE 集成测试

文件：

```text
backend/tests/test_agent_schema_inventory_api.py
```

测试约束：

- 使用 FastAPI `TestClient`。
- 覆盖 `get_current_user`，构造 `admin` 或 `analyst`。
- mock `schema` 工具返回固定结构化数据。
- mock/patch LLMService，使其一旦被调用就抛异常；测试必须证明 deterministic path 不调用 LLM。
- 读取 SSE event，断言事件顺序和 `done` payload。

关键断言：

```python
assert events[0]["type"] == "metadata"
assert any(e["type"] == "tool_call" and e["tool"] == "schema" for e in events)
assert done["response_type"] == "schema_inventory"
assert done["tools_used"] == ["schema"]
assert done["steps_count"] == 1
assert "26+" not in done["answer"]
assert "".join(e["content"] for e in events if e["type"] == "token") == done["answer"]
```

### 11.3 回归测试

必须确保以下现有行为不被破坏：

- 普通问数仍可走 `query` / fast path。
- ReAct 工具链仍可处理非 inventory 问题。
- `/api/agent/conversations/{id}/messages` 可读取 deterministic assistant 消息。
- 首页前端无需改动即可展示 Markdown。

### 11.4 Mock 与测试约束

- **LLMService**：deterministic path 测试必须 mock 为“调用即失败”，证明没有隐式 LLM 依赖。
- **SchemaTool**：单元测试不连真实数据库；API 测试 mock 工具执行结果即可。
- **SessionManager**：使用同步 SQLAlchemy Session，不需要 `AsyncMock`。
- **SSE**：测试必须解析完整事件流，不允许只断言 HTTP 200。
- **Token 分片**：deterministic path 测试必须断言 token 拼接结果等于 `done.answer`。
- **排序断言**：测试数据必须故意打乱顺序，验证 normalize 后稳定排序。
- **多轮上下文**：history builder 单测不需要真实 LLM；只断言 compact structured context 被注入，且字段/条数受限。

---

## 12. Coder 交付任务

### Task 1：Intent Router

- 新增 `detect_deterministic_intent()`。
- 覆盖中文/英文关键词和排除词。
- 不 import FastAPI。

### Task 2：Schema Inventory Skill

- 新增 `run_schema_inventory_skill()`。
- 通过 registry 获取 `schema` 工具。
- 调用工具后执行 normalize、validate、render。
- 返回统一结果对象，供 API 层转 SSE。

建议返回结构：

```python
@dataclass
class DeterministicSkillResult:
    answer: str
    response_data: dict
    tools_used: list[str]
    response_type: str
    steps_count: int
```

### Task 3：API 集成

- 在 `agent_stream` 创建 engine/registry 后，ReAct 前增加 deterministic branch。
- 保持原有 fast path / ReAct 路径不变。
- 保存 user message 的行为不变。
- assistant message 使用 `SessionManager.persist_message()`。
- deterministic answer 必须按 §5.2 分片输出 `token` 事件，再输出 `done`。
- `thinking` 事件使用业务友好文案；技术路由原因写日志和 step。

### Task 4：可观测性

- 写入 `BiAgentRun`。
- 写入 4 条 `BiAgentStep`。
- 错误时 run 标记为 `failed`。

### Task 5：测试

- 完成 §11.1 和 §11.2。
- 所有新增 AC 必须有对应测试断言。

### Task 6：多轮上下文

- 扩展现有 history builder。
- 当历史消息存在 `response_type="schema_inventory"` 时，注入 compact structured context。
- 控制注入条数和字段，避免把完整大型 `response_data` 塞进 LLM prompt。

---

## 13. 开发交付约束

### 13.1 架构红线

- deterministic 模块不得 import `fastapi`。
- deterministic 模块不得直接读取 `os.environ`。
- deterministic 模块不得调用 LLM。
- deterministic 模块不得直接查询 `TableauAsset`，必须复用 `schema` 工具。
- 不得修改 `SchemaTool` 的 Tableau 查询语义，除非另立 spec。
- 不得改变非 inventory 问题的现有路由行为。

### 13.2 强制检查清单

- [ ] “你有哪些数据源？”命中 deterministic path。
- [ ] deterministic path 中 LLM mock 为抛异常时测试仍通过。
- [ ] `done.answer` 不含模糊计数。
- [ ] `response_data.summary` 与 `response_data.groups[].total_count` 计数一致。
- [ ] `shown_count / omitted_count` 与实际展示条数一致。
- [ ] deterministic path 至少输出一个 `token` 事件。
- [ ] 同一 payload 渲染完全一致。
- [ ] 权限错误不被 deterministic path 吞掉。
- [ ] 含筛选、推荐、引用上一轮的复杂问题不命中 deterministic path。
- [ ] 下一轮 ReAct history 能读取 compact structured context。
- [ ] ReAct 现有测试仍通过。

### 13.3 验证命令

```bash
cd backend
python -m py_compile app/api/agent.py services/data_agent/deterministic/*.py
python -m pytest tests/services/data_agent/test_schema_inventory_skill.py -q
python -m pytest tests/test_agent_schema_inventory_api.py -q
python -m pytest tests/test_agent_api.py -q
```

如果项目环境要求使用 venv：

```bash
backend/.venv/bin/python -m pytest backend/tests/services/data_agent/test_schema_inventory_skill.py -q
backend/.venv/bin/python -m pytest backend/tests/test_agent_schema_inventory_api.py -q
```

### 13.4 正确 / 错误示范

```python
# 错误：schema 结果再交给 LLM 整理
answer = await llm.complete(prompt=json.dumps(schema_result, ensure_ascii=False))
```

```python
# 正确：确定性模板渲染
payload = normalize_schema_inventory(schema_result["data"])
validate_schema_inventory_payload(payload)
answer = render_schema_inventory_markdown(payload)
```

```python
# 错误：为了方便直接查 TableauAsset
assets = db.query(TableauAsset).filter(TableauAsset.connection_id == connection_id).all()
```

```python
# 正确：复用现有 schema 工具
tool = registry.get("schema")
result = await tool.execute(params={}, context=context)
```

---

## 14. Tester 验收清单

### 14.1 P0 必测

- [ ] 用固定 schema mock 数据，调用 `/api/agent/stream`，断言未调用 LLM。
- [ ] 断言 SSE 事件顺序稳定。
- [ ] 断言 Markdown 中 datasource/view 数量精确。
- [ ] 断言资产分组按 type -> project -> name 稳定排序。
- [ ] 断言工具结果中不存在的资产名不会出现在回答中。
- [ ] 断言 `agent_conversation_messages.response_type == "schema_inventory"`。
- [ ] 断言 `bi_agent_steps` 有 thinking/tool_call/tool_result/answer 四类记录。
- [ ] 用非 inventory 问题回归，确认仍走原路径。

### 14.2 手工验收

在本地启动后访问首页，选择 Tableau 连接，输入：

```text
你有哪些数据源？
```

预期：

- 页面正常流式输出。
- 回答中数量为精确整数。
- 不出现 `26+`、`约`、`多个` 等模糊计数。
- 不出现工具结果外的“推荐核心表”。
- 刷新页面后历史会话可读取同一回答。

---

## 15. OpenSpec 说明

项目根目录存在：

```text
openspec/
.claude/skills/openspec-*
```

说明项目曾引入 OpenSpec 工作流。但当前技术规格主索引仍是：

```text
docs/specs/README.md
```

且该 README 明确规定：

```text
所有技术规格书统一存放于 docs/specs/
文件名格式：{序号}-{模块名}-spec.md
```

因此本次先按项目主规范落到 `docs/specs/`。如后续要求 OpenSpec 化，可再创建：

```text
openspec/specs/agents/00-44-data-agent-deterministic-schema-inventory-spec.md
```

或通过 OpenSpec CLI 生成 change proposal / design / tasks。

---

## 16. 开放问题

| # | 问题 | 负责人 | 状态 |
|---|------|--------|------|
| 1 | P1 是否支持“某表有哪些字段”的确定性 table_name 抽取 | architect | 待定 |
| 2 | 是否需要前端原生折叠表格展示 `response_data.groups` | frontend | P2 评估 |
| 3 | `response_type=schema_inventory` 是否需要加入前端类型定义 | frontend/backend | 实施时确认 |
| 4 | OpenSpec 是否作为后续所有新 spec 的强制入口 | owner | 待定 |
