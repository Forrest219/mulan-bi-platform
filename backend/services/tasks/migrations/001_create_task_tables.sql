-- Migration: Create task tables for bi_task_runs and bi_task_schedules
-- Spec 33 — Task Management API
-- Runs idempotently via seed endpoint table-check

-- bi_task_runs: task execution history
CREATE TABLE IF NOT EXISTS bi_task_runs (
    id BIGSERIAL PRIMARY KEY,
    celery_task_id VARCHAR(256),
    task_name VARCHAR(256) NOT NULL,
    task_label VARCHAR(128),
    trigger_type VARCHAR(16) NOT NULL DEFAULT 'beat',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_ms INTEGER,
    result_summary JSONB,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    parent_run_id BIGINT REFERENCES bi_task_runs(id) ON DELETE SET NULL,
    triggered_by BIGINT REFERENCES auth_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_trigger_type CHECK (trigger_type IN ('beat', 'manual', 'api')),
    CONSTRAINT chk_status CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS ix_task_runs_task_name_started ON bi_task_runs(task_name, started_at);
CREATE INDEX IF NOT EXISTS ix_task_runs_status_started ON bi_task_runs(status, started_at);
CREATE INDEX IF NOT EXISTS ix_task_runs_started_at ON bi_task_runs(started_at);
CREATE INDEX IF NOT EXISTS ix_task_runs_parent ON bi_task_runs(parent_run_id);
CREATE INDEX IF NOT EXISTS ix_task_runs_celery_task_id ON bi_task_runs(celery_task_id);

-- bi_task_schedules: celery beat schedule configuration
CREATE TABLE IF NOT EXISTS bi_task_schedules (
    id SERIAL PRIMARY KEY,
    schedule_key VARCHAR(128) UNIQUE NOT NULL,
    task_name VARCHAR(256) NOT NULL,
    description TEXT,
    schedule_expr VARCHAR(256) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMP,
    last_run_status VARCHAR(16),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_task_schedules_task_name ON bi_task_schedules(task_name);
CREATE INDEX IF NOT EXISTS ix_task_schedules_is_enabled ON bi_task_schedules(is_enabled);