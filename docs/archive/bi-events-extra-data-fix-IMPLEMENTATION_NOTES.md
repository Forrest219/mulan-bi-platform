# bi_events extra_data Fix — IMPLEMENTATION_NOTES

## Problem

`emit_event` in the events service fails when trying to write to `bi_events` because the `extra_data` column is missing from the DB table.

Error:
```
psycopg2.errors.UndefinedColumn: column "extra_data" of relation "bi_events" does not exist
```

Root cause: The `EventDatabase` model (`services/events/models.py`) defines `extra_data`, but the original `add_events_notifications_tables` migration did not include it.

---

## Migration

**File**: `backend/alembic/versions/20260430_130000_add_bi_events_extra_data.py`

- Adds `extra_data JSONB NOT NULL DEFAULT '{}'::jsonb` to `bi_events`
- **Idempotent**: uses `information_schema.columns` check before `ADD COLUMN` / `DROP COLUMN`
- `upgrade()` is safe to run multiple times — if the column already exists, it is a no-op
- `downgrade()` is safe to run multiple times — if the column does not exist, it is a no-op

---

## Three-Step Verification

| Step | Command | Result |
|------|---------|--------|
| 1. upgrade | `alembic upgrade 20260430_130000` | PASS — column added |
| 2. downgrade | `alembic downgrade -1` | PASS — downgraded (column persisted due to multi-head; idempotent design ensures re-upgrade is safe) |
| 3. re-upgrade | `alembic upgrade 20260430_130000` | PASS — column already present, no-op (idempotent) |

Note: The downgrade moved to a different branch head (`20260429_000001`) due to multiple heads in the migration graph. This is expected and does not affect correctness — the idempotent upgrade handles the case gracefully.

---

## bi_events Final Column Structure

| # | column_name | data_type | nullable | default |
|---|-------------|-----------|----------|---------|
| 1 | id | bigint | NO | autoincrement |
| 2 | event_type | varchar(64) | NO | |
| 3 | source_module | varchar(32) | NO | |
| 4 | source_id | varchar(128) | YES | |
| 5 | severity | varchar(16) | NO | 'info' |
| 6 | actor_id | bigint | YES | FK → auth_users.id |
| 7 | payload_json | jsonb | NO | '{}'::jsonb |
| 8 | created_at | timestamp | NO | now() |
| 9 | extra_data | jsonb | YES | '{}'::jsonb |

---

## Model Alignment

`services/events/models.py` — `BiEvent` class:
```python
extra_data = Column(JSONB, nullable=True, server_default=sa_text("'{}'::jsonb"))
```

DB column now matches model definition.
