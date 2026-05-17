# SPEC: Reconcile Tableau Catalog Fields And MCP Queryable Fields

> Version: v0.1 | Status: proposed | Change: `reconcile-tableau-mcp-fields`

## 1. Overview

MULAN must distinguish Tableau asset catalog fields from MCP queryable fields.

The asset catalog may contain more fields than Tableau MCP exposes for `query-datasource`. Data Agent must use MCP queryable fields as the execution contract, while using catalog fields only for routing and explanation.

## 2. Non-Goals

- Do not remove catalog-only fields from Tableau asset pages.
- Do not overwrite catalog fields with the MCP field subset.
- Do not require users to manually resolve field availability.
- Do not change the Tableau connection/MCP binding architecture.

## 3. Acceptance Criteria

1. Asset `422`-style cases show both catalog count and Agent-queryable count.
2. Field rows expose a queryability status.
3. Data Agent planning receives only MCP queryable fields as executable fields.
4. If a user asks for a catalog-only field, Data Agent returns a clear preflight message before MCP query execution.
5. MCP metadata failures do not delete, hide, or overwrite catalog fields.
6. Tests cover catalog-only conflict and queryable-field success paths.

## 4. Change Budget

- Backend API: medium.
- DB migration: medium.
- Data Agent prompt/guardrail: medium-high.
- Frontend asset field UI: medium.
- No broad refactor of Agent runner or Tableau sync architecture.

## 5. Design

### 5.1 Field States

Each Tableau datasource field may be:

- `queryable`: present in catalog and MCP queryable fields.
- `catalog_only`: present in catalog but absent from MCP queryable fields.
- `mcp_only`: present in MCP but absent from catalog; diagnostic only for MVP.
- `unknown`: MCP has not been checked.
- `error`: last MCP check failed.

### 5.2 Backend Storage

MVP preferred storage:

```text
tableau_datasource_fields.mcp_queryable boolean null
tableau_datasource_fields.mcp_field_name varchar null
tableau_datasource_fields.mcp_field_caption varchar null
tableau_datasource_fields.mcp_checked_at timestamp null
tableau_datasource_fields.mcp_last_error text null
```

Coder may choose a separate capability table only if migration review finds column extension risky.

### 5.3 API Contract

`GET /api/tableau/assets/{asset_id}/fields` returns:

```json
{
  "catalog_field_count": 32,
  "queryable_field_count": 11,
  "catalog_only_count": 21,
  "mcp_status": "partial",
  "fields": [
    {
      "field": "订单日期",
      "mcp_queryable": false,
      "queryability_status": "catalog_only"
    }
  ]
}
```

Existing `fields` properties must remain backward compatible.

### 5.4 Data Agent Preflight

Before query planning:

1. Use catalog fields to detect user-mentioned fields.
2. Use queryable fields as executable field set.
3. If mentioned field is catalog-only:
   - Return structured clarification/error.
   - Include alternatives from queryable fields.
   - Do not call `query-datasource`.

### 5.5 Frontend

Asset fields table must show:

- Field name/type/role as today.
- Queryability badge.
- Summary counts.
- Last MCP check status/error.

## 6. Mocks & Fixtures

Required backend fixture:

```text
asset_id: 422-like fixture
catalog_fields: 32
queryable_fields: 11
catalog_only_fields includes: 订单日期, 数量, 区域
queryable_fields includes: 发货日期, 发货年份, 销售额, 利润
```

Required frontend fixture:

```json
{
  "catalog_field_count": 32,
  "queryable_field_count": 11,
  "catalog_only_count": 21,
  "fields": [
    {"field": "订单日期", "queryability_status": "catalog_only"},
    {"field": "销售额", "queryability_status": "queryable"}
  ]
}
```
