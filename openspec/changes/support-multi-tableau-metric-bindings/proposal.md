# Proposal: Support Multi Tableau Metric Bindings

## Status

Ready for Coder implementation.

## Problem

`/governance/metrics` treats one metric as if it can have only one Tableau Published Datasource binding. This is not true for real BI governance: the same logical metric, such as revenue or profit, may exist in multiple Tableau published datasources, with datasource-specific field captions, formulas, or execution metadata.

Current implementation gaps:

- Frontend create/edit form has single-value fields: `tableau_connection_id`, `tableau_asset_id`, `tableau_datasource_luid`, `field_caption`.
- Frontend list and detail pages display only one Tableau datasource.
- API request/response schemas expose only one Tableau binding.
- Backend data model has `bi_metric_bindings`, but service code only replaces one primary Tableau binding.
- Lookup can filter by runtime datasource, but response shape still returns one selected binding rather than all configured bindings.

## Goal

Model metric definitions as logical governance objects with one or more execution bindings.

MVP behavior:

- A metric can bind to multiple Tableau Published Datasources.
- Each binding stores its own Tableau connection, asset, datasource LUID, field mappings, required base metrics, formula expression, active flag, and primary flag.
- Exactly one active primary Tableau binding is allowed per metric.
- Data Agent lookup with explicit Tableau datasource context selects the matching binding.
- Data Agent lookup without explicit datasource context uses the primary binding.
- Governance list/detail pages show multi-binding state clearly.
- Create/edit page allows adding, editing, removing, and selecting primary Tableau bindings.

## Non-Goals

- Do not redesign metric dependency semantics beyond the minimum needed for binding source compatibility.
- Do not migrate legacy `datasource_id/table_name/column_name` execution paths into the new UI.
- Do not add cross-datasource formula execution in the first delivery.
- Do not change Tableau MCP Gateway behavior.
- Do not change homepage chat query behavior except where lookup already consumes metric bindings.

## User Impact

Data governance users can define one logical metric once and attach it to multiple Tableau datasources, avoiding duplicate metric definitions just because Tableau assets differ.

## Primary Files

- `backend/models/metrics.py`
- `backend/services/metrics_agent/schemas.py`
- `backend/services/metrics_agent/registry.py`
- `backend/app/api/metrics.py`
- `frontend/src/api/metrics.ts`
- `frontend/src/pages/data-governance/metrics/page.tsx`
- `frontend/src/pages/data-governance/metrics/detail.tsx`
- `backend/tests/services/metrics_agent/test_registry.py`

## Acceptance Summary

- Create metric with two Tableau bindings succeeds.
- Edit metric can add/remove/update bindings without creating duplicate metric definitions.
- List page shows datasource count and primary datasource.
- Detail page shows all bindings.
- Lookup with `tableau_connection_id + tableau_datasource_luid` selects that binding.
- Lookup without datasource context selects primary binding.
- Attempting to save zero active primary binding or multiple active primary bindings fails with a clear validation error.
