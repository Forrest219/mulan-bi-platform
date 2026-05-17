"""Tests for unified Tableau MCP binding entry."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import uuid
from unittest import mock

import pytest
import sqlalchemy as sa


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _load_migration():
    migration_path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260517_010000_unify_tableau_mcp_entry.py"
    )
    spec = importlib.util.spec_from_file_location("unify_tableau_mcp_entry", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    return migration


@pytest.mark.skip_db
def test_mcp_server_mapper_configures_without_preimporting_tableau_models():
    code = """
from sqlalchemy.orm import configure_mappers
from services.mcp.models import McpServer
configure_mappers()
print(McpServer.__tablename__)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=__import__("pathlib").Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "mcp_servers" in result.stdout


def test_migration_columns_and_plain_binding_index_exist(db_session):
    inspector = sa.inspect(db_session.bind)
    columns = {column["name"] for column in inspector.get_columns("mcp_servers")}
    assert {"tableau_connection_id", "binding_source", "binding_status", "last_binding_error"} <= columns

    indexes = inspector.get_indexes("mcp_servers")
    binding_indexes = [
        index
        for index in indexes
        if index["name"] == "ix_mcp_servers_tableau_connection_id"
        or index.get("column_names") == ["tableau_connection_id"]
    ]
    assert binding_indexes
    assert not any(index.get("unique") for index in binding_indexes)


def test_migration_backfill_conflict_marks_unbound():
    migration = _load_migration()
    connection_id, error = migration._pick_tableau_connection(
        {
            "id": 1,
            "name": "legacy",
            "credentials": {"tableau_server": "https://tableau.example.com", "site_name": "sales"},
        },
        [
            {"id": 1, "name": "one", "server_url": "https://tableau.example.com", "site": "sales"},
            {"id": 2, "name": "two", "server_url": "https://tableau.example.com/", "site": "/sales"},
        ],
    )

    assert connection_id is None
    assert error == "multiple tableau_connections matched"


def test_migration_unique_match_backfill_cleans_only_pat_value(db_session, monkeypatch):
    from app.api.tableau import _encrypt
    from services.auth.models import User
    from services.mcp.models import McpServer
    from services.tableau.models import TableauConnection

    migration = _load_migration()
    admin = db_session.query(User).filter(User.username == "admin").first()
    assert admin is not None
    server_url = f"https://backfill-{uuid.uuid4().hex[:8]}.example.com"

    conn = TableauConnection(
        name="legacy-tableau",
        server_url=server_url,
        site="sales",
        token_name="pat",
        token_encrypted=_encrypt("secret"),
        owner_id=admin.id,
        api_version="3.21",
        connection_type="mcp",
    )
    db_session.add(conn)
    db_session.flush()
    mcp = McpServer(
        name="legacy-tableau",
        type="tableau",
        server_url="http://legacy-mcp.local/mcp",
        is_active=True,
        credentials={
            "tableau_server": f"{server_url}/",
            "site_name": "/sales",
            "pat_name": "pat",
            "pat_value": "legacy-secret",
            "keep": "value",
        },
    )
    db_session.add(mcp)
    db_session.flush()

    monkeypatch.setattr(migration.op, "get_bind", lambda: db_session.connection())
    migration._backfill_legacy_tableau_mcp_bindings()
    db_session.expire_all()

    rebound = db_session.query(McpServer).filter(McpServer.id == mcp.id).one()
    assert rebound.tableau_connection_id == conn.id
    assert rebound.binding_source == "legacy_mcp_backfill"
    assert rebound.binding_status == "bound"
    assert rebound.credentials["keep"] == "value"
    assert "pat_value" not in rebound.credentials


def test_create_connection_uses_token_value_and_creates_bound_mcp(admin_client, monkeypatch):
    monkeypatch.setenv("TABLEAU_MCP_GATEWAY_URL", "http://gateway.local/mcp")
    monkeypatch.setattr("app.api.tableau._test_connection_rest", lambda *args, **kwargs: {"success": True, "message": "ok"})

    class _Resp:
        status_code = 200
        text = "event: message\ndata: {\"result\": {}}\n\n"

    post_calls = []

    def _post(url, json=None, headers=None, timeout=None):
        post_calls.append({"url": url, "headers": headers or {}})
        return _Resp()

    monkeypatch.setattr("services.tableau.mcp_binding_service.requests.post", _post)

    payload = {
        "name": _unique("bi-tableau"),
        "server_url": f"https://tableau-{uuid.uuid4().hex[:8]}.example.com",
        "site": "sales",
        "token_name": "mulan_pat",
        "token_value": "secret",
        "agent_enabled": True,
    }
    resp = admin_client.post("/api/tableau/connections", json=payload)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["connection"]["mcp_binding"]["binding_status"] == "bound"
    assert post_calls[0]["headers"]["X-Mulan-Tableau-Connection-Id"]

    mcp_resp = admin_client.get("/api/mcp-configs/")
    assert mcp_resp.status_code == 200
    records = [item for item in mcp_resp.json() if item.get("tableau_connection_id") == body["connection"]["id"]]
    assert records
    assert (records[0].get("credentials") or {}).get("pat_value") is None


def test_create_connection_gateway_missing_returns_disabled_without_health_check(admin_client, monkeypatch):
    monkeypatch.delenv("TABLEAU_MCP_GATEWAY_URL", raising=False)
    monkeypatch.delenv("TABLEAU_MCP_SERVER_URL", raising=False)
    monkeypatch.setattr("app.api.tableau._test_connection_rest", lambda *args, **kwargs: {"success": True, "message": "ok"})
    post_call = mock.Mock(side_effect=AssertionError("missing gateway should skip health check"))
    monkeypatch.setattr("services.tableau.mcp_binding_service.requests.post", post_call)

    resp = admin_client.post("/api/tableau/connections", json={
        "name": _unique("disabled-tableau"),
        "server_url": f"https://disabled-{uuid.uuid4().hex[:8]}.example.com",
        "site": "sales",
        "token_name": "pat",
        "token_value": "secret",
        "agent_enabled": True,
    })

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["connection"]["mcp_binding"]["binding_status"] == "disabled"
    assert body["connection"]["mcp_binding"]["last_error"] == "TABLEAU_MCP_GATEWAY_URL is not configured"
    assert body["connection"]["mcp_direct_enabled"] is False
    assert post_call.call_count == 0


def test_create_connection_gateway_health_failure_returns_unhealthy(admin_client, monkeypatch):
    monkeypatch.setenv("TABLEAU_MCP_GATEWAY_URL", "http://gateway.local/mcp")
    monkeypatch.setattr("app.api.tableau._test_connection_rest", lambda *args, **kwargs: {"success": True, "message": "ok"})
    monkeypatch.setattr(
        "services.tableau.mcp_binding_service.requests.post",
        mock.Mock(side_effect=RuntimeError("gateway down")),
    )

    resp = admin_client.post("/api/tableau/connections", json={
        "name": _unique("unhealthy-tableau"),
        "server_url": f"https://unhealthy-{uuid.uuid4().hex[:8]}.example.com",
        "site": "sales",
        "token_name": "pat",
        "token_value": "secret",
        "agent_enabled": True,
    })

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["connection"]["mcp_binding"]["binding_status"] == "unhealthy"
    assert body["connection"]["mcp_direct_enabled"] is True
    assert body["connection"]["agent_enabled"] is True


def test_update_connection_can_disable_agent_binding(admin_client, monkeypatch):
    monkeypatch.setenv("TABLEAU_MCP_GATEWAY_URL", "http://gateway.local/mcp")
    monkeypatch.setattr("app.api.tableau._test_connection_rest", lambda *args, **kwargs: {"success": True, "message": "ok"})

    class _Resp:
        status_code = 200
        text = "event: message\ndata: {\"result\": {}}\n\n"

    monkeypatch.setattr("services.tableau.mcp_binding_service.requests.post", lambda *args, **kwargs: _Resp())
    create_resp = admin_client.post("/api/tableau/connections", json={
        "name": _unique("disable-agent"),
        "server_url": f"https://disable-{uuid.uuid4().hex[:8]}.example.com",
        "site": "sales",
        "token_name": "pat",
        "token_value": "secret",
        "agent_enabled": True,
    })
    assert create_resp.status_code == 201, create_resp.text
    conn = create_resp.json()["connection"]

    update_resp = admin_client.put(f"/api/tableau/connections/{conn['id']}", json={"agent_enabled": False})

    assert update_resp.status_code == 200, update_resp.text
    body = update_resp.json()
    assert body["connection"]["mcp_binding"]["binding_status"] == "disabled"
    assert body["connection"]["mcp_direct_enabled"] is False


def test_create_connection_duplicate_site_returns_409(admin_client, monkeypatch):
    monkeypatch.delenv("TABLEAU_MCP_GATEWAY_URL", raising=False)
    monkeypatch.setattr("app.api.tableau._test_connection_rest", lambda *args, **kwargs: {"success": True, "message": "ok"})
    server_url = f"https://dup-{uuid.uuid4().hex[:8]}.example.com"
    payload = {
        "name": _unique("dup-tableau"),
        "server_url": server_url,
        "site": "sales",
        "token_name": "pat",
        "token_value": "secret",
        "agent_enabled": False,
    }
    first = admin_client.post("/api/tableau/connections", json=payload)
    assert first.status_code == 201, first.text

    duplicate = dict(payload, name=_unique("dup-tableau"), server_url=f"{server_url}/", site="/sales")
    second = admin_client.post("/api/tableau/connections", json=duplicate)

    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "TAB_409"


def test_mcp_config_tableau_default_requires_connection_id(admin_client):
    resp = admin_client.post("/api/mcp-configs/", json={
        "name": _unique("tableau-mcp-reject"),
        "type": "tableau",
        "server_url": None,
        "is_active": True,
        "credentials": {},
        "advanced_mode": False,
    })

    assert resp.status_code == 422
    assert "tableau_connection_id" in resp.text


def test_mcp_config_rejects_tableau_pat_credentials(admin_client):
    resp = admin_client.post("/api/mcp-configs/", json={
        "name": _unique("tableau-mcp-pat-reject"),
        "type": "tableau",
        "server_url": "http://gateway.local/mcp",
        "is_active": True,
        "credentials": {"pat_value": "secret"},
        "advanced_mode": True,
    })

    assert resp.status_code == 422
    assert "PAT Secret" in resp.text


def test_mcp_config_non_tableau_behavior_preserves_endpoint_and_credentials(admin_client):
    payload = {
        "name": _unique("starrocks-mcp"),
        "type": "starrocks",
        "server_url": "http://localhost:3928/starrocks-mcp",
        "description": "StarRocks MCP",
        "is_active": True,
        "credentials": {"host": "localhost", "user": "root", "password": "pw"},
    }

    resp = admin_client.post("/api/mcp-configs/", json=payload)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["type"] == "starrocks"
    assert body["server_url"] == payload["server_url"]
    assert body["credentials"] == payload["credentials"]


def test_mcp_config_list_scrubs_legacy_tableau_pat_credentials(admin_client):
    from app.core.database import SessionLocal
    from services.mcp.models import McpServer

    session = SessionLocal()
    legacy_id = None
    try:
        legacy = McpServer(
            name=_unique("legacy-tableau-scrub"),
            type="tableau",
            server_url="http://legacy-mcp.local/mcp",
            is_active=True,
            credentials={
                "tableau_server": "https://tableau.example.com",
                "site_name": "sales",
                "pat_name": "pat",
                "pat_value": "legacy-secret",
                "token_value": "legacy-token",
                "token_secret": "legacy-token-secret",
            },
            binding_source="manual",
            binding_status="unbound",
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id

        resp = admin_client.get("/api/mcp-configs/")

        assert resp.status_code == 200, resp.text
        record = next(item for item in resp.json() if item["id"] == legacy_id)
        assert record["credentials"]["tableau_server"] == "https://tableau.example.com"
        assert "pat_value" not in record["credentials"]
        assert "token_value" not in record["credentials"]
        assert "token_secret" not in record["credentials"]
    finally:
        if legacy_id is not None:
            session.query(McpServer).filter(McpServer.id == legacy_id).delete()
            session.commit()
        session.close()


def test_updating_legacy_tableau_mcp_does_not_reverse_bridge(admin_client, monkeypatch):
    from app.core.database import SessionLocal
    from services.mcp.models import McpServer
    from services.tableau.models import TableauConnection

    session = SessionLocal()
    legacy_id = None
    try:
        legacy = McpServer(
            name=_unique("legacy-no-bridge"),
            type="tableau",
            server_url="http://legacy-mcp.local/mcp",
            is_active=True,
            credentials={
                "tableau_server": f"https://legacy-{uuid.uuid4().hex[:8]}.example.com",
                "site_name": "sales",
                "pat_name": "pat",
                "pat_value": "legacy-secret",
            },
            binding_source="manual",
            binding_status="unbound",
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
        before = session.query(TableauConnection).count()
        monkeypatch.setattr(
            "services.tableau.models.TableauDatabase.ensure_connection_from_mcp",
            mock.Mock(side_effect=AssertionError("legacy bridge must not run")),
        )

        resp = admin_client.put(f"/api/mcp-configs/{legacy_id}", json={
            "description": "legacy edited",
            "is_active": True,
        })

        session.expire_all()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "tableau_bridge" not in body
        assert "pat_value" not in body["credentials"]
        assert session.query(TableauConnection).count() == before
    finally:
        if legacy_id is not None:
            session.query(McpServer).filter(McpServer.id == legacy_id).delete()
            session.commit()
        session.close()


@pytest.mark.skip_db
def test_tableau_mcp_endpoint_normalizes_legacy_hostdocker_by_runtime(monkeypatch):
    import services.common.settings as settings

    monkeypatch.setattr(settings, "_is_running_in_container", lambda: False)
    assert (
        settings.normalize_tableau_mcp_endpoint("http://host.docker.internal:3927/tableau-mcp")
        == "http://localhost:3927/tableau-mcp"
    )
    monkeypatch.setenv("TABLEAU_MCP_GATEWAY_URL", "http://host.docker.internal:3927/tableau-mcp")
    assert settings.get_tableau_mcp_gateway_url() == "http://localhost:3927/tableau-mcp"

    monkeypatch.setattr(settings, "_is_running_in_container", lambda: True)
    assert (
        settings.normalize_tableau_mcp_endpoint("http://host.docker.internal:3927/tableau-mcp")
        == "http://tableau-mcp-gateway:3928/tableau-mcp"
    )
    assert settings.get_tableau_mcp_gateway_url() == "http://tableau-mcp-gateway:3928/tableau-mcp"


def test_auto_binding_rewrites_legacy_hostdocker_to_localhost_for_host_runtime(db_session, monkeypatch):
    from app.core.crypto import get_tableau_crypto
    import services.common.settings as settings
    from services.auth.models import User
    from services.mcp.models import McpServer
    from services.tableau.mcp_binding_service import TableauMcpBindingService
    from services.tableau.models import TableauConnection

    monkeypatch.setattr(settings, "_is_running_in_container", lambda: False)
    monkeypatch.setenv("TABLEAU_MCP_GATEWAY_URL", "http://host.docker.internal:3927/tableau-mcp")

    admin = db_session.query(User).filter(User.username == "admin").first()
    assert admin is not None
    conn = TableauConnection(
        name=_unique("legacy-hostdocker-tableau"),
        server_url=f"https://legacy-hostdocker-{uuid.uuid4().hex[:8]}.example.com",
        site="sales",
        token_name="pat",
        token_encrypted=get_tableau_crypto().encrypt("secret"),
        owner_id=admin.id,
        api_version="3.21",
        connection_type="mcp",
    )
    db_session.add(conn)
    db_session.flush()
    binding = McpServer(
        name=_unique("legacy-hostdocker-mcp"),
        type="tableau",
        server_url="http://host.docker.internal:3927/tableau-mcp",
        is_active=True,
        credentials={"tableau_connection_id": conn.id},
        tableau_connection_id=conn.id,
        binding_source="auto_tableau_connection",
        binding_status="unbound",
        health_status="unknown",
    )
    db_session.add(binding)
    db_session.flush()

    service = TableauMcpBindingService(db_session)
    result = service.upsert_for_connection(
        connection=conn,
        enabled=True,
        owner_id=admin.id,
        health_check=False,
    )
    db_session.flush()

    assert result["server_url"] == "http://localhost:3927/tableau-mcp"
    assert binding.server_url == "http://localhost:3927/tableau-mcp"
    assert conn.mcp_server_url == "http://localhost:3927/tableau-mcp"

    class _Resp:
        status_code = 200

    monkeypatch.setattr(
        "services.tableau.mcp_binding_service.requests.post",
        lambda *args, **kwargs: _Resp(),
    )
    binding.server_url = "http://host.docker.internal:3927/tableau-mcp"
    conn.mcp_server_url = "http://host.docker.internal:3927/tableau-mcp"
    refreshed = service.refresh_health_for_connection(connection_id=conn.id, user_id=admin.id)

    assert refreshed["server_url"] == "http://localhost:3927/tableau-mcp"
    assert binding.server_url == "http://localhost:3927/tableau-mcp"
    assert conn.mcp_server_url == "http://localhost:3927/tableau-mcp"


def test_update_connection_agent_enable_allows_unchanged_duplicate_site(admin_client, monkeypatch):
    from app.api.tableau import _encrypt
    from app.core.database import SessionLocal
    from services.auth.models import User
    from services.mcp.models import McpServer
    from services.tableau.models import TableauConnection

    monkeypatch.setenv("TABLEAU_MCP_GATEWAY_URL", "http://gateway.local/mcp")
    rest_test = mock.Mock(side_effect=AssertionError("unchanged site key should not be retested"))
    monkeypatch.setattr("app.api.tableau._test_connection_rest", rest_test)

    class _Resp:
        status_code = 200
        text = "event: message\ndata: {\"result\": {}}\n\n"

    monkeypatch.setattr("services.tableau.mcp_binding_service.requests.post", lambda *args, **kwargs: _Resp())

    server_url = f"https://duplicate-{uuid.uuid4().hex[:8]}.example.com"
    session = SessionLocal()
    created_ids: list[int] = []
    try:
        admin = session.query(User).filter(User.username == "admin").first()
        assert admin is not None
        primary = TableauConnection(
            name=_unique("primary-tableau"),
            server_url=server_url,
            site="sales",
            token_name="pat",
            token_encrypted=_encrypt("secret"),
            owner_id=admin.id,
            api_version="3.21",
            connection_type="mcp",
        )
        legacy_duplicate = TableauConnection(
            name=_unique("legacy-duplicate-tableau"),
            server_url=f"{server_url}/",
            site="/sales",
            token_name="pat",
            token_encrypted=_encrypt("secret"),
            owner_id=admin.id,
            api_version="3.21",
            connection_type="mcp",
        )
        session.add_all([primary, legacy_duplicate])
        session.commit()
        created_ids = [primary.id, legacy_duplicate.id]

        resp = admin_client.put(f"/api/tableau/connections/{primary.id}", json={
            "name": primary.name,
            "server_url": primary.server_url,
            "site": primary.site,
            "api_version": primary.api_version,
            "connection_type": primary.connection_type,
            "auto_sync_enabled": False,
            "schedule_id": None,
            "agent_enabled": True,
        })

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["connection"]["mcp_binding"]["binding_status"] == "bound"
        rest_test.assert_not_called()
    finally:
        if created_ids:
            session.query(McpServer).filter(McpServer.tableau_connection_id.in_(created_ids)).delete(synchronize_session=False)
            session.query(TableauConnection).filter(TableauConnection.id.in_(created_ids)).delete(synchronize_session=False)
            session.commit()
        session.close()


def test_connection_dict_keeps_agent_enabled_for_existing_active_binding(admin_client):
    from app.api.tableau import _encrypt
    from app.core.database import SessionLocal
    from services.auth.models import User
    from services.mcp.models import McpServer
    from services.tableau.models import TableauConnection

    session = SessionLocal()
    created_ids: list[int] = []
    try:
        admin = session.query(User).filter(User.username == "admin").first()
        assert admin is not None
        conn = TableauConnection(
            name=_unique("existing-unhealthy-binding"),
            server_url=f"https://existing-{uuid.uuid4().hex[:8]}.example.com",
            site="sales",
            token_name="pat",
            token_encrypted=_encrypt("secret"),
            owner_id=admin.id,
            api_version="3.21",
            connection_type="mcp",
            mcp_direct_enabled=False,
        )
        session.add(conn)
        session.flush()
        binding = McpServer(
            name=_unique("tableau-binding"),
            type="tableau",
            server_url="http://gateway.local/mcp",
            is_active=True,
            credentials={"tableau_connection_id": conn.id},
            tableau_connection_id=conn.id,
            binding_source="auto_tableau_connection",
            binding_status="unhealthy",
            health_status="unhealthy",
            last_binding_error="gateway down",
        )
        session.add(binding)
        session.commit()
        created_ids = [conn.id]

        payload = conn.to_dict(session)

        assert payload["agent_enabled"] is True
        assert payload["mcp_binding"]["binding_status"] == "unhealthy"
    finally:
        if created_ids:
            session.query(McpServer).filter(McpServer.tableau_connection_id.in_(created_ids)).delete(synchronize_session=False)
            session.query(TableauConnection).filter(TableauConnection.id.in_(created_ids)).delete(synchronize_session=False)
            session.commit()
        session.close()


@pytest.mark.skip_db
def test_tableau_mcp_client_injects_mulan_runtime_headers(monkeypatch):
    import services.tableau.mcp_client as mcp_mod
    from services.tableau.mcp_client import TableauMCPClient

    class _Resp:
        status_code = 200
        text = 'event: message\ndata: {"result": {"content": [{"type": "text", "text": "{\\"fields\\": [], \\"rows\\": []}"}], "isError": false}}\n\n'

    captured_headers = {}
    captured_json = {}

    class _Session:
        def post(self, url, json=None, headers=None, timeout=None):
            captured_headers.update(headers or {})
            captured_json.update(json or {})
            return _Resp()

    conn = mock.Mock()
    conn.id = 42
    conn.server_url = "https://tableau.example.com"
    conn.site = "sales"
    conn.is_active = True
    conn.last_test_success = True
    conn.mcp_direct_enabled = True
    conn.mcp_server_url = "http://gateway.local/mcp"
    conn.mcp_server_id = 99

    monkeypatch.setattr(mcp_mod, "_get_http_session", lambda: _Session())
    monkeypatch.setattr(mcp_mod, "_get_effective_mcp_base_url", lambda _conn: "http://gateway.local/mcp")
    monkeypatch.setattr(mcp_mod, "_load_active_tableau_mcp_binding", lambda _connection_id: {"mcp_server_id": 99, "mcp_server_url": "http://gateway.local/mcp"})
    monkeypatch.setattr(mcp_mod, "_ensure_session", lambda **kwargs: "sid")
    monkeypatch.setattr(TableauMCPClient, "_get_connection_by_luid", lambda self, datasource_luid, connection_id: conn)

    client = TableauMCPClient(connection_id=42, username="alice")
    result = client.query_datasource(
        "ds-1",
        {},
        connection_id=42,
        user_id=7,
        trace_id="trace-1",
    )

    assert result == {"fields": [], "rows": []}
    assert captured_headers["X-Mulan-Tableau-Connection-Id"] == "42"
    assert captured_headers["X-Mulan-Mcp-Server-Id"] == "99"
    assert captured_headers["X-Mulan-User-Id"] == "7"
    assert captured_headers["X-Mulan-Trace-Id"] == "trace-1"
    params = captured_json.get("params") or {}
    assert "tableau_connection_id" not in params
    assert "mcp_server_id" not in params
    assert "user_id" not in params
    assert "trace_id" not in params
