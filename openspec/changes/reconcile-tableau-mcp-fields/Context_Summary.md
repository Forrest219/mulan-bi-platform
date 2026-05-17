# Context Summary

## Relevant Files

- `backend/services/llm/nlq_service.py`
  - `route_datasource()` uses `tableau_assets` and cached `tableau_datasource_fields` for datasource routing.
  - `get_datasource_fields_cached()` reads `TableauDatasourceField` and caches field captions.
- `backend/services/data_agent/mcp_first_main.py`
  - `_queryable_field_context()` prefers MCP `get_datasource_metadata()` and falls back to local field cache only when MCP metadata is unavailable.
- `backend/services/data_agent/mcp_proxy_main.py`
  - Uses `_queryable_fields()` to build the MCP tool prompt and field count.
- `backend/services/data_agent/mcp_args_guardrail.py`
  - Validates MCP query args against `queryable_fields`.
- `backend/app/api/tableau.py`
  - `/api/tableau/assets/{asset_id}/fields` returns cached catalog fields.
  - `/api/tableau/datasources/{asset_id}/metadata` refreshes metadata via MCP.
- `frontend/src/api/tableau.ts`
  - Defines `TableauAssetField` and metadata response types used by the asset page.

## Current Behavior

- Homepage Data Agent does not call `/assets/tableau`; it enters through `/api/agent/stream`.
- Datasource routing uses local Tableau asset/cache data.
- MCP query planning uses MCP queryable fields when available.
- Asset page shows catalog fields without indicating whether each field is queryable by Agent.

## Verified Example

Asset `422`:

- Name: `订单+ (示例 - 超市)`
- Type: `datasource`
- Connection: `4`
- Tableau LUID: `f4290485-26d3-428f-aa8d-ccc33862a411`

Verification result:

- Local catalog fields: 32.
- MCP queryable fields: 11.
- Catalog-only fields: 21.

MCP queryable fields:

```text
客单价、利润率、客户数、子类别、发货年份、发货日期、销售额、利润、客户名称、省/自治区、类别
```

Catalog-only examples:

```text
区域 (人员)、退回、产品 Id、城市、订单日期、装运模式、区域经理、国家/地区、区域、产品名称、邮政编码、折扣、订单 Id、数量、细分、行 Id、客户 Id
```

## Dependency/Call Chain

```text
Home AskBar
→ useStreamingChat
→ POST /api/agent/stream
→ route_datasource()
→ tableau_assets + tableau_datasource_fields
→ _queryable_field_context()
→ TableauMCPClient.get_datasource_metadata()
→ MCP queryable_fields
→ query planning / mcp_args_guardrail
→ TableauMCPClient.query_datasource()
```

## Existing Constraints

- Full catalog fields must remain available for asset governance.
- Query planning must not use fields MCP cannot query.
- MCP failures must not delete or shrink the catalog field list.
- User-facing behavior must explain field availability instead of failing with opaque field mismatch errors.

## Potential Risks

- Field names may have aliases or localized captions; reconciliation needs normalized matching plus raw payload preservation.
- MCP metadata may return a subset because of Tableau datasource semantics, joins, hidden fields, permissions, or MCP implementation limits.
- If fallback to local fields remains silent, Agent may continue generating invalid MCP queries.
