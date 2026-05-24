# OSI Semantic Model Integration — Proposal

**Change ID**: `osi-semantic-model-integration`
**Author**: Forrest
**Created**: 2026-05-24
**Status**: Draft
**PR**: (to be assigned after review)

---

## 1. Problem Statement

Mulan 当前的 metric 定义分散在三个地方，导致口径不一致、AI 幻觉难以控制：

| 位置 | 问题 |
|------|------|
| `bi_metric_definitions` 表 | 扁平结构，无嵌套语义；过滤逻辑依赖 SQL hardcode |
| `semantic_maintenance` 上下文 | `ai_context` 散落在各处理函数，无标准格式 |
| `llm/prompts.py` | 业务规则以字符串注入 Prompt，LLM 无法校验 |

**根本问题**：没有统一的语义定义标准格式，各模块各自维护"业务语义"，跨模块一致性无法保证。

---

## 2. Goals

1. 引入 **OSI（Open Semantic Interchange）YAML 格式**作为 Mulan 语义模型的唯一标准定义格式
2. 各模块（metrics / semantic_maintenance / nlq_service）从 OSI YAML 读取语义，不再各自维护
3. LLM 生成 SQL 时自动继承 OSI `filters` 和 `ai_context` 定义的业务规则，消除 hardcode
4. 支持多 SQL 方言（ANSI / Snowflake / Databricks），通过 `expression.dialects` 切换

---

## 3. Scope

### In Scope

- **`backend/services/metrics/`** — 接入 OSI 格式作为 metric 定义源
- **`backend/services/semantic_maintenance/`** — 改造为 OSI `ai_context` consumer
- **`backend/services/llm/nlq_service.py`** — 在 Prompt 组装阶段注入 OSI 语义上下文
- **新增 `backend/services/osi_parser/`** — OSI YAML 解析器（轻量，无外部依赖）
- **`bi_metric_definitions` 表兼容策略** — 双写过渡期，最终迁移到 OSI YAML

### Out of Scope

- OSI Converter 开发（Snowflake / dbt / Databricks 等外部 converter）
- Web UI 编辑器（后期 Roadmap）
- Ontology 层（OSI Roadmap 后期方向）

---

## 4. Motivation Details

### OSI 是什么

OSI（Open Semantic Interchange）是一个**厂商无关的语义模型交换标准**，核心是 YAML 格式的语义模型定义：

```yaml
semantic_model:
  - name: ecommerce_sales
    datasets:
      - name: orders
        source: sales.public.orders
        primary_key: [order_id]
        fields:
          - name: amount
          - name: is_returned
          - name: order_date
            dimension:
              dimension_type: time
    metrics:
      - name: total_revenue
        aggregation_method: sum
        expression:
          dialects:
            ansi_sql: "sum(amount)"
        filters:
          - expr: "is_returned = false"
            dialect: ansi_sql
    ai_context:
      instructions: "当查询销售额时，必须确保过滤掉 is_returned 为 true 的订单。"
```

### 为什么是 OSI

1. **结构对齐**：OSI 的 `semantic_model / datasets / metrics / fields / ai_context` 与 Mulan 现有模块高度对应，改造成本最低
2. **生态潜力**：已有 Snowflake / dbt / Salesforce / Databricks / Polaris / GoodData converter，生态持续扩展
3. **AI-Native 设计**：`ai_context` 字段专为 LLM 设计，Mulan 的 NL2SQL 可以直接受益
4. **Hub-and-Spoke 架构**：N 个 vendor 只需 2N 个 converter，新增方言零额外成本

### 为什么不是现在

- OSI 仍为 **Draft 0.2.0.dev**，正式 release 前 schema 可能变化
- 需要设计**兼容策略**：在 OSI 正式版发布前，双写 OSI YAML 和现有 `bi_metric_definitions`
- `expression.dialects` 目前只支持 6 种方言（ansi_sql / snowflake / databricks / tableau / mdx / maql），StarRocks 等需要 converter

---

## 5. Success Criteria

| # | 指标 | 验证方式 |
|---|------|---------|
| 1 | 核心 metric（`total_revenue` / `order_count`）用 OSI YAML 定义并通过 `osi-schema.json` 校验 | `validate.py` 通过 |
| 2 | LLM 生成 SQL 时，`is_returned = false` 过滤条件自动注入，无 hardcode | NL2SQL 单元测试 |
| 3 | `expression.dialects` 支持 ansi_sql 和 snowflake 两种方言切换 | 方言切换测试 |
| 4 | 各模块（metrics / semantic_maintenance / nlq_service）从同一份 OSI YAML 读取语义 | 集成测试 |
| 5 | 与现有 `bi_metric_definitions` 双写兼容，无数据丢失 | 回归测试 |

---

## 6. Risk & Mitigations

| 风险 | 级别 | 缓解措施 |
|------|------|---------|
| OSI schema 在 0.2.0 正式发布前变化 | 中 | 双写策略 + schema 版本锁定；变化时通过 OSI converter 迁移 |
| LLM 生成 SQL 未遵循 OSI filters | 中 | 增加 NL2SQL 单元测试覆盖；Prompt 中明确引用 `ai_context.instructions` |
| `bi_metric_definitions` 历史数据迁移复杂 | 低 | 双写过渡期，历史数据只读不写；分批迁移 |

---

## 7. Non-Goals

- 不在本次实现一个 OSI Web UI 编辑器（留给后期社区贡献）
- 不实现完整的 OSI Converter 生态（只接入 Mulan 内部消费，不做 export）
- 不改变现有 API 契约（所有改动内部完成，对前端透明）

---

## 8. Open Questions

## 8. Resolved Decisions

> 以下问题已通过评审决策确定，不再作为 Open Questions。

| # | 问题 | 决策 |
|---|------|------|
| 1 | OSI YAML 持久化方案 | **PostgreSQL**（yaml_content TEXT + parsed_json JSONB），文件系统降为 seed/import/export |
| 2 | 是否需要版本化 | **是，P0 必须**，每份 OSI 文档独立版本化 |
| 3 | 热重载策略 | **cache invalidation**，通过 version_id / updated_at，不依赖文件系统监听 |
| 4 | 多租户支持 | **P1 前期预留**，设计需考虑 tenant_id，暂不实现多租户隔离 |
| 5 | `bi_metric_definitions` 迁移 | **P2 任务**，待细化分批策略 |
| 6 | NLQ 边界 | **P0 必须修正**，NLQService 只走 ContextAssembler，不直接调用 OSIParser |

## 9. Dependencies

- `osi-schema.json`（从 `repos/OSI/core-spec/` 复制到 `backend/services/osi_parser/`）
- `validation/validate.py`（参考实现，可能需要适配 Python 3.10+）
- `sqlglot`（已引入，处理 `expression.dialects` 方言转换）

---

## 10. Related Changes

- `openspec/changes/metrics-agent-spec`（§30 Metrics Agent）- 已有 `bi_metric_definitions` 定义，本次是增强
- `openspec/changes/data-agent-architecture`（§28 Data Agent）- NL2SQL 链路，本次影响其 Prompt 组装逻辑