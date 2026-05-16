# 首页问数 Data QA 开发计划与任务拆解

> 日期：2026-05-16
> Spec Source：`docs/specs/56-homepage-data-qa-guardrails-spec.md`
> Testcase Source：`docs/specs/testcases/56-homepage-data-qa-golden-set-test-cases.md`

---

## 1. PM 目标

首页问数的下一阶段目标不是“链路能返回答案”，而是“答案能被判定为正确”。本计划以 Spec 56 为实现合约，先建立 Data QA Golden Set、Result Guardrail 和质量分级埋点，再推进语义算子和上下文治理。

验收总口径：

```text
Batch 2 P0 case 可自动回归
fallback 默认 needs_review
detail scan 可阻断
Renderer 不总结被 Guardrail 判失败的数据
语义算子和上下文继承进入 CI/nightly
```

---

## 2. Sprint 1：质量基建与拦截闭环

### QA-001：沉淀 Batch 2 Golden Set

- **负责人**：QA
- **依赖**：Spec 56 §4，testcases/56
- **交付物**：
  - `backend/tests/fixtures/data_agent_golden_set/batch2_q0_q10.yaml`
  - Q0-Q10 的问题、session 分组、MCP baseline、row count、核心字段、核心值、粒度和失败标签。
- **验收**：
  - Q2/Q4/Q5/Q8/Q9/Q10 均为 P0。
  - 每个 P0 case 有确定性断言。
  - 未补录 baseline 的 case 不得标记为 `semantic_pass`。

### BE-001：实现 Golden Set benchmark harness

- **负责人**：Backend
- **建议路径**：
  - `backend/tests/services/data_agent/test_homepage_data_qa_golden_set.py`
  - `backend/tests/fixtures/data_agent_golden_set/`
- **任务**：
  - 读取 Golden Set fixture。
  - 支持 mocked MCP baseline 的 CI 模式。
  - 支持真实链路的 nightly 模式。
  - 输出 case 级判定：pass/fail/needs_review 和 failure_tags。
- **验收**：
  - P0 case 失败时测试失败。
  - fallback 未校验时输出 `needs_review`，不能算 pass。

### BE-002：新增 Result Guardrail 模块

- **负责人**：Backend
- **建议路径**：
  - `backend/services/data_agent/result_guardrail.py`
  - `backend/tests/services/data_agent/test_result_guardrail.py`
- **任务**：
  - 定义 Result Guardrail 输入/输出模型。
  - 实现 P0 检查：detail scan、核心字段缺失、粒度可疑、fallback 默认 review。
  - 输出 `decision=allow|block|review` 和 `semantic_status`。
- **验收**：
  - detail scan 命中时返回 `decision=block`、`semantic_status=semantic_fail`、`error_code=DETAIL_SCAN_BLOCKED`。
  - fallback 无自动校验证据时返回 `needs_review`。

### BE-003：接入首页问数返回链路

- **负责人**：Backend
- **建议接入点**：
  - `backend/services/data_agent/mcp_proxy_main.py`
  - `backend/services/data_agent/mcp_first_main.py`
  - 后续如 MCP Host 主链路启用，同样必须接入。
- **任务**：
  - 在 MCP/Tableau result 返回后、Postprocessor/Renderer 前调用 Result Guardrail。
  - `decision=block` 时禁止 Renderer 总结。
  - 保留原始 result metadata 供 QA trace 使用。
- **验收**：
  - 所有首页问数路径都有 Result Guardrail trace。
  - block 场景返回用户可理解错误，不返回 500。

### BE-004：语义状态与多维指标埋点

- **负责人**：Backend
- **任务**：
  - 在 trace / response metadata 中写入：
    - `data_qa.semantic_status`
    - `data_qa.case_id`
    - `data_qa.semantic_operator`
    - `data_qa.fallback_triggered`
    - `data_qa.result_guardrail_decision`
    - `data_qa.result_guardrail_error_code`
  - 明确统计口径切分，支持计算以下四个核心指标：
    1. **Strict Semantic Pass Rate** (严格语义成功率) - PM/业务首屏核心指标，必须剔除所有 `needs_review` 和 `semantic_fail`。
    2. **Needs Review Rate** (待复核率) - 包含所有 Fallback 和护栏无法确定的样本。
    3. **Semantic Fail Rate** (语义失败率) - 被护栏或 Golden Set 确定拦截的样本。
    4. **Execution Success Rate** (执行成功率) - 研发/运维指标，仅代表链路未抛出 5xx 异常。
- **验收**：
  - 各类指标聚合准确，Fallback 样本不再自动推高业务成功率大盘。

### BE-005：MCP Result 前置资源闸口 (防 OOM)

- **负责人**：Backend
- **建议路径**：
  - `backend/services/data_agent/mcp_host/runtime.py` 或底层 `TableauMCPClient` 封装处。
- **任务**：
  - 在向 MCP 发起 `query-datasource` 时，强制在 executor / network 层注入限制：`max_rows` (默认 1000)、`max_bytes`、`timeout`。
  - 若触发截断，向返回的 metadata 中写入标记 `truncated_by_guardrail: true`。
  - 将该标记传递给后置的 Result Guardrail 判定是否抛出 `DETAIL_SCAN_BLOCKED`（注意区分独立的分页/导出链路）。
- **验收**：
  - 执行 100 万行的明细扫描意图时，Python 进程内存稳定，不发生 OOM，且正常返回截断拦截提示。

### DEVOPS-001：CI/nightly 切分与 Schema Drift Alert

- **负责人**：DevOps + QA
- **任务**：
  - CI 跑 mocked fixture 最小集，保证代码逻辑变更的快速反馈。
  - nightly 跑真实链路或更接近真实链路的 benchmark，用于发现底层 Tableau schema 或 baseline 的漂移。
  - **新增报警机制**：如果 CI 保持全绿，但 nightly 出现大面积失败，自动触发 **`SCHEMA_DRIFT_ALERT`**。
- **验收**：
  - P0 case 在 CI 或 nightly 中至少有一个强制闸口。
  - 触发 `SCHEMA_DRIFT_ALERT` 时，自动冻结相关 Golden Set 的 Pass 结论，并通知对应群组。

---

## 3. Sprint 2：语义算子深化与上下文治理

### BE-101：语义算子 deterministic 单测与容错

- **负责人**：Backend
- **涉及算子**：
  - Q5：`set_difference`
  - Q8：`consecutive_growth`
  - Q9：`all_period_condition`
- **任务约束**：
  - 单测绝对不依赖 LLM。
  - 优先使用标准库和轻量集合逻辑。**非必要不引入 Pandas**（除非数据量大且项目已有强依赖）。
  - 强化容错：算子在遇到周期缺失、字段缺失、异常空值时**禁止 Crash**，必须安全捕获并抛出 `DATA_CONTINUITY_ERROR`，降级为友好的错误提示。
- **验收**：
  - 覆盖语义反向、首尾比较冒充连续增长、任一周期冒充全周期。
  - 异常数据输入时稳定抛出对应的 Error 分类，而非 500。

### BE-102：Q2/Q4 上下文继承测试套件

- **负责人**：Backend + QA
- **任务**：
  - 同 session 执行多轮问题。
  - 验证指标、维度、过滤条件、时间范围继承。
  - fallback 情况保留 `needs_review`。
- **验收**：
  - Q2/Q4 上下文丢失时测试失败。

### PM-101：Metrics Registry 前置约束与 Virtual Registry (Escape Hatch)

- **负责人**：PM + Backend
- **任务**：
  - 原则上，在正式的 Metrics Registry 产品化前，冻结所有宽泛的 Python 派生指标公式新增。
  - 设立极窄的白名单逃生舱 (**Virtual Metrics Registry**)：允许少量临时派生指标上线，但必须包含明确的 owner、公式版本、来源说明、审批人、过期时间 (TTL) 和单测覆盖。
- **验收**：
  - Code review checklist 中加入“Python 派生指标冻结与 Virtual Registry 审查”项。
  - 逃生舱指标在正式 Registry 上线后具备清晰的迁移路径。

---

## 4. 任务执行顺序

1. QA-001：先补 Golden Set 元数据和 baseline。
2. BE-002：先做 Result Guardrail 独立模块与单测。
3. BE-005：补 MCP Result 前置资源闸口，避免后置 Result Guardrail 判断前 OOM。
4. BE-003：接入问数链路。
5. BE-004：补 trace、语义状态和多维指标。
6. BE-001：接入 benchmark harness。
7. DEVOPS-001：挂 CI/nightly 与 Schema Drift Alert。
8. BE-101 / BE-102：进入 Sprint 2。
9. PM-101：同步进入评审 checklist。

---

## 5. Coder 执行要求

- 开始写代码前必须阅读：
  - `docs/specs/56-homepage-data-qa-guardrails-spec.md`
  - `docs/specs/testcases/56-homepage-data-qa-golden-set-test-cases.md`
- Result Guardrail 必须独立于 `mcp_args_guardrail.py`。
- Result Guardrail 前必须有 executor/network 层资源上限，不能等大结果完整进入 Python 内存后再阻断。
- 不允许用 LLM 判断 Golden Set 是否通过。
- 不允许把 fallback 自动判为成功。
- 不允许 Renderer 总结被 Result Guardrail block 的数据。
- 不允许在 Metrics Registry 未落地前新增宽泛 Python 派生指标计算。

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| QA baseline 补录不完整 | Golden Set 无法判定 | P0 case 先补齐，P1 后续补 |
| 真实链路测试不稳定 | CI 波动 | CI mocked fixture，nightly 跑真实链路 |
| Result Guardrail 误拦截 | 用户体验下降 | P0 先 block detail scan，其余先 review |
| fallback 数量过高 | 掩盖主路质量问题 | 单独统计 fallback rate 和 `needs_review` |
| Python 派生指标继续扩张 | 口径漂移 | Code review checklist + Metrics Registry 前置 |
