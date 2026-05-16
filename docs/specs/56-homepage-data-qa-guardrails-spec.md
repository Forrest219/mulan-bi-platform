# 首页问数 Data QA 与结果质量门禁技术规格书

> 版本：v0.1 | 状态：Engineering Spec — Ready for Task Breakdown | 日期：2026-05-16 | 关联 PRD：100 人 x 1000 问首页问数准确性保障

---

## 1. 概述

### 1.1 目的

本 Spec 定义首页数据问答的 Data QA 质量闭环：把 Batch 2 失败样本沉淀为可回归的 Golden Set，在参数级 Guardrail 之后增加结果级 Result Guardrail，并用语义状态、语义算子测试和多轮上下文测试支撑“答案准确性不低于 MCP baseline”的产品验收。

核心目标从“链路能返回答案”升级为：

```text
结果可判、语义可测、失败可复现、回归可自动化
```

### 1.2 范围

- **包含**：
  - Data QA Golden Set 的用例契约、存储格式和运行要求。
  - Result Guardrail 的输入/输出、执行位置、P0 拦截规则和错误码。
  - 质量分级标签：`semantic_pass`、`semantic_fail`、`needs_review`。
  - Fallback 默认 `needs_review` 的埋点与升级规则。
  - Batch 2 Q0-Q10 的回归分层，尤其 Q5/Q8/Q9/Q10 强制质量门禁。
  - Q2/Q4 多轮追问上下文继承测试。
  - Q5/Q8/Q9 语义算子验收表与单元测试要求。
  - Metrics Registry 产品化前的 Python 派生指标冻结规则。

- **不包含**：
  - Metrics Registry 的完整产品化实现。
  - Tableau MCP Server 自身 schema 或执行能力改造。
  - 前端完整 QA 工作台。
  - 覆盖 1000 问的全量题库建设；本 Spec 只定义第一阶段机制和 Batch 2 种子集。

### 1.3 关联文档

| 文档 | 路径 | 关系 |
|------|------|------|
| Data Agent 架构 | `docs/specs/36-data-agent-architecture-spec.md` | 首页 Agent 主架构 |
| Transparent MCP Proxy | `docs/specs/54-data-agent-transparent-mcp-proxy-plan.md` | MCP proxy 与 guardrail 背景 |
| Agent 架构蓝图 | `docs/tech/mulan-agent-architecture-blueprint.md` | 语义契约、Guardrail、SSOT 共识 |
| MCP Host code review | `inbox/20260516-mcp-host-code-review.md` | 代码风险与架构共识 |
| Data QA 架构反馈 | `inbox/20260516-13-data-qa-architecture-feedback.md` | 需求来源 |
| Golden Set 测试用例 | `docs/specs/testcases/56-homepage-data-qa-golden-set-test-cases.md` | 本 Spec 的测试矩阵 |

### 1.4 与 Spec 36 / Spec 54 的关系

本 Spec 是首页问数的**质量验收覆盖层**，不直接替代 Spec 36 / Spec 54 的链路选择设计。

当链路设计文档强调 fallback 可用性时，本 Spec 对产品验收做更严格约束：

- fallback 只代表高可用，不代表语义正确。
- fallback 结果默认标记为 `needs_review`。
- 只有通过结果级校验或 Golden Set 判定的 fallback 结果，才允许升级为 `semantic_pass`。
- QuerySpec、MCP Host、MCP proxy、legacy chain 的任何路径，只要进入首页问数用户答案，都必须接受本 Spec 的质量门禁。

---

## 2. 核心概念

| 概念 | 定义 |
|------|------|
| Data QA Golden Set | 可重复执行的首页问数语义回归集，首批由 Batch 2 Q0-Q10 组成。 |
| MCP baseline | 由 MCP 参照链路得到的基准结果，包括 row count、核心字段、核心值和粒度。 |
| Result Guardrail | MCP/Tableau 结果返回后、Renderer 介入前的结果级质量门禁。 |
| semantic status | 对一次问答结果的语义质量标签：`semantic_pass` / `semantic_fail` / `needs_review`。 |
| detail scan | 用户要聚合答案但系统返回高行数原始明细的行为。 |
| semantic operator | 可确定测试的业务语义算子，例如差集、连续增长、全周期条件。 |

---

## 3. 目标架构

### 3.1 执行位置

Result Guardrail 必须位于数据结果返回后、任何自然语言总结或前端渲染前：

```text
User Question
  -> Semantic Plan / MCP Args
  -> MCP Args Guardrail
  -> Tableau MCP
  -> Result Guardrail
  -> Deterministic Postprocessor
  -> Renderer
  -> Frontend
```

`mcp_args_guardrail.py` 继续负责参数级防线；Result Guardrail 应作为独立模块实现，避免参数护栏和结果护栏职责混杂。

### 3.2 前置资源闸口 (Resource Cap)

Result Guardrail 不能只在 Python 已经拿到完整结果后再判断行数。首页问数链路必须在 MCP executor / network 层设置硬资源上限，防止底层 Tableau MCP 返回大批明细导致 Python 进程 OOM。

P0 要求：

- 所有首页问数的 `query-datasource` 调用必须强制注入 `max_rows`、`max_bytes` 和 `timeout`，即使 LLM 未生成这些限制。
- 默认 `max_rows` 建议为 `1000`；更严格的 detail scan 判定阈值仍由 Result Guardrail 的 `max_detail_rows` 控制。
- 如果执行层发生截断，必须在 result metadata 中写入：

```json
{
  "truncated_by_guardrail": true,
  "guardrail_resource_cap": {
    "max_rows": 1000,
    "max_bytes": 5242880,
    "timeout_ms": 30000
  }
}
```

- Result Guardrail 看到 `truncated_by_guardrail=true` 时，若该请求属于首页问数聚合/趋势/条件判断路径，应优先判定为 `DETAIL_SCAN_BLOCKED`。
- 明确的分页、导出、明细检索链路不属于本 Spec 的首页问数路径，必须另走独立权限、分页和审计机制。

### 3.3 Result Guardrail 契约

#### 输入

```json
{
  "question": "string",
  "chain_mode": "legacy_queryspec | mcp_proxy | mcp_host",
  "fallback_triggered": true,
  "fallback_reason": "string | null",
  "semantic_operator": "aggregate | set_difference | consecutive_growth | all_period_condition | ranking | root_cause | unknown",
  "context_snapshot": {
    "previous_metrics": [],
    "previous_dimensions": [],
    "previous_filters": [],
    "previous_time_range": null
  },
  "tool_name": "query-datasource",
  "safe_args": {},
  "result": {
    "fields": [],
    "rows": [],
    "metadata": {
      "truncated_by_guardrail": false
    }
  },
  "thresholds": {
    "max_detail_rows": 200,
    "max_unaggregated_rows": 100
  }
}
```

#### 输出

```json
{
  "decision": "allow | block | review",
  "semantic_status": "semantic_pass | semantic_fail | needs_review",
  "error_code": "DETAIL_SCAN_BLOCKED | RESULT_FIELD_MISSING | RESULT_GRAIN_MISMATCH | SEMANTIC_QA_FAILED | null",
  "message": "string",
  "checks": [
    {
      "name": "detail_scan",
      "status": "pass | fail | review",
      "detail": {}
    }
  ]
}
```

### 3.4 P0 拦截规则

| 规则 | 触发条件 | 结果 |
|------|----------|------|
| Detail scan block | 用户问题需要聚合/趋势/TopN/条件判断，但结果为超过阈值的原始明细行 | `block` + `DETAIL_SCAN_BLOCKED` |
| Resource cap truncation | 首页问数路径触发 `truncated_by_guardrail=true` | `block` + `DETAIL_SCAN_BLOCKED` |
| Missing core field | 结果字段缺少用户问题核心指标或维度 | `review` 或 `block`，Golden Set case 中为 `semantic_fail` |
| Grain mismatch | 用户问题要求年份/客户/省份粒度，结果粒度不匹配 | `review` 或 `semantic_fail` |
| Fallback default review | `fallback_triggered=true` 且无结果级校验证据 | `needs_review` |
| Renderer block | Result Guardrail 输出 `block` | 禁止 Renderer 总结，返回结构化错误 |

`DETAIL_SCAN_BLOCKED` 是 Data Agent 结果级检查码；若进入统一 API 错误包络，后续实现应按 `docs/specs/01-error-codes-standard.md` 映射到模块化错误码，同时保留该检查码用于 trace 和 QA 分类。

---

## 4. Golden Set 与 Benchmark Harness

### 4.1 用例格式

首批用例存放建议：

```text
backend/tests/fixtures/data_agent_golden_set/batch2_q0_q10.yaml
```

每个 case 必须包含：

```yaml
- id: Q5
  title: 差集语义
  priority: P0
  session_group: batch2
  turn_index: 1
  question: ""
  context_before: {}
  expected_operator: set_difference
  mcp_baseline:
    row_count: null
    core_fields: []
    core_values: []
    grain: ""
  assertions:
    row_count: {}
    required_fields: []
    forbidden_fields: []
    semantic_rules: []
  failure_tags:
    - semantic_reversal
```

### 4.2 强制门禁 case

| Case | 类型 | 验收重点 | CI 要求 |
|------|------|----------|---------|
| Q2 | 多轮追问 | 继承上轮指标、维度、时间范围 | P0 |
| Q4 | 多轮追问 | 继承上轮过滤条件和当前追问意图 | P0 |
| Q5 | 差集 | 不得把“未发生/不包含”反向查成 TopN 发生 | P0 |
| Q8 | 连续增长 | “连续/每年都”必须是全相邻周期条件 | P0 |
| Q9 | 全周期条件 | “一直/每年/全周期”必须覆盖所有目标周期 | P0 |
| Q10 | 明细扫描 | 不得拉大批原始明细后让 LLM 总结 | P0 |

### 4.3 判定原则

- 接口成功不等于 QA pass。
- 有自然语言回复不等于 QA pass。
- MCP args 合法不等于 QA pass。
- Golden Set 中任一 P0 case 出现语义反向、粒度错误、核心字段缺失或 detail scan，均判失败。
- 如果 CI 使用 mocked Golden Set 全绿，但 nightly 真实链路大面积失败，应触发 `SCHEMA_DRIFT_ALERT`，冻结相关 Golden Set 的 pass 结论，直到 QA 与研发重新同步 MCP baseline 和 schema。

---

## 5. 语义状态与埋点

### 5.1 状态定义

| 状态 | 含义 |
|------|------|
| `semantic_pass` | 结果通过 Golden Set 或 Result Guardrail 的确定性校验。 |
| `semantic_fail` | 结果违反确定性语义规则，禁止作为成功样本统计。 |
| `needs_review` | 结果可展示或可返回，但缺少自动判定证据，需要人工或离线 QA 复核。 |

### 5.2 指标口径

质量大盘必须区分业务语义指标和研发运维指标：

| 指标 | 口径 | 使用者 |
|------|------|--------|
| Strict Semantic Pass Rate | `semantic_pass / total_questions`，剔除 `needs_review` 和 `semantic_fail` | PM / 业务首屏 |
| Needs Review Rate | `needs_review / total_questions`，包含 fallback 和护栏无法确定样本 | PM / QA / Backend |
| Semantic Fail Rate | `semantic_fail / total_questions`，包含 Golden Set 或 Result Guardrail 确定失败样本 | PM / QA / Backend |
| Execution Success Rate | 链路未抛出 5xx 或基础执行异常的比例，不代表业务答对 | Backend / DevOps |

业务层和管理层默认查看 Strict Semantic Pass Rate；Execution Success Rate 仅用于定位链路稳定性，不得对外等同为问数成功率。

### 5.3 默认规则

| 场景 | 默认状态 |
|------|----------|
| 正常主链路且通过 Result Guardrail | `semantic_pass` |
| fallback 触发且未命中 Golden Set 自动判定 | `needs_review` |
| Result Guardrail block | `semantic_fail` |
| Golden Set 断言失败 | `semantic_fail` |
| Result Guardrail 无法判断 | `needs_review` |

### 5.4 Trace 字段

每次首页问数至少记录：

```json
{
  "data_qa.semantic_status": "needs_review",
  "data_qa.case_id": "Q5",
  "data_qa.semantic_operator": "set_difference",
  "data_qa.fallback_triggered": true,
  "data_qa.fallback_reason": "MCP_ARGS_LLM_INVALID",
  "data_qa.result_guardrail_decision": "review",
  "data_qa.result_guardrail_error_code": null,
  "data_qa.truncated_by_guardrail": false
}
```

---

## 6. 语义算子验收表

### 6.1 Sprint 2 P0 算子

| 算子 | 来源 case | 必须验证 |
|------|-----------|----------|
| `set_difference` | Q5 | A 有、B 无；不得反查为 B 有；结果必须体现差集条件。 |
| `consecutive_growth` | Q8 | 每个相邻周期均增长；不得只比较首尾或只找 TopN 增长。 |
| `all_period_condition` | Q9 | 条件必须覆盖所有目标周期；不得只判断任一周期。 |

### 6.2 测试要求

- 算子判断必须有 deterministic unit tests。
- 单测不得依赖 LLM。
- 算子实现优先使用标准库和轻量集合/序列逻辑；除非项目已有强依赖且数据量受控，不得为了 P0 算子默认引入 Pandas。
- 算子遇到周期缺失、字段缺失、异常空值、时间序列不连续时不得 crash，应返回或抛出可分类错误 `DATA_CONTINUITY_ERROR`，由上层转换为可理解提示。
- E2E Golden Set 可以调用真实链路，但断言必须是确定性的。

---

## 7. Python 派生计算冻结规则与 Virtual Metrics Registry

Metrics Registry 产品化前：

- 禁止新增利润率、客单价、销售占比等业务派生指标的 Python 计算公式。
- 禁止 Renderer 或 LLM 做任何业务计算。
- 允许 Python 对 MCP 已返回的聚合结果做确定性集合/条件判断，例如差集、连续增长、全周期条件。
- 如确需新增派生指标计算，必须先补 Metrics Registry 公式来源、版本、口径说明和测试。

过渡期允许极窄的 Escape Hatch：`Virtual Metrics Registry`。

临时派生指标只有满足以下条件才允许进入：

- TL 审批。
- 明确 owner。
- 公式、版本、来源说明完整。
- 有过期时间 (TTL) 和迁移到正式 Metrics Registry 的计划。
- 有单元测试和 Golden Set 或等价回归覆盖。
- response metadata 必须标记该指标来自 Virtual Metrics Registry，避免被误认为正式治理指标。

---

## 8. 测试策略

### 8.1 关键场景

| # | 场景 | 预期 | 优先级 |
|---|------|------|--------|
| 1 | Batch 2 Q0-Q10 Golden Set 执行 | 所有 P0 case 语义通过 | P0 |
| 2 | fallback 触发 | 默认 `needs_review`，不得自动计入成功 | P0 |
| 3 | detail scan 结果返回 | `DETAIL_SCAN_BLOCKED`，Renderer 不总结 | P0 |
| 4 | MCP result 触发资源截断 | `truncated_by_guardrail=true` 并被 Result Guardrail 判定 | P0 |
| 5 | Q5 差集 | 不得语义反向 | P0 |
| 6 | Q8 连续增长 | 必须验证每个相邻周期 | P0 |
| 7 | Q9 全周期条件 | 必须验证所有目标周期 | P0 |
| 8 | Q2/Q4 多轮追问 | 上下文继承正确 | P0 |
| 9 | CI 绿但 nightly 真实链路大面积失败 | 触发 `SCHEMA_DRIFT_ALERT` | P1 |

### 8.2 验收标准

- [ ] Data QA Golden Set 首批 Q0-Q10 已落地。
- [ ] Q5/Q8/Q9/Q10 作为强制门禁进入 CI 或 nightly。
- [ ] Q2/Q4 多轮追问测试进入 CI 或 nightly。
- [ ] Result Guardrail 独立模块落地，并接入所有首页问数返回路径。
- [ ] MCP executor / network 层有 `max_rows`、`max_bytes`、`timeout` 硬限制，避免 Result Guardrail 后置判断前 OOM。
- [ ] `semantic_pass` / `semantic_fail` / `needs_review` 进入 trace。
- [ ] 质量大盘区分 Strict Semantic Pass Rate 与 Execution Success Rate。
- [ ] fallback 默认 `needs_review`。
- [ ] `DETAIL_SCAN_BLOCKED` 能阻止 Renderer 总结。
- [ ] `DATA_CONTINUITY_ERROR` 和 `SCHEMA_DRIFT_ALERT` 有明确分类和测试覆盖。
- [ ] Metrics Registry 未上线前，无新增宽泛 Python 派生指标计算。
- [ ] 如启用 Virtual Metrics Registry，必须具备审批、TTL、公式版本和测试。

### 8.3 Mock 与测试约束

- **Result Guardrail**：单测直接构造 `fields/rows/metadata`，不得依赖 Tableau MCP 网络调用。
- **Golden Set E2E**：真实链路可放入 nightly；CI 最小集应使用固定 fixture 或 mocked MCP baseline，避免 provider 波动。
- **多轮追问**：必须复用同一 session/conversation context，不能把每轮拆成独立单问。
- **语义算子**：必须测试算子本身的 deterministic 判定函数，不允许只测 prompt 文案。

---

## 9. 分阶段开发计划

### Sprint 1：质量基建与拦截闭环

1. 建立 Data QA Golden Set：Batch 2 Q0-Q10。
2. 新增 Result Guardrail 模块，先覆盖 detail scan、字段缺失、fallback 默认 review。
3. 增加 MCP result 前置资源闸口，防止 Result Guardrail 后置判断前 OOM。
4. 增加语义状态埋点：`semantic_pass` / `semantic_fail` / `needs_review`，并区分 Strict Semantic Pass Rate 与 Execution Success Rate。

### Sprint 2：语义算子深化与上下文治理

1. Q5/Q8/Q9 抽象为语义算子验收表并补 deterministic 单测。
2. Q2/Q4 多轮追问上下文继承进入 CI/nightly。
3. 语义算子补充 `DATA_CONTINUITY_ERROR` 容错。
4. Metrics Registry 产品化前冻结 Python 派生指标扩张；必要时通过 Virtual Metrics Registry 受控放行。

---

## 10. 开放问题

| # | 问题 | 负责人 | 状态 |
|---|------|--------|------|
| 1 | Batch 2 Q0-Q10 的 MCP baseline 核心值由谁最终签字 | QA + PM | 待确认 |
| 2 | Result Guardrail P0 阈值是否按数据源/租户可配置 | Backend + PM | 待确认 |
| 3 | Golden Set 放 CI 还是 nightly 的切分比例 | QA + DevOps | 待确认 |
| 4 | 统一 API 错误码中 `DETAIL_SCAN_BLOCKED` 的最终映射 | Backend | 待确认 |
