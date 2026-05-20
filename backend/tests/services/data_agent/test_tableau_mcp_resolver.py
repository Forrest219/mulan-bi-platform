import pytest

from services.data_agent.tableau_mcp_resolver import DatasourceCandidateResolver, normalize_candidate_text
from services.data_agent.tool_base import ToolContext

pytestmark = pytest.mark.skip_db


def _context(connection_id=7, user_id=42, role=None):
    return ToolContext(session_id="s1", user_id=user_id, connection_id=connection_id, user_role=role)


def _resolver(assets, *, accessible=True, belongs=True):
    return DatasourceCandidateResolver(
        datasource_asset_loader=lambda connection_id: assets,
        connection_access_checker=lambda connection_id, user_id, user_role: accessible,
        datasource_connection_checker=lambda datasource_luid, connection_id: belongs,
    )


def test_normalize_candidate_text_matches_mainline_rule():
    assert normalize_candidate_text(" Super Store（数据源） ") == "superstore数据源"


def test_resolve_returns_zero_candidates_when_no_match():
    resolver = _resolver(
        [
            {"id": 1, "connection_id": 7, "tableau_id": "ds-orders", "name": "订单数据源"},
        ]
    )

    assert resolver.resolve("介绍 财务数据源", _context()) == []


def test_resolve_returns_one_exact_candidate_before_contains():
    resolver = _resolver(
        [
            {"id": 1, "connection_id": 7, "tableau_id": "ds-superstore", "name": "SuperStore 数据源"},
            {"id": 2, "connection_id": 7, "tableau_id": "ds-superstore-copy", "name": "SuperStore 数据源副本"},
        ]
    )

    candidates = resolver.resolve("介绍 SuperStore 数据源", _context())

    assert len(candidates) == 1
    assert candidates[0]["datasource_luid"] == "ds-superstore"
    assert candidates[0]["luid"] == "ds-superstore"


def test_resolve_returns_contains_candidates_capped_at_five():
    assets = [
        {"id": index, "connection_id": 7, "tableau_id": f"ds-{index}", "name": f"订单数据源 {index}"}
        for index in range(1, 8)
    ]
    resolver = _resolver(assets)

    candidates = resolver.resolve("介绍 订单数据源", _context())

    assert [item["datasource_luid"] for item in candidates] == ["ds-1", "ds-2", "ds-3", "ds-4", "ds-5"]


def test_resolve_rejects_inaccessible_connection_before_asset_lookup():
    calls = []
    resolver = DatasourceCandidateResolver(
        datasource_asset_loader=lambda connection_id: calls.append(connection_id) or [],
        connection_access_checker=lambda connection_id, user_id, user_role: False,
    )

    assert resolver.resolve("介绍 订单数据源", _context()) == []
    assert calls == []


def test_datasource_belongs_to_connection_uses_injected_checker():
    resolver = _resolver([], belongs=False)

    assert resolver.datasource_belongs_to_connection("ds-1", 7) is False
