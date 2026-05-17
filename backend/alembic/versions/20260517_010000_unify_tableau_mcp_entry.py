"""unify tableau mcp entry

Revision ID: 20260517_010000
Revises: 20260514_020000
Create Date: 2026-05-17 01:00:00.000000

OpenSpec unify-tableau-mcp-entry:
- add nullable tableau MCP binding columns
- best-effort legacy Tableau MCP backfill
- do not add active unique binding index in this MVP revision
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260517_010000"
down_revision: Union[str, None] = "20260514_020000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize_url(value: object) -> str:
    return str(value or "").strip().rstrip("/").lower()


def _normalize_site(value: object) -> str:
    return str(value or "").strip().strip("/").lower()


def _credentials_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _strip_successful_backfill_pat_value(credentials: object) -> dict:
    cleaned = dict(_credentials_dict(credentials))
    cleaned.pop("pat_value", None)
    return cleaned


def _pick_tableau_connection(mcp: dict, connections: list[dict]) -> tuple[int | None, str | None]:
    creds = _credentials_dict(mcp.get("credentials"))
    mcp_url = _normalize_url(creds.get("tableau_server"))
    mcp_site = _normalize_site(creds.get("site_name") or mcp.get("site_name"))
    mcp_name = str(mcp.get("name") or "").strip().lower()

    if not mcp_url or not mcp_site:
        return None, "legacy tableau MCP credentials missing tableau_server or site_name"

    matches = [
        conn
        for conn in connections
        if _normalize_url(conn.get("server_url")) == mcp_url
        and _normalize_site(conn.get("site")) == mcp_site
    ]
    if not matches:
        return None, "no matching tableau_connection found"

    name_matches = [conn for conn in matches if str(conn.get("name") or "").strip().lower() == mcp_name]
    if len(name_matches) == 1:
        return int(name_matches[0]["id"]), None
    if len(name_matches) > 1:
        return None, "multiple same-name tableau_connections matched"
    if len(matches) == 1:
        return int(matches[0]["id"]), None

    return None, "multiple tableau_connections matched"


def _backfill_legacy_tableau_mcp_bindings() -> None:
    bind = op.get_bind()
    mcps = bind.execute(
        sa.text(
            """
            SELECT id, name, credentials, site_name
            FROM mcp_servers
            WHERE type = 'tableau'
            ORDER BY id
            """
        )
    ).mappings().all()
    connections = bind.execute(
        sa.text(
            """
            SELECT id, name, server_url, site, is_active, last_test_success, created_at
            FROM tableau_connections
            ORDER BY is_active DESC, last_test_success DESC NULLS LAST, created_at DESC, id DESC
            """
        )
    ).mappings().all()

    connection_dicts = [dict(row) for row in connections]
    for row in mcps:
        mcp = dict(row)
        connection_id, error = _pick_tableau_connection(mcp, connection_dicts)
        if connection_id is None:
            bind.execute(
                sa.text(
                    """
                    UPDATE mcp_servers
                    SET binding_status = 'unbound',
                        last_binding_error = :error
                    WHERE id = :id
                    """
                ),
                {"id": mcp["id"], "error": error},
            )
            continue

        bind.execute(
            sa.text(
                """
                UPDATE mcp_servers
                SET tableau_connection_id = :connection_id,
                    binding_source = 'legacy_mcp_backfill',
                    binding_status = 'bound',
                    credentials = CASE
                        WHEN credentials IS NULL THEN credentials
                        ELSE credentials - 'pat_value'
                    END,
                    last_binding_error = NULL
                WHERE id = :id
                """
            ),
            {"id": mcp["id"], "connection_id": connection_id},
        )


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("tableau_connection_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "mcp_servers",
        sa.Column(
            "binding_source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column(
            "binding_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'unbound'"),
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("last_binding_error", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_mcp_servers_tableau_connection_id",
        "mcp_servers",
        "tableau_connections",
        ["tableau_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_mcp_servers_tableau_connection_id",
        "mcp_servers",
        ["tableau_connection_id"],
    )
    _backfill_legacy_tableau_mcp_bindings()


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_tableau_connection_id", table_name="mcp_servers")
    op.drop_constraint("fk_mcp_servers_tableau_connection_id", "mcp_servers", type_="foreignkey")
    op.drop_column("mcp_servers", "last_binding_error")
    op.drop_column("mcp_servers", "binding_status")
    op.drop_column("mcp_servers", "binding_source")
    op.drop_column("mcp_servers", "tableau_connection_id")
