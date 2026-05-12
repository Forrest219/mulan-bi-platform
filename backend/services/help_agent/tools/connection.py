"""Connection diagnostic tool."""

from __future__ import annotations

from typing import Any

from services.tableau.models import TableauConnection, TableauSyncLog

from .base import finding, isoformat, permission_denied_result, recommendation, related_entity, require_owner_or_admin, tool_result


def diagnose_connection(
    db: Any,
    current_user: Any,
    connection_id: int | None = None,
    tableau_connection_id: int | None = None,
) -> dict[str, Any]:
    conn_id = connection_id if connection_id is not None else tableau_connection_id
    target = {"type": "connection", "id": conn_id}
    conn = db.query(TableauConnection).filter(TableauConnection.id == conn_id).first()
    if not conn:
        return tool_result(
            tool="diagnose_connection",
            target=target,
            findings=[finding("error", "CONNECTION_NOT_FOUND", "没有找到该连接。")],
        )

    try:
        require_owner_or_admin(current_user, getattr(conn, "owner_id", None))
    except PermissionError as exc:
        return permission_denied_result("diagnose_connection", target, str(exc))

    latest_sync = (
        db.query(TableauSyncLog)
        .filter(TableauSyncLog.connection_id == getattr(conn, "id"))
        .order_by(TableauSyncLog.started_at.desc())
        .first()
    )
    findings: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    related: list[dict[str, Any]] = []

    if not getattr(conn, "is_active", False):
        findings.append(finding("error", "CONNECTION_INACTIVE", "该连接当前未启用。"))
        recommendations.append(recommendation("P1", "建议由管理员确认后启用或替换连接。"))
    if getattr(conn, "last_test_success", None) is False:
        findings.append(finding("warning", "LAST_TEST_FAILED", "最近一次连接测试失败。"))
    if getattr(conn, "sync_status", None) == "failed":
        findings.append(finding("warning", "SYNC_STATUS_FAILED", "连接同步状态为 failed。"))
    if latest_sync and getattr(latest_sync, "status", None) == "failed":
        findings.append(finding("warning", "LATEST_SYNC_FAILED", "最近一次同步日志为失败状态。"))
    if getattr(conn, "schedule_id", None):
        related.append(related_entity("task_schedule", getattr(conn, "schedule_id"), "connection.schedule_id"))

    facts = {
        "connection": {
            "id": getattr(conn, "id", None),
            "name": getattr(conn, "name", None),
            "server_url": getattr(conn, "server_url", None),
            "site": getattr(conn, "site", None),
            "api_version": getattr(conn, "api_version", None),
            "connection_type": getattr(conn, "connection_type", None),
            "token_name": getattr(conn, "token_name", None),
            "owner_id": getattr(conn, "owner_id", None),
            "is_active": getattr(conn, "is_active", None),
            "auto_sync_enabled": getattr(conn, "auto_sync_enabled", None),
            "schedule_id": getattr(conn, "schedule_id", None),
            "last_test_at": isoformat(getattr(conn, "last_test_at", None)),
            "last_test_success": getattr(conn, "last_test_success", None),
            "last_test_message": getattr(conn, "last_test_message", None),
            "last_sync_at": isoformat(getattr(conn, "last_sync_at", None)),
            "last_sync_duration_sec": getattr(conn, "last_sync_duration_sec", None),
            "sync_status": getattr(conn, "sync_status", None),
            "mcp_direct_enabled": getattr(conn, "mcp_direct_enabled", None),
            "mcp_server_url": getattr(conn, "mcp_server_url", None),
            "created_at": isoformat(getattr(conn, "created_at", None)),
            "updated_at": isoformat(getattr(conn, "updated_at", None)),
        },
        "latest_sync": {
            "id": getattr(latest_sync, "id", None),
            "trigger_type": getattr(latest_sync, "trigger_type", None),
            "started_at": isoformat(getattr(latest_sync, "started_at", None)),
            "finished_at": isoformat(getattr(latest_sync, "finished_at", None)),
            "status": getattr(latest_sync, "status", None),
            "workbooks_synced": getattr(latest_sync, "workbooks_synced", None),
            "views_synced": getattr(latest_sync, "views_synced", None),
            "dashboards_synced": getattr(latest_sync, "dashboards_synced", None),
            "datasources_synced": getattr(latest_sync, "datasources_synced", None),
            "assets_deleted": getattr(latest_sync, "assets_deleted", None),
            "error_message": getattr(latest_sync, "error_message", None),
        }
        if latest_sync
        else None,
        "mcp_status": {
            "source": "tableau_connection",
            "mcp_direct_enabled": getattr(conn, "mcp_direct_enabled", None),
            "mcp_server_url": getattr(conn, "mcp_server_url", None),
        },
    }
    return tool_result(
        tool="diagnose_connection",
        target=target,
        facts=facts,
        findings=findings,
        recommendations=recommendations,
        related_entities=related,
    )

