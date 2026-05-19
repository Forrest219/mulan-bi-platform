# Design: Multi Tableau Metric Bindings

## Current State

The database already contains `bi_metric_bindings` and `BiMetricDefinition.bindings`, but application code still behaves as a single-binding system.

Observed constraints:

- `BiMetricDefinition` still has legacy single-source columns: `datasource_id`, `table_name`, `column_name`.
- `BiMetricBinding` supports one row per datasource binding.
- Existing unique index `uq_bmb_primary_tableau_binding` allows only one active primary Tableau binding per metric, which is correct for primary selection.
- `registry._replace_primary_tableau_binding()` currently deactivates the old primary and inserts one new primary row, so non-primary binding management is missing.
- `MetricCreate`, `MetricUpdate`, `MetricBase`, `MetricDetail`, and frontend API types do not expose `bindings[]`.

## Target Contract

### API Binding Shape

Add a shared binding schema to frontend and backend:

```json
{
  "id": "uuid-or-null-for-create",
  "source_type": "tableau_published_datasource",
  "datasource_id": null,
  "tableau_connection_id": 4,
  "tableau_asset_id": 280,
  "tableau_datasource_luid": "f4290485-26d3-428f-aa8d-ccc33862a411",
  "field_mappings": { "value": "销售额" },
  "required_base_metrics": [],
  "formula_expression": {
    "type": "tableau_field",
    "field_caption": "销售额",
    "aggregation_type": "SUM"
  },
  "is_primary": true,
  "is_active": true
}
```

Backend names may use Pydantic models such as `MetricBindingInput` and `MetricBindingOutput`.

### Backward Compatibility

For one release, keep accepting existing single-binding fields:

- `tableau_connection_id`
- `tableau_asset_id`
- `tableau_datasource_luid`
- `field_mappings`
- `required_base_metrics`
- `formula_expression`

If `bindings` is absent and any legacy field is present, normalize these fields into a single primary Tableau binding.

New frontend code must send `bindings`.

### Response Shape

`MetricBase` and `MetricDetail` should include:

- `bindings: MetricBindingOutput[]`
- `primary_binding: MetricBindingOutput | null`
- Existing single-binding fields may remain populated from `primary_binding` for compatibility.

### Validation Rules

- Only `source_type='tableau_published_datasource'` is required for this MVP.
- For active Tableau bindings:
  - `tableau_connection_id` is required.
  - `tableau_datasource_luid` is required.
  - Atomic metrics require non-empty `field_mappings`.
  - Derived/ratio metrics require non-null `formula_expression`.
- Exactly one active primary Tableau binding is required when there is at least one active Tableau binding.
- Duplicate active binding for the same `metric_id + tableau_connection_id + tableau_datasource_luid` must be rejected.
- Derived/ratio metric dependencies must still be compatible with selected binding source. MVP may enforce same Tableau datasource for all dependency bindings unless a more complete cross-source formula strategy is implemented.

## Backend Implementation

### Schema

No required table creation is expected because `bi_metric_bindings` already exists.

Add an Alembic migration only if needed for indexes/constraints:

- Add a partial unique index for active Tableau binding identity if absent:

```sql
UNIQUE (tenant_id, metric_id, tableau_connection_id, tableau_datasource_luid)
WHERE is_active = true AND source_type = 'tableau_published_datasource'
```

Keep existing `uq_bmb_primary_tableau_binding` because it enforces one primary binding.

### Registry Service

Add helpers:

- `_normalize_binding_inputs(data, metric_type, existing_metric=None) -> list[dict]`
- `_validate_metric_bindings(metric_type, bindings)`
- `_replace_tableau_bindings(db, metric, binding_inputs, dependencies_by_binding=None)`
- `_serialize_binding(binding) -> dict`
- `_primary_binding_for_metric(metric)` or query equivalent

Refactor:

- `create_metric()` should create the metric, dependencies, and all binding rows in one transaction.
- `update_metric()` should replace or patch bindings consistently.
- `get_metric()` should eager-load or serialize active bindings.
- `list_metrics()` should return metrics with binding summaries without N+1 behavior.
- `lookup_metrics()` should use matching binding when datasource context exists and primary binding when it does not.

### Lookup Selection

Rules:

1. If `tableau_connection_id` and/or `tableau_datasource_luid` are provided, select the active binding matching those filters.
2. If no datasource context is provided, select the active primary binding.
3. If no matching binding exists, return `MC_BINDING_UNAVAILABLE`.
4. If a selected binding is invalid, return `MC_BINDING_INVALID`.

Do not silently fall back to a different datasource when explicit datasource context was provided.

## Frontend Implementation

### List Page

On `/governance/metrics`:

- Replace the single datasource cell with a compact summary:
  - `主: Tableau <luid-prefix>`
  - `共 N 个绑定`
- If there are binding errors, show a small warning indicator.
- Keep table dense; do not add oversized cards.

### Create/Edit Form

For atomic metrics:

- Replace the single Tableau Binding section with a repeatable binding table/editor.
- Each row includes:
  - Tableau connection
  - Published Datasource
  - Field Caption
  - Aggregation type or formula expression preview as applicable
  - Primary radio
  - Active toggle
  - Remove button
- Provide “添加 Tableau 数据源” button.
- Prevent save when zero active primary binding or duplicate active datasource binding exists.

For derived/ratio metrics:

- Show inherited binding compatibility constraints clearly in validation messages.
- MVP can either:
  - derive bindings from dependency metrics, or
  - allow explicit binding rows with formula expression.

Coder should choose the smaller implementation that satisfies backend validation and current UX.

### Detail Page

Add an “执行绑定” table:

- Primary marker
- Source type
- Tableau connection id
- Tableau asset id
- Datasource LUID
- Field mappings
- Required base metrics
- Active status

## Testing Strategy

Backend:

- Registry unit tests for create/update/list/detail/lookup.
- API tests for request/response compatibility.
- Migration test if a new index is added.

Frontend:

- API type/payload tests where existing patterns allow.
- Component tests for create/edit binding rows and list/detail rendering.

Manual Docker verification:

- Create a metric with two bindings through UI.
- Confirm database has two active binding rows and one primary row.
- Confirm list/detail display both bindings.
- Confirm lookup behavior with explicit datasource context.

## Risks

- Existing tests may assume a single primary binding. Keep compatibility fields populated from primary binding.
- Derived/ratio cross-datasource support can expand scope quickly. Enforce same-source constraints for MVP if needed.
- Replacing all bindings on update may deactivate rows and create new IDs. This is acceptable for MVP unless audit requirements depend on stable binding IDs.
