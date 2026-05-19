# Coder Taskbook: Support Multi Tableau Metric Bindings

> 状态：可交付 Coder
> 关联 proposal：`openspec/changes/support-multi-tableau-metric-bindings/proposal.md`
> 关联 design：`openspec/changes/support-multi-tableau-metric-bindings/design.md`
> 关联 tasks：`openspec/changes/support-multi-tableau-metric-bindings/tasks.md`

## 1. 开发目标

把指标治理从“一个指标只能绑定一个 Tableau Published Datasource”升级为“一个逻辑指标可以绑定多个 Tableau Published Datasource”。

用户可见目标：

- `/governance/metrics` 列表能看到指标的主 Tableau 数据源和绑定数量。
- 新建/编辑指标时，atomic 指标可以添加多条 Tableau binding。
- 指标详情页能看到所有执行绑定。
- Data Agent lookup 在给定 Tableau datasource 上下文时使用对应 binding；无上下文时使用 primary binding。

## 2. 不可破坏约束

- 不删除 `bi_metric_definitions.datasource_id/table_name/column_name` 等历史字段。
- 不删除 `bi_metric_bindings` 现有表。
- 不删除 `uq_bmb_primary_tableau_binding`，它用于保证一个 metric 只有一个 active primary Tableau binding。
- 不让显式 datasource lookup fallback 到其他 datasource。
- 不破坏旧 single-binding API payload；旧字段必须至少兼容一个发布周期。
- 不改变 Tableau MCP Gateway、Tableau connection、首页 chat 流式渲染逻辑。
- 不把本任务和当前工作区其他未提交的 Tableau field governance / Agent Monitor / MessageActions 改动混在一起提交。

## 3. 数据契约

新增/使用统一 binding shape：

```ts
interface MetricBinding {
  id?: string | null;
  source_type: 'tableau_published_datasource';
  datasource_id?: number | null;
  tableau_connection_id: number;
  tableau_asset_id?: number | null;
  tableau_datasource_luid: string;
  field_mappings?: Record<string, string> | null;
  required_base_metrics?: string[];
  formula_expression?: unknown;
  is_primary: boolean;
  is_active: boolean;
}
```

`MetricCreate` / `MetricUpdate` 新增：

```ts
bindings?: MetricBinding[];
```

`MetricItem` / `MetricDetail` 新增：

```ts
bindings: MetricBinding[];
primary_binding?: MetricBinding | null;
```

兼容字段保留，并由 primary binding 派生：

- `tableau_connection_id`
- `tableau_asset_id`
- `tableau_datasource_luid`
- `field_mappings`
- `required_base_metrics`
- `formula_expression`

## 4. Package A: Backend Schema And Serialization

Owner files:

- `backend/services/metrics_agent/schemas.py`
- `frontend/src/api/metrics.ts`

Tasks:

- Add `MetricBindingInput` and `MetricBindingOutput` in backend schemas.
- Add `bindings` to create/update/detail/list/lookup schemas.
- Add frontend TypeScript `MetricBinding`.
- Keep existing single-binding fields in API types.

Acceptance:

- Old payload with only `tableau_connection_id/tableau_datasource_luid/field_mappings` still validates.
- New payload with `bindings[]` validates.

## 5. Package B: Backend Registry Service

Owner file:

- `backend/services/metrics_agent/registry.py`

Tasks:

- Replace `_replace_primary_tableau_binding()` usage with multi-binding replacement logic.
- Keep helper for selecting primary binding.
- Add validation:
  - active Tableau binding requires connection id and LUID
  - atomic binding requires non-empty `field_mappings`
  - derived/ratio binding requires `formula_expression`
  - exactly one active primary binding
  - no duplicate active binding for same connection + LUID
- Update create/update/list/detail/lookup paths.
- Ensure version history records binding changes.

Acceptance:

- Create metric with two active Tableau bindings succeeds.
- Update can add/remove bindings.
- Invalid primary/duplicate states fail before DB commit.
- Lookup selection follows explicit context > primary.

## 6. Package C: Optional Alembic Migration

Owner files:

- `backend/alembic/versions/*_metric_binding_unique_identity.py`
- `backend/models/metrics.py`

Tasks:

- Inspect current indexes first.
- If missing, add partial unique index:

```sql
UNIQUE (tenant_id, metric_id, tableau_connection_id, tableau_datasource_luid)
WHERE is_active = true AND source_type = 'tableau_published_datasource'
```

- Keep existing primary unique index unchanged.

Acceptance:

- `alembic upgrade head` succeeds.
- Duplicate active binding is prevented by service validation and DB index.

## 7. Package D: Frontend List And Detail

Owner files:

- `frontend/src/pages/data-governance/metrics/page.tsx`
- `frontend/src/pages/data-governance/metrics/detail.tsx`

Tasks:

- List datasource column:
  - show primary datasource prefix
  - show `共 N 个绑定`
  - show `—` when no active binding
- Detail page:
  - replace single binding block with binding table
  - show primary marker, active state, connection id, asset id, datasource LUID, mappings/formula

Acceptance:

- Single-binding metrics display exactly as before or better.
- Multi-binding metrics show all bindings without layout overflow.

## 8. Package E: Frontend Create/Edit Form

Owner file:

- `frontend/src/pages/data-governance/metrics/page.tsx`

Tasks:

- Refactor `FormData` from single binding fields to `bindings[]`.
- Provide repeatable binding rows for atomic metrics.
- Each row loads assets/fields independently.
- Provide add/remove row, primary radio, active toggle.
- Validate before save:
  - at least one active binding
  - exactly one active primary
  - no duplicate active connection + LUID
  - field caption required for active atomic binding
- Build payload using `bindings[]`.

Acceptance:

- User can add two Tableau datasources to one metric.
- Save request contains `bindings[]`.
- Existing edit page can load old single-binding metric into one row.

## 9. Package F: Tests

Backend required tests:

- Create atomic metric with two bindings and one primary.
- Reject zero primary.
- Reject multiple primary bindings.
- Reject duplicate active binding.
- Legacy single-binding payload creates one primary binding.
- Detail/list include `bindings[]` and compatibility fields.
- Lookup explicit datasource returns matching binding.
- Lookup without datasource returns primary.
- Lookup explicit datasource does not fallback to primary when missing.

Frontend required tests:

- List renders primary binding and binding count.
- Form can add two binding rows and choose primary.
- Save payload contains `bindings[]`.
- Detail renders all bindings.

## 10. Suggested Verification Commands

Backend:

```bash
cd backend && python3 -m py_compile services/metrics_agent/registry.py services/metrics_agent/schemas.py app/api/metrics.py models/metrics.py
cd backend && PYTHONPATH=. .venv/bin/pytest tests/services/metrics_agent/test_registry.py -q --no-cov
```

Frontend:

```bash
cd frontend && npm run type-check
cd frontend && npm test -- --run
cd frontend && npm run build
```

Docker smoke:

```bash
docker compose up -d --build backend frontend
curl -I -L http://localhost:3000/governance/metrics
```

## 11. Manual QA Script

1. Login as `admin/admin123`.
2. Open `http://localhost:3000/governance/metrics`.
3. Create an atomic metric.
4. Add two Tableau bindings using different Published Datasources.
5. Select one as primary and save.
6. Confirm list shows primary datasource and `共 2 个绑定`.
7. Open detail page and confirm both bindings are listed.
8. Edit metric, switch primary binding, save, and confirm list/detail update.
9. Run backend lookup with explicit datasource context for each binding and confirm selected `tableau_datasource_luid` matches the request.

## 12. Coder Handoff Notes

- Start with backend schemas and registry tests before frontend refactor.
- Keep compatibility fields populated from primary binding to minimize blast radius.
- If derived/ratio multi-binding becomes large, keep MVP strict: dependencies must resolve to compatible datasource bindings.
- Do not stage unrelated dirty files already present in the worktree.
