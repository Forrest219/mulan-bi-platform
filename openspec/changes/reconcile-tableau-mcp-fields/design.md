# Design

## Current Verified Behavior

资产 `422`（`订单+ (示例 - 超市)`）验证结果：

| 来源 | 字段数 | 用途 |
|---|---:|---|
| `tableau_datasource_fields` | 32 | 资产目录、治理、搜索、数据源路由 |
| MCP `get-datasource-metadata` | 11 | Data Agent 可查询字段、MCP query guardrail |

MCP queryable fields:

```text
客单价、利润率、客户数、子类别、发货年份、发货日期、销售额、利润、客户名称、省/自治区、类别
```

Catalog-only examples:

```text
订单日期、数量、区域、折扣、订单 Id、客户 Id、城市、产品名称、装运模式
```

## Field Semantics

### Catalog Fields

Catalog fields are the platform's asset inventory:

- Source: Tableau asset sync / metadata cache.
- Storage: `tableau_datasource_fields`.
- User-facing surface: `/assets/tableau/:id`, governance, semantic maintenance, search.
- Agent use: datasource routing and explanatory context.

### Queryable Fields

Queryable fields are the runtime contract for `query-datasource`:

- Source: MCP `get-datasource-metadata`.
- Storage: reconciliation result, not a replacement for catalog fields.
- User-facing surface: Agent availability status on asset fields.
- Agent use: prompt, query planning, preflight, guardrail, MCP execution.

## Implementation Decision

MVP uses nullable capability columns on `tableau_datasource_fields`; no separate reconciliation table is introduced.

Implemented columns:

```text
mcp_queryable boolean null
mcp_field_name varchar(256) null
mcp_field_caption varchar(256) null
mcp_checked_at timestamp null
mcp_last_error text null
```

`mcp_queryable = null` means MCP queryability has not been checked. `false` is used only after successful MCP metadata reconciliation confirms the catalog field is not present in MCP queryable fields. MCP failures set `mcp_last_error` / `mcp_checked_at` and do not delete or overwrite catalog fields.

Shared field extraction lives in `backend/services/tableau/mcp_metadata_fields.py`; Data Agent guardrail and reconciliation reuse it instead of importing private helpers from `query_tool.py`.

## Proposed Data Shape

Preferred MVP option: extend `tableau_datasource_fields` with capability metadata.

```text
mcp_queryable boolean null
mcp_field_name varchar null
mcp_field_caption varchar null
mcp_checked_at timestamp null
mcp_last_error text null
```

Asset-level API response should include:

```json
{
  "field_count": 32,
  "catalog_field_count": 32,
  "queryable_field_count": 11,
  "catalog_only_count": 21,
  "mcp_checked_at": "2026-05-17T07:06:00Z",
  "mcp_status": "partial",
  "fields": [
    {
      "field": "订单日期",
      "mcp_queryable": false,
      "queryability_status": "catalog_only"
    },
    {
      "field": "销售额",
      "mcp_queryable": true,
      "queryability_status": "queryable"
    }
  ]
}
```

If the team prefers avoiding nullable columns on a busy table, use a separate table:

```text
tableau_datasource_field_capabilities
- id
- asset_id
- datasource_luid
- field_name
- field_caption
- mcp_queryable
- mcp_field_payload jsonb
- checked_at
- last_error
```

Architect recommendation for MVP: extend `tableau_datasource_fields` unless migration risk is higher than expected. It keeps API serialization simple and avoids joining for every asset field page.

## Reconciliation Algorithm

1. Load catalog fields by `asset_id`.
2. Call MCP `get-datasource-metadata(datasource_luid)`.
3. Extract queryable field names using the same extraction logic used by Data Agent.
4. Normalize names with compact/casefold rules.
5. Mark:
   - `queryable`: catalog field matched MCP field.
   - `catalog_only`: catalog field did not match MCP.
   - `mcp_only`: MCP field did not match catalog; include in response diagnostics but do not create a catalog field unless explicitly required later.
6. Save `mcp_checked_at` and errors.

## Data Agent Behavior

### Routing

Datasource routing may use catalog fields because catalog fields are broader and help identify the intended datasource.

### Planning

Planning must use queryable fields only. The prompt must clearly label them:

```text
queryable_fields: fields that MCP query-datasource can execute.
catalog_only_fields: fields visible in Tableau asset catalog but currently not queryable by Agent.
```

### Preflight

Before LLM query planning or before accepting LLM-generated args:

1. Extract user-mentioned fields using existing field matching utilities.
2. If a field matches catalog-only but not queryable:
   - Stop before MCP query.
   - Return a structured clarification/error.
   - Include closest queryable alternatives.

Example response:

```text
我找到了字段“订单日期”，但当前 Tableau MCP 不支持直接查询该字段。
当前可查询的时间字段有：发货日期、发货年份。
是否改用“发货日期”继续分析？
```

## Frontend Behavior

On `/assets/tableau/:id`:

- Show all catalog fields.
- Add a compact status badge:
  - `Agent 可查询`
  - `仅资产目录`
  - `未校验`
  - `MCP 异常`
- Add a field summary:
  - `资产字段 32`
  - `Agent 可查询 11`
  - `仅资产目录 21`

Do not hide catalog-only fields. Hiding them would make governance users think the asset sync is incomplete.

## Risks

- MCP metadata may be temporarily unavailable; reconciliation must be best-effort.
- Field aliases may differ between catalog and MCP metadata. Matching must preserve raw names and expose mismatch diagnostics.
- Returning too many catalog-only fields in Data Agent prompt may confuse LLM. Prompt should keep catalog-only summary short and only include fields relevant to the user question.
