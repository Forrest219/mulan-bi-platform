# Reconcile Tableau Catalog Fields And MCP Queryable Fields

> Status: proposed

## Why

Tableau 资产页展示的是 `tableau_datasource_fields` 中的资产目录字段，但首页 Data Agent 执行 Tableau 问数时实际受 MCP `get-datasource-metadata` 返回的 queryable fields 约束。

已验证资产 `422`（`订单+ (示例 - 超市)`）存在明显差异：

- `tableau_datasource_fields`: 32 个字段。
- MCP metadata queryable fields: 11 个字段。
- 21 个资产字段不在当前 MCP 可查询字段内，例如 `订单日期`、`数量`、`区域`、`折扣`、`订单 Id`、`客户 Id`。

如果用户在首页 Data Agent 提问时使用这些 catalog-only 字段，系统会先基于资产目录路由到正确数据源，但后续 MCP 查询 guardrail 会认为字段不可查询，导致字段冲突、拒绝、自动修复或答非所问。

## What Changes

- 明确字段分层：
  - `catalog_fields`: Tableau 资产目录字段，用于资产页、治理、搜索、数据源路由。
  - `queryable_fields`: MCP 当前可查询字段，用于 Data Agent 查询规划、prompt 注入、guardrail 校验和 `query-datasource` 执行。
- 资产页展示字段查询能力状态，避免用户误认为资产目录字段都能被 Agent 查询。
- Data Agent 查询前增加字段 preflight：用户提及字段若只存在于 catalog fields、不存在于 queryable fields，提前返回可解释的冲突提示和替代字段建议。
- 同步/刷新流程增加 MCP metadata reconciliation，保存 catalog/queryable 差异，不能用 MCP 少量字段覆盖完整资产目录字段。
- 保持数据源路由可使用 catalog fields，但进入查询规划后必须以 queryable fields 为准。

## Non-Goals

- 不把 MCP queryable fields 覆盖写成 Tableau 资产的完整字段列表。
- 不要求用户手动配置或选择 MCP 字段。
- 不在本变更中解决 Tableau MCP 官方返回字段少的根因。
- 不改变 Tableau 资产同步对工作簿、视图、数据源资产的主流程。
- 不把首页 Data Agent 改造成完整 MCP Host；本变更只处理字段语义一致性和冲突解释。

## User Impact

- 资产页用户能看到哪些字段“Agent 可查询”、哪些字段“仅资产目录可见”。
- 首页 Data Agent 在遇到 catalog-only 字段时给出明确说明，而不是产生隐式字段冲突。
- 问数链路更稳定：不会因为资产目录字段更全而诱导 LLM 生成 MCP 无法执行的查询。

## Success Metrics

- 对资产 `422`，资产页能同时显示 32 个 catalog fields 与 11 个 queryable fields 的关系。
- 用户询问 `订单日期`、`数量`、`区域` 等 catalog-only 字段时，Data Agent 返回“字段存在但当前 MCP 不可查询”的解释，并给出可替代字段。
- 用户询问 `销售额`、`利润`、`类别` 等 queryable 字段时，Data Agent 可以继续正常生成 MCP 查询。
- Data Agent 的 `queryable_fields` prompt/guardrail 不再混入 catalog-only 字段。
