# Tasks

## Backend

- [ ] MMB-01: Add backend Pydantic schemas for metric bindings: `MetricBindingInput`, `MetricBindingOutput`, and update `MetricCreate`, `MetricUpdate`, `MetricBase`, `MetricDetail`, `MetricLookupItem`.
- [ ] MMB-02: Preserve backward compatibility by normalizing legacy single-binding fields into one primary binding when `bindings` is absent.
- [ ] MMB-03: Add binding validation: required Tableau connection/LUID, atomic field mappings, derived/ratio formula expression, exactly one active primary binding, no duplicate active datasource binding.
- [ ] MMB-04: Refactor `registry.create_metric()` to persist all submitted Tableau bindings in one transaction.
- [ ] MMB-05: Refactor `registry.update_metric()` to update binding rows consistently and write version history when bindings change.
- [ ] MMB-06: Update `registry.list_metrics()` and `registry.get_metric()` to include `bindings[]`, `primary_binding`, and compatibility single-binding fields derived from primary binding.
- [ ] MMB-07: Update `registry.lookup_metrics()` so explicit Tableau datasource context selects the matching binding and no-context lookup selects primary binding only.
- [ ] MMB-08: Add Alembic migration only if the active duplicate binding unique index is missing; do not drop existing `uq_bmb_primary_tableau_binding`.
- [ ] MMB-09: Ensure publish validation checks the selected/primary valid binding and still rejects missing/invalid bindings.
- [ ] MMB-10: Ensure derived/ratio dependency validation has deterministic MVP behavior for datasource compatibility.

## Frontend

- [ ] MMB-11: Update `frontend/src/api/metrics.ts` with `MetricBinding` types and `bindings[]` request/response fields.
- [ ] MMB-12: Update `/governance/metrics` list datasource column to show primary binding and total active binding count.
- [ ] MMB-13: Refactor create/edit form state from single Tableau binding fields to repeatable binding rows while keeping the current compact inline form.
- [ ] MMB-14: Add row actions: add Tableau binding, remove binding, choose primary binding, activate/deactivate binding.
- [ ] MMB-15: Load Tableau assets/fields per binding row without cross-row state collisions.
- [ ] MMB-16: Build save payload using `bindings[]`; do not send only single-binding fields from new UI.
- [ ] MMB-17: Update metric detail page “执行绑定” section to render all bindings in a table.
- [ ] MMB-18: Keep existing visual style: dense governance UI, no marketing hero, no nested cards.

## Tests

- [ ] MMB-19: Backend test: create atomic metric with two Tableau bindings and one primary.
- [ ] MMB-20: Backend test: reject create/update when zero primary active binding exists.
- [ ] MMB-21: Backend test: reject create/update when multiple active primary bindings exist.
- [ ] MMB-22: Backend test: reject duplicate active `tableau_connection_id + tableau_datasource_luid` for one metric.
- [ ] MMB-23: Backend test: legacy single-binding payload still creates one primary binding.
- [ ] MMB-24: Backend test: list/detail return `bindings[]`, `primary_binding`, and compatibility fields.
- [ ] MMB-25: Backend test: lookup with explicit Tableau datasource returns matching binding.
- [ ] MMB-26: Backend test: lookup without datasource context returns primary binding.
- [ ] MMB-27: Backend test: explicit datasource context does not fall back to primary when no matching binding exists.
- [ ] MMB-28: Frontend test: list renders binding count and primary binding.
- [ ] MMB-29: Frontend test: create/edit form can add two binding rows and select primary.
- [ ] MMB-30: Frontend test: save payload contains `bindings[]`.
- [ ] MMB-31: Frontend test: detail page renders all bindings.

## Verification

- [ ] MMB-32: Run `cd backend && python3 -m py_compile services/metrics_agent/registry.py services/metrics_agent/schemas.py app/api/metrics.py models/metrics.py`.
- [ ] MMB-33: Run `cd backend && PYTHONPATH=. .venv/bin/pytest tests/services/metrics_agent/test_registry.py -q --no-cov`.
- [ ] MMB-34: Run relevant backend API tests if added.
- [ ] MMB-35: Run `cd frontend && npm run type-check`.
- [ ] MMB-36: Run `cd frontend && npm test -- --run`.
- [ ] MMB-37: Run `cd frontend && npm run build`.
- [ ] MMB-38: Rebuild/restart Docker frontend/backend if UI/API behavior is verified in Docker.

## Gate

- A metric must not need to be duplicated just because it appears in multiple Tableau datasources.
- API must remain backward compatible with old single-binding payloads for one release.
- New frontend must use `bindings[]`.
- Explicit datasource lookup must never silently execute against a different datasource.
- Exactly one active primary Tableau binding must exist for metrics that have active Tableau bindings.
- Existing Data Agent metric lookup behavior must not regress for single-binding metrics.
- Existing governance routes must continue to load under `http://localhost:3000/governance/metrics`.
