# Mulan vs MCP A/B 对齐测试 — data_agent_Q&A Batch 2

**日期**: 2026-05-15
**数据源**: Tableau Online — `订单+ (示例 - 超市)` (luid: `f4290485-26d3-428f-aa8d-ccc33862a411`)
**MCP 网关**: `http://localhost:3930` (Online Gateway, PAT `mcp_test_0419`)
**Mulan 接口**: `POST /api/search/query`
**测试范围**: Q0 ~ Q10

---

## 一、测试总览

### 环境

| 项目 | 值 |
|------|---|
| MCP Gateway | `http://localhost:3930` (Tableau Online, site: `zy_bi`) |
| Mulan Backend | `http://localhost:8000` |
| 数据源 | Tableau Online — `订单+ (示例 - 超市)` |
| 连接 ID (Mulan) | `Tableau-online` (id=2) |
| 数据模型 | 11 字段；销售额/利润/利润率/客单价/客户数/子类别/年份/省份/类别 |

### 通过率

| 指标 | 值 |
|------|---|
| Mulan 端到端 Pass | **1 / 10 (10%)** |
| MCP Baseline 实际可执行查询 | **4 / 10 (40%)**（Q0 元数据、Q1-Q3 聚合查询；Q4-Q10 无执行） |
| MCP 路由触发 | **1 / 10**（Q6 触发 tableau_mcp；Q1-Q5/Q7-Q10 全部 `no_mcp`） |
| 质量门 Pass | **0 / 9** |

> MCP Baseline 本身 Q1-Q4 有原始查询结果，说明通过某种机制（在线连接分析）取得了数据。Mulan 侧 Q1-Q10 全部在 QuerySpec 生成阶段失败。

### 根因总结

**Mulan 端到端全链路失败**，所有失败都发生在同一层：

```
llm_queryspec → LLM_500 (MiniMax-M2.7 Anthropic API timeout)
    ↓
queryspec_validator → QS_LLM_INVALID
    ↓
fallback_disabled=true（兜底被禁用）
    ↓
最终响应: "LLM 未生成可执行的 QuerySpec"
```

Q6 特殊性：`baseline_mcp_execution` 通过（触发了 `tableau_mcp` 工具），但 `MCP_ARGS_GUARDRAIL_PASS` 缺失。

---

## 二、基准对照表

| Q | MCP 时长 (ms) | Mulan 时长 (ms) | Mulan 行数 | MCP 核心结论 | Mulan 核心结论 | 状态 |
|---|-------------|---------------|-----------|------------|--------------|------|
| Q0 | 3,003 | 1,595 | 11 (字段) | 11 字段，销售额/利润/利润率/客单价/客户名称/子类别等 | 11 字段（路由: schema_inventory） | ✅ 一致 |
| Q1 | 1,426 | 27,950 | null | 销售额 1686.74 万，利润 211.92 万，利润率 12.56%，客户 771，客单价 2.19 万 | `QS_LLM_INVALID` — LLM_500，QuerySpec 生成失败 | ❌ |
| Q2 | 1,194 | 30,623 | null | 2021-2024 趋势：347.86万→349.63万→446.64万→538.73万 | `QS_LLM_INVALID` — LLM_500 | ❌ |
| Q3 | 1,254 | — | null | 17 个子类别；桌子亏损 12.87 万、书架亏损 2.63 万 | `QS_LLM_INVALID` | ❌ |
| Q4 | 1,445 | — | null | 80 行子类别×年份交叉；书架 2021-2024 持续亏损 | `QS_LLM_INVALID` | ❌ |
| Q5 | — | — | null | 5 个子类别 2025 无销售记录 | `QS_LLM_INVALID` | ❌ |
| Q6 | — | — | 10 | Top10 大客户（客户名称/销售额/占比） | MCP 触发但 Guardrail 缺失，row_count=10 | ⚠️ 部分 |
| Q7 | — | — | null | 邓保 2 年合作记录 | `QS_LLM_INVALID` | ❌ |
| Q8 | — | — | null | 5 个子类别利润每年持续增长 | `QS_LLM_INVALID` | ❌ |
| Q9 | — | — | null | 1 个省份所有年份均亏损 | `QS_LLM_INVALID` | ❌ |
| Q10 | — | — | null | 辽宁/福建 2024 产品线+客户亏损明细 | `QS_LLM_INVALID` | ❌ |

---

## 三、质量观察

### 1. Pushdown（算子下推）

**现象**：MCP Baseline 原始数据本身为 Tableau REST API / VizQL 查询结果，字段包含 `SUM(销售额)`, `COUNTD(客户名称)` 等聚合表达。Mulan 在元数据阶段（Q0 schema inventory）成功路由到 `schema` 工具并返回 11 字段，但在 QuerySpec 生成阶段完全失败。

**问题**：
- Mulan 对 Q1 "整体的销售额..." 的问法，路由为 `data_query`（正确），intent 识别为 `aggregate`（正确），但 LLM QuerySpec 生成阶段触发 `LLM_500` 超时
- 失败点不在 MCP 连接层，在 LLM 层——QuerySpec 本身无法生成，导致后续所有 MCP 调用无法发生

### 2. 语义算子

**现象**：MCP Baseline 的聚合字段完全符合预期：
- `SUM(销售额)`, `SUM(利润)`, `COUNTD(客户名称)` — 标准聚合
- `利润率 = SUM([利润])/SUM([销售额])` — 派生计算
- `客单价 = SUM([销售额])/[客户数]` — 派生计算

Mulan 在 Q0 成功识别了这 11 个字段的名称、类型、角色（dimension/measure）、是否计算字段。元数据层表达正确。

### 3. Intent 与路由

| Q | Intent 识别 | Guardrail 决策 | 路由策略 | 问题 |
|---|-----------|--------------|---------|------|
| Q0 | `aggregate` → `schema_inventory` | `asset_metadata_pattern` → allow | `schema_only` | ✅ |
| Q1 | `aggregate` | `metric_keyword` → allow | `data_query` | ❌ LLM_500 |
| Q2 | `trend_condition` | `data_action_pattern` → allow | `data_query` | ❌ LLM_500 |
| Q3 | (同失败) | — | — | ❌ LLM_500 |
| Q4 | (同失败) | — | — | ❌ LLM_500 |
| Q6 | (部分通过) | 缺失 `MCP_ARGS_GUARDRAIL_PASS` | `tableau_mcp` 触发 | ⚠️ Guardrail |

**关键**：Q6 是唯一触发 MCP 工具的案例，但因 Guardrail trace 缺失导致质量门 block。说明 MCP 工具链（tableau_mcp → answer_renderer → queryspec_validator）本身是可工作的。

### 4. 上下文断层

**现象**：Mulan 的多轮对话上下文链完整（`conversation_id` 持续为 `ad643a50-b876-439e-aa8c-6fdd6df0e577`），但每个问题都是独立处理，上下文继承体现在 trace_id 漂移上（Q1: `t-f685464c` → Q2: `t-14d336a8`），而非语义层面的上下文传递。

Q2 "这个指标过去几年的趋势" 没有继承 Q1 的指标定义，是独立识别为 `trend_condition`，没有从上一轮获取 `SUM(销售额)`。

---

## 四、阻塞项与下一步

### 核心阻塞

```
BLOCKER-1: LLM 层不可用
  代码: QS_LLM_INVALID
  原因: MiniMax-M2.7 的 Anthropic API 调用超时
  影响: 9/10 数据查询问题无法生成 QuerySpec
  建议: 修复 MiniMax provider 超时配置或切换备用 LLM

BLOCKER-2: MCP 工具链 Guardrail Trace 缺失
  代码: MCP_ARGS_GUARDRAIL_PASS 事件未记录
  影响: Q6 等本可工作的路径被质量门 block
  建议: 在 tableau_mcp 工具调用后添加 guardrail pass trace 事件

BLOCKER-3: MCP Online Gateway 无查询工具
  现状: Online Gateway (port 3930) 只有元数据工具（list/get_detail），无 query-datasource
  实际查询通过 tableau-data MCP 走 ksyun 站点
  建议: 为 Online MCP Gateway 添加 query 工具，或确保 Mulan 使用正确的 MCP 连接
```

### 非阻塞观察

- **Q0 schema inventory**：Mulan 路由完全正确，11 字段全部对齐 MCP baseline
- **Q6 MCP 触发**：说明 tableau_mcp 工具链在特定条件下可工作
- **失败模式一致**：所有失败均为 LLM 层超时，无脏数据或语义反转

### 下一步

1. **立即**：修复 MiniMax API 超时（增加 timeout 或启用 fallback）
2. **P0**：为 Online MCP Gateway 添加 `query-datasource` 工具，使 MCP Baseline 与 Mulan 使用相同的查询路径
3. **P1**：补充 Q6 Guardrail trace `MCP_ARGS_GUARDRAIL_PASS` 事件
4. **P2**：多轮上下文继承——Q2 应继承 Q1 的指标定义，而非独立识别

---

*生成时间: 2026-05-15T19:00:00+08:00*
*数据来源: inbox/20260515-13-abtest-raw.json, inbox/20260515-15-mcp-accuracy-quality-report.json*
