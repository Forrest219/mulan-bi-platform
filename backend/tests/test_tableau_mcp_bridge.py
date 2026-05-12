"""Tests for Tableau MCP bridge compatibility behavior."""

import pytest


pytestmark = pytest.mark.skip_db


class _FakeQuery:
    def __init__(self, *, count_value=0, all_value=None):
        self._count_value = count_value
        self._all_value = all_value or []

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return self._count_value

    def all(self):
        return self._all_value


class _FakeDb:
    def __init__(self, query):
        self._query = query

    def query(self, _model):
        return self._query


class _FakeConn:
    def to_dict(self):
        return {"id": 7, "name": "real-tableau", "is_active": True}


class _FakeMcp:
    def __init__(self, mcp_id, name, credentials):
        self.id = mcp_id
        self.name = name
        self.server_url = "http://mcp.local"
        self.credentials = credentials
        self.created_at = None
        self.updated_at = None


def test_sync_mcp_to_tableau_reports_missing_pat_without_creating(monkeypatch):
    from app.api import mcp_configs

    class _Crypto:
        def decrypt(self, value):
            return value

    monkeypatch.setattr("app.core.crypto.get_mcp_crypto", lambda: _Crypto())

    result = mcp_configs._sync_mcp_to_tableau(
        mcp_name="missing-pat",
        mcp_server_url="http://mcp.local",
        credentials={"tableau_server": "https://tableau.local", "pat_name": "pat"},
        owner_id=1,
    )

    assert result["success"] is False
    assert "pat_value" in result["message"]


@pytest.mark.asyncio
async def test_tableau_connections_prefers_real_connections(monkeypatch):
    from app.api import tableau

    class _TableauDb:
        def __init__(self, session):
            pass

        def get_all_connections(self, **_kwargs):
            return [_FakeConn()]

    monkeypatch.setattr(tableau, "get_current_user", lambda request, db: {"id": 1, "role": "admin"})
    monkeypatch.setattr(tableau, "TableauDatabase", _TableauDb)

    response = await tableau.list_connections(
        request=None,
        db=_FakeDb(_FakeQuery(count_value=1)),
    )

    assert response["total"] == 1
    assert response["connections"] == [{"id": 7, "name": "real-tableau", "is_active": True}]


@pytest.mark.asyncio
async def test_tableau_connections_virtual_fallback_only_when_no_real_and_usable(monkeypatch):
    from app.api import tableau

    class _TableauDb:
        def __init__(self, session):
            pass

        def get_all_connections(self, **_kwargs):
            return []

    mcps = [
        _FakeMcp(5, "usable-mcp", {
            "tableau_server": "https://tableau.local",
            "site_name": "sales",
            "pat_name": "pat",
            "pat_value": "secret",
        }),
        _FakeMcp(6, "missing-pat", {
            "tableau_server": "https://tableau.local",
            "pat_name": "pat",
        }),
    ]

    monkeypatch.setattr(tableau, "get_current_user", lambda request, db: {"id": 1, "role": "admin"})
    monkeypatch.setattr(tableau, "TableauDatabase", _TableauDb)

    response = await tableau.list_connections(
        request=None,
        db=_FakeDb(_FakeQuery(all_value=mcps)),
    )

    assert response["total"] == 1
    assert response["connections"][0]["id"] == 10005
    assert response["connections"][0]["source"] == "mcp_virtual_fallback"
