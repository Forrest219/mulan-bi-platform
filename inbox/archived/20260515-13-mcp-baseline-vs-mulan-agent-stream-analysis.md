# MCP Baseline vs Mulan Agent Stream 工作流对比分析

生成时间：2026-05-15 13:xx CST
分析对象：Tableau Online 数据源 `订单+ (示例 - 超市)`，datasource_luid `f4290485-26d3-428f-aa8d-ccc33862a411`
问题来源：`/Users/forrest/Documents/my_vault/20_Projects/21_mulan_bi_platform/data_agent_Q&A.md` 的 batch2
对照原始数据：`inbox/20260515-13-abtest-raw.json`

## 结论

当前观察到的结果是：**Mulan `/api/agent/stream` 在 batch2 的多数问数问题上明显劣于 MCP gateway baseline**。

最核心差距不是 Tableau MCP 本身不可用，而是 Mulan 链路在进入 MCP 前增加了意图识别、数据源路由、planning skill、QuerySpec、校验、answer renderer、SSE 封装和前端表格解析等多层门控。已有 A/B raw 结果显示，Q1-Q10 中除 Q0 schema 问题外，Mulan 大多在 `planning_skill_loader` 阶段失败，返回 `query_plan_unavailable: 未找到该意图对应的 planning skill`，没有真正执行 `tableau_mcp`。而 baseline 直连 gateway 可以直接构造 MCP tool args，稳定拿到结构化 `fields/rows`。

如果目标是“Mulan 输出不能劣于 MCP gateway”，当前首要短板是：**受控问数主链路依赖 planning skill 的可用性，且缺少在 skill 缺失时退回 MCP direct/proxy 的兜底策略**。

## 两条路径的工作流

### 路径 A：MCP baseline 直连本地 Tableau MCP gateway

典型流程：

1. 客户端直连 `http://localhost:3927/tableau-mcp`。
2. MCP streamable-http 三步：`initialize` -> `notifications/initialized` -> `tools/call`。
3. 对 `query-datasource` 直接传 Tableau MCP tool args，例如：

```json
{
  "datasourceLuid": "f4290485-26d3-428f-aa8d-ccc33862a411",
  "query": {
    "fields": [
      {"fieldCaption": "客户名称"},
      {"fieldCaption": "销售额", "function": "SUM", "sortDirection": "DESC", "sortPriority": 1}
    ],
    "filters": []
  },
  "limit": 10
}
```

4. gateway 返回 SSE，其中 `data:` 是 JSON-RPC 响应；`result.content[0].text` 内再嵌套业务 JSON。
5. baseline 脚本解析后得到统一结构：`{"fields": [...], "rows": [...]}`。
6. answer/core 文案由脚本基于结构化数据确定性计算。

这条链路的优势是短：只要字段名、聚合、筛选和 limit 构造正确，就能贴近 Tableau MCP 原始能力。

### 路径 B：Mulan `/api/agent/stream` + SSE `done.response_data`

后端入口是 `backend/app/api/agent.py` 的 `POST /api/agent/stream`。关键流程：

1. 权限校验、connection 解析、创建/续接 conversation。
2. 发送前置 SSE 事件：`intent_classifier`、`route_decision`、`explainability`。
3. 若识别为 schema/资产清单，走 deterministic route，直接用 schema 工具返回 `done.response_data`。
4. 若是问数问题，进入标准 ReAct / controlled data path。
5. controlled path 当前有两种：
   - `mcp_first_main`：先加载 planning skill，生成/兜底 QuerySpec，校验，再执行 Tableau MCP，最后 answer renderer。
   - `mcp_proxy_main`：实验链路，LLM 直接生成 MCP tool args，再经 guardrail 后执行 Tableau MCP。
6. `/api/agent/stream` 将内部 `AgentEvent` 转成 SSE。成功时最后发：

```json
{
  "type": "done",
  "answer": "...",
  "response_type": "table",
  "response_data": {
    "fields": ["客户名称", "SUM(销售额)"],
    "rows": [["李丽丽", 181562.1125]]
  }
}
```

7. 前端 `useStreamingChat` 只在 `response_type === "table"` 且 `response_data.fields/rows` 非空时提取表格；否则不渲染表格。

这条链路的价值是可治理、可解释、可权限控制，但比 baseline 多出很多可能阻断或劣化结果的环节。

## 具体示例对比

### 示例 1：Q1 整体指标

问题：`整体的销售额、利润、利润率、客户数、客单价是什么样子`

baseline 结果：

- fields：`SUM(销售额)`, `SUM(利润)`, `COUNTD(客户名称)`
- rows：`[16867374.06867518, 2119151.905850007, 771]`
- core：销售额 `1686.74万`，利润 `211.92万`，利润率 `12.56%`，客户数 `771`，客单价 `2.19万`
- 耗时约 `1.66s`

Mulan 结果：

- HTTP 200，但 SSE 最终是 `error`
- error_code：`query_plan_unavailable`
- message：`未找到该意图对应的 planning skill。`
- 没有 `done.response_data`，没有表格数据
- 耗时约 `1.46s`

差异判断：baseline 已经能直接完成聚合查询和派生指标计算；Mulan 在 MCP 执行前失败。该问题不是“输出格式差一点”，而是**没有完成查询**。

### 示例 2：Q6 Top 10 大客户

问题：`Top 10 大客户是谁？请列出客户名称和销售金额及占比`

baseline 结果：

- fields：`客户名称`, `SUM(销售额)`
- rows Top3：
  - `李丽丽`, `181562.1125`
  - `潘锦`, `138128.5805`
  - `袁丽美`, `109600.70775`
- core：Top3 分别占总销售额 `1.08%`、`0.82%`、`0.65%`
- 耗时约 `2.80s`

Mulan 结果：

- HTTP 200，但 SSE 最终是 `error`
- intent_classifier 识别为 `ranking`
- 失败点仍是 `planning_skill_loader`
- 没有表格、没有占比、没有排序结果

差异判断：这是典型“baseline 可完成、Mulan 被前置治理层拦截”的问题。Mulan 即使 intent 识别正确，也要求 ranking 对应 planning skill 存在，否则直接退化为错误。

### 示例 3：Q10 辽宁、福建 2024 巨亏原因

问题：`为什么辽宁、福建在 2024 年出现了巨亏？请看看是什么产品线和客户导致的`

baseline 结果：

- 产品线维度 Top3 亏损：
  - 辽宁-装订机 `-3.08万`
  - 福建-设备 `-2.78万`
  - 辽宁-设备 `-2.74万`
- 客户维度 Top3 亏损：
  - 福建-殷丽雪 `-2.77万`
  - 辽宁-黄涛 `-2.48万`
  - 辽宁-柯巧 `-2.12万`
- baseline 通过两次 MCP 查询分别按 `子类别` 和 `客户名称` breakdown。

Mulan 结果：

- intent_classifier 识别为 `root_cause`
- 仍失败于 planning skill 缺失
- 没有执行 Tableau MCP

差异判断：root cause 类问题本来需要多步查询或 semantic operator。baseline 脚本用固定策略能完成；Mulan 的设计上支持 semantic operator，但当前 skill 依赖未满足，导致高价值分析问题完全不可用。

### 示例 4：Q0 数据源介绍

问题：`介绍数据源“订单+ (示例 - 超市)”`

Mulan 结果优于该次 baseline raw：

- Mulan 走 schema_inventory，返回 11 个字段，包括 `客单价`、`利润率`、`客户数`、`子类别`、`发货日期`、`销售额`、`利润`、`客户名称` 等。
- baseline raw 的 Q0 metadata 解析结果显示 `数据源 None，字段 0 个`，说明该脚本对 `get-datasource-metadata` 的返回结构适配不足。

差异判断：schema/资产清单类问题，Mulan deterministic route 有优势。但这不能掩盖 Q1-Q10 问数主链路的系统性失败。

## 链路短板与风险点

### P0：planning skill 缺失会阻断整个问数链路

证据：`mcp_first_main` 在 `_queryable_fields` 后立即 `loader.load_planning(intent_result.intent)`，若 skill 缺失则返回 `query_plan_unavailable`，不会继续生成 QuerySpec，也不会执行 Tableau MCP。

影响：只要某个 intent 没有配置 planning skill，Mulan 就会比 MCP gateway 明显差。当前 raw 结果中 Q1-Q10 多数都卡在这里。

建议：把“planning skill 缺失”从硬失败改为可降级路径。至少对 `aggregate`、`ranking`、`trend_condition`、`set_difference`、`customer_record`、`root_cause` 建立内置 fallback planning 或切到 `mcp_proxy`。

### P0：质量基线存在雏形，但尚未真正用于阻断劣化输出

项目里已有 `batch2_cases.yaml`、`mcp_baseline_comparator.py`、`quality_gate.py`，能定义 required_fields、max_rows、numeric tolerance 等。但 live snapshot 仍是 draft，`superstore_2026_05_13.json` 只有 Q6 示例数据，且注释要求替换为 reviewed MCP output。

影响：即使 Mulan 后续能返回 `done.response_data`，目前也缺少“与 MCP baseline 对齐”的自动阻断机制，无法保证不劣于 gateway。

建议：把 batch2 的 3-5 个代表问题先固化为 reviewed snapshot，最少覆盖 Q1、Q6、Q8、Q10；CI 跑 snapshot shape，nightly/manual 跑 live MCP compare。

### P0：前端只认 `done.response_data` 的 table 类型，`table_data` 事件缺少 table_display

前端表格提取逻辑要求：

- `response_type === "table"`
- `response_data.fields` 是数组
- `response_data.rows` 是非空数组

如果后端只发 `table_data`，或 `done.response_type` 不是 `table`，最终表格可能不渲染。后端当前转发 `table_data` 时只带 `fields/rows/col_types`，不带 `table_display`；前端虽尝试解析 `table_display`，但事件类型声明里没有该字段。

影响：数据可能在 SSE 中出现，但 UI 不一定以完整表格契约展示；列标签、数值格式、百分比和对齐可能丢失。

建议：统一要求成功问数的最终 `done.response_data` 必含 `fields/rows/table_display`，并让 `table_data` 事件也携带同一份 `table_display`。

### P1：Mulan 受 LLM QuerySpec 和 answer renderer 双重影响，可能引入非 MCP 原始劣化

`mcp_first_main` 里，MCP 执行前有 LLM QuerySpec；执行后还有 answer renderer。虽然有 deterministic replacement，但仍存在风险：

- QuerySpec 漏掉字段、误选日期字段、错误聚合。
- answer 文案与 `rows` 不一致。
- 派生指标如利润率、占比、客单价如果只在文案中算，可能没有进入 `response_data.rows`。

建议：派生指标必须结构化落到 `response_data.fields/rows`，answer 只能解释结构化数据，不应成为唯一载体。

### P1：日期字段和时间口径存在 baseline/Mulan 不一致风险

baseline 脚本实际使用 `发货日期` 做 2021-2025 年度口径；batch2 case yaml 里部分 required_fields 写的是 `订单日期`。Mulan schema_inventory 返回的是 `发货日期` 和计算字段 `发货年份`。

影响：若质量门禁按 `订单日期` 校验，会误杀真实可用结果；若 Mulan QuerySpec 使用 `订单日期`，MCP 可能报 unknown field。

建议：把 batch2 相关基线字段统一到 MCP metadata 的真实字段名，或在 comparator 中支持字段同义词映射，但最终执行 args 必须使用 MCP 可查询字段。

### P1：MCP proxy 链路更贴近 baseline，但当前是实验开关

`mcp_proxy_main` 的设计更接近 baseline：LLM 直接生成 official MCP tool args，再由 guardrail 校验，最后执行 `query-datasource`。这比 QuerySpec 链少一层转换，更适合作为“不能劣于 MCP gateway”的主对照路径。

风险在于它依赖 `DATA_AGENT_MCP_PROXY_ENABLED` 和 chain selector；如果没开，仍走 `mcp_first_main`，会继续暴露 planning skill 缺失问题。

建议：短期对 batch2 打开 `mcp_proxy` 做 A/B；中期让 `mcp_first_main` 在 planning skill 缺失或 QuerySpec 失败时自动降级到 `mcp_proxy`，但保留 guardrail。

## 建议的验收标准

为了保证 Mulan 不劣于 MCP gateway，建议把每个 case 的验收拆成 4 层：

1. 路由层：必须选中正确 connection/datasource，不得 fallback 成泛化回答。
2. 执行层：必须至少一次进入 `tableau_mcp`，除非问题本身是 schema_inventory。
3. 结果层：`done.response_type === "table"` 且 `response_data.fields/rows` 满足 baseline required_fields、max_rows、row_set/numeric tolerance。
4. 展示层：前端能从 `done.response_data` 渲染表格，并保留 `table_display` 的列标签、格式和对齐。

建议先固化 5 个 batch2 canary：

- Q1：整体 KPI，覆盖聚合 + 派生指标。
- Q4：继续拆分到每个年份，覆盖上下文继承。
- Q6：Top 10 大客户，覆盖排序、limit、占比。
- Q8：利润每年持续增长，覆盖趋势条件。
- Q10：辽宁/福建巨亏原因，覆盖多维 breakdown / root cause。

## 可执行改进优先级

1. 补齐或内置 fallback planning skills：`aggregate`、`ranking`、`trend_condition`、`set_difference`、`customer_record`、`root_cause`。
2. 用已有 A/B runner 重新录制 reviewed MCP baseline snapshot，替换 draft fixture。
3. 把 baseline comparator 接入 Data Agent done 前质量门禁：缺字段、超行数、数值偏差时不标记成功。
4. 统一 `done.response_data` 表格契约：`fields/rows/table_display` 必须完整保留。
5. 对 batch2 canary 建立自动化回归，报告同时输出 MCP baseline、Mulan response_data、UI tableData 三份结果。

## 参考代码位置

- `/api/agent/stream` 入口和 SSE 封装：`backend/app/api/agent.py:966`
- deterministic schema route：`backend/app/api/agent.py:1108`
- 标准 ReAct controlled data path：`backend/app/api/agent.py:1304`
- `done.response_data` SSE 输出：`backend/app/api/agent.py:1340`
- `mcp_first_main` planning skill / QuerySpec / MCP 执行：`backend/services/data_agent/mcp_first_main.py:30`
- `mcp_proxy_main` direct MCP args 实验链路：`backend/services/data_agent/mcp_proxy_main.py:40`
- 前端 `done.response_data` 表格提取：`frontend/src/hooks/useStreamingChat.ts:175`
- batch2 baseline cases：`backend/tests/fixtures/data_agent/baseline/batch2_cases.yaml`
- A/B 原始结果：`inbox/20260515-13-abtest-raw.json`
