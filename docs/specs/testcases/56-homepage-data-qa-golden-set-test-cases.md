# Spec 56 测试用例：Homepage Data QA Golden Set

> 版本：v0.1 | 日期：2026-05-16 | 关联 Spec：`docs/specs/56-homepage-data-qa-guardrails-spec.md`

---

## 1. 用例目标

将 Batch 2 的 Q0-Q10 沉淀为首页问数第一组 Data QA Golden Set，用于验证：

- Mulan 结果准确性不低于 MCP baseline。
- fallback 不被自动视为业务成功。
- 语义算子、上下文继承和 detail scan 风险可自动回归。

---

## 2. 用例元数据格式

建议 fixture 路径：

```text
backend/tests/fixtures/data_agent_golden_set/batch2_q0_q10.yaml
```

每个 case 必须包含：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | Y | Q0-Q10 |
| `priority` | Y | P0/P1 |
| `question` | Y | 用户原始问题 |
| `session_group` | Y | 同会话追问分组 |
| `turn_index` | Y | 多轮中的轮次 |
| `expected_operator` | Y | aggregate / set_difference / consecutive_growth / all_period_condition 等 |
| `mcp_baseline.row_count` | Y | MCP baseline 行数 |
| `mcp_baseline.core_fields` | Y | 核心字段 |
| `mcp_baseline.core_values` | Y | 核心值或 TopN 核心值 |
| `mcp_baseline.grain` | Y | 结果粒度 |
| `assertions` | Y | 确定性断言 |
| `failure_tags` | Y | 失败分类标签 |

---

## 3. Batch 2 种子用例矩阵

| Case | 优先级 | 类型 | 验收重点 | 状态 |
|------|--------|------|----------|------|
| Q0 | P1 | baseline aggregate | QA 补录 MCP baseline、row count、核心字段值 | 待补录 |
| Q1 | P1 | baseline aggregate | QA 补录 MCP baseline、row count、核心字段值 | 待补录 |
| Q2 | P0 | context follow-up | 继承上轮指标、维度、过滤条件或时间范围 | 待补录 |
| Q3 | P1 | baseline aggregate | QA 补录 MCP baseline、row count、核心字段值 | 待补录 |
| Q4 | P0 | context follow-up | 同会话追问不得丢上下文 | 待补录 |
| Q5 | P0 | set_difference | 差集方向正确，不得反向查成发生销售 TopN | 待补录 |
| Q6 | P1 | operator/aggregate | QA 补录 Batch 2 失败或通过判定 | 待补录 |
| Q7 | P1 | operator/aggregate | QA 补录 Batch 2 失败或通过判定 | 待补录 |
| Q8 | P0 | consecutive_growth | “连续增长/每年都”必须验证全相邻周期 | 待补录 |
| Q9 | P0 | all_period_condition | “一直/全周期/每年”必须覆盖所有目标周期 | 待补录 |
| Q10 | P0 | detail_scan_guardrail | 不得返回大批原始明细后由 LLM 总结 | 待补录 |

---

## 4. P0 断言模板

### Q2 / Q4：上下文追问

必须断言：

- `session_group` 相同。
- 当前轮能继承上一轮必要指标、维度、过滤条件和时间范围。
- 结果字段覆盖追问所需的核心字段。
- 若 fallback 触发，默认 `semantic_status=needs_review`，不得直接判成功。

### Q5：差集

必须断言：

- `expected_operator=set_difference`。
- 断言中明确 minuend/subtrahend 的业务方向。
- 结果不得包含反向集合。
- 不允许只返回 TopN 发生销售结果冒充差集。

### Q8：连续增长

必须断言：

- `expected_operator=consecutive_growth`。
- 每个相邻周期都满足增长条件。
- 不允许只比较首尾周期。
- 不允许只返回增长额 TopN。

### Q9：全周期条件

必须断言：

- `expected_operator=all_period_condition`。
- 检查覆盖所有目标周期。
- 不允许任一周期满足即通过。

### Q10：明细扫描

必须断言：

- 用户问题如果需要聚合/条件/总结，结果不得是超过阈值的原始明细。
- 命中阈值时必须输出 `DETAIL_SCAN_BLOCKED`。
- Renderer 不得继续生成自然语言业务总结。

---

## 5. 失败分类标签

| 标签 | 含义 |
|------|------|
| `semantic_reversal` | 语义方向反了，例如差集反查。 |
| `context_loss` | 多轮追问丢失上下文。 |
| `detail_scan` | 返回不合理明细结果。 |
| `grain_mismatch` | 粒度错误。 |
| `field_missing` | 核心字段缺失。 |
| `metric_drift` | 指标口径漂移。 |
| `fallback_unverified` | fallback 有返回但未通过语义校验。 |
| `renderer_misleading` | Renderer 总结误导或掩盖数据问题。 |

---

## 6. 通过标准

- P0 case 全部通过，才允许进入 100 人试用。
- P1 case 可在 nightly 中持续补齐，但不得阻塞 Sprint 1 的 P0 闸口。
- QA 未补录 baseline 的 case 不得标记为 `semantic_pass`。
