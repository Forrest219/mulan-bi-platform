"""repair spec28 analysis tables

Revision ID: 20260519_010000
Revises: 20260518_010000
Create Date: 2026-05-19 01:00:00.000000

This migration repairs environments whose alembic_version reached a later
revision while the Spec 28 analysis table family was not actually created.
It is intentionally idempotent and data-preserving.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260519_010000"
down_revision: Union[str, None] = "20260518_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SEQUENCE IF NOT EXISTS bi_analysis_session_steps_seq")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bi_analysis_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            agent_type VARCHAR(32) NOT NULL DEFAULT 'data_agent',
            task_type VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'created',
            expiration_reason VARCHAR(32),
            hypothesis_tree JSONB,
            current_step INTEGER NOT NULL DEFAULT 0,
            context_snapshot JSONB,
            session_metadata JSONB,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            completed_at TIMESTAMP WITHOUT TIME ZONE,
            expired_at TIMESTAMP WITHOUT TIME ZONE
        )
        """
    )
    op.execute("ALTER TABLE bi_analysis_sessions ADD COLUMN IF NOT EXISTS session_metadata JSONB")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'bi_analysis_sessions'
                  AND column_name = 'metadata'
            ) THEN
                EXECUTE 'UPDATE bi_analysis_sessions '
                    || 'SET session_metadata = metadata '
                    || 'WHERE session_metadata IS NULL AND metadata IS NOT NULL';
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bi_analysis_session_steps (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID NOT NULL,
            session_id UUID NOT NULL REFERENCES bi_analysis_sessions(id) ON DELETE CASCADE,
            sequence_no BIGINT NOT NULL DEFAULT nextval('bi_analysis_session_steps_seq'::regclass),
            step_no INTEGER NOT NULL,
            branch_id VARCHAR(32) NOT NULL DEFAULT 'main',
            parent_sequence_no BIGINT,
            idempotency_key VARCHAR(128),
            reasoning_trace JSONB NOT NULL,
            query_log JSONB,
            context_delta JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_ass_step_branch UNIQUE (session_id, step_no, branch_id)
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_ass_session_id'
                  AND conrelid = 'bi_analysis_session_steps'::regclass
            ) THEN
                ALTER TABLE bi_analysis_session_steps
                ADD CONSTRAINT fk_ass_session_id
                FOREIGN KEY (session_id)
                REFERENCES bi_analysis_sessions(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bi_analysis_insights (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            session_id UUID REFERENCES bi_analysis_sessions(id) ON DELETE SET NULL,
            insight_type VARCHAR(16) NOT NULL,
            title VARCHAR(256) NOT NULL,
            summary TEXT NOT NULL,
            detail_json JSONB NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            impact_scope VARCHAR(128),
            push_targets JSONB,
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            created_by INTEGER NOT NULL,
            lineage_status VARCHAR(16) NOT NULL DEFAULT 'resolved',
            datasource_ids INTEGER[] NOT NULL DEFAULT '{}'::INTEGER[],
            metric_names TEXT[],
            visibility VARCHAR(16) NOT NULL DEFAULT 'private',
            allowed_roles JSONB,
            published_at TIMESTAMP WITHOUT TIME ZONE,
            provenance_info JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bi_analysis_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            session_id UUID REFERENCES bi_analysis_sessions(id) ON DELETE SET NULL,
            subject VARCHAR(256) NOT NULL,
            time_range VARCHAR(64),
            content_json JSONB NOT NULL,
            content_md TEXT,
            author INTEGER NOT NULL,
            lineage_status VARCHAR(16) NOT NULL DEFAULT 'resolved',
            datasource_ids INTEGER[] NOT NULL DEFAULT '{}'::INTEGER[],
            visibility VARCHAR(16) NOT NULL DEFAULT 'private',
            allowed_roles TEXT[],
            allowed_user_groups TEXT[],
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            published_at TIMESTAMP WITHOUT TIME ZONE,
            provenance_info JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_as_tenant_status ON bi_analysis_sessions (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_as_user_status ON bi_analysis_sessions (tenant_id, created_by, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_as_task_type ON bi_analysis_sessions (task_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_as_created ON bi_analysis_sessions (created_at DESC)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_ass_tenant ON bi_analysis_session_steps (tenant_id, session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ass_session_step ON bi_analysis_session_steps (tenant_id, session_id, step_no DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ass_sequence ON bi_analysis_session_steps (session_id, sequence_no)")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ass_idem_key
        ON bi_analysis_session_steps (session_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_session ON bi_analysis_insights (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_type_status ON bi_analysis_insights (insight_type, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_published ON bi_analysis_insights (published_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_ds ON bi_analysis_insights USING gin (datasource_ids)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_roles ON bi_analysis_insights USING gin (allowed_roles)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_vis_pub ON bi_analysis_insights (visibility, status, published_at DESC)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_ar_session ON bi_analysis_reports (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ar_author ON bi_analysis_reports (author)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ar_ds ON bi_analysis_reports USING gin (datasource_ids)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ar_roles ON bi_analysis_reports USING gin (allowed_roles)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ar_groups ON bi_analysis_reports USING gin (allowed_user_groups)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ar_vis_pub ON bi_analysis_reports (visibility, status, published_at DESC)")


def downgrade() -> None:
    # This is a repair migration for production schema drift. Downgrade must not
    # drop user data or shared Spec 28 tables that may have predated this repair.
    pass
