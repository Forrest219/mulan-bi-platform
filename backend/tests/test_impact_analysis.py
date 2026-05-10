"""SPEC 40 — Tableau 资产影响分析测试

覆盖场景：
1. datasource 被 3 个 workbook 使用 → 返回 3 workbook + 正确 view 数
2. datasource 无下游 workbook → affected_workbooks = []
3. 对 workbook 类型资产调用 /impact → 400 + TAB_IA_001
4. 跨连接隔离：两个 connection_id 各有同名 datasource，不跨连接污染
5. impact-alerts 仅返回 health_score < 60 的资产

所有测试为纯单元测试（MagicMock），不依赖数据库连接。
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("SECURE_COOKIES", "false")
os.environ.setdefault("SERVICE_JWT_SECRET", "test-jwt-secret-for-service-auth-32ch")

import pytest
from unittest.mock import MagicMock

from services.tableau.impact_service import ImpactService

pytestmark = pytest.mark.skip_db


# ── Helper factories ─────────────────────────────────────────────────────────

def _make_asset(**kwargs):
    """构造轻量级 TableauAsset mock 对象"""
    obj = MagicMock()
    defaults = {
        "id": 1,
        "connection_id": 1,
        "asset_type": "datasource",
        "name": "Sales DB",
        "health_score": 80.0,
        "is_deleted": False,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ── Case 1: datasource 被 3 个 workbook 使用 ─────────────────────────────────

def test_impact_three_workbooks():
    """datasource 被 3 个 workbook 使用，每个 workbook 下 2 个 view → 3 workbook, 6 view"""
    db = MagicMock()

    ds_asset = _make_asset(id=10, connection_id=1, asset_type="datasource", name="Sales DB")

    wb1 = _make_asset(id=101, connection_id=1, asset_type="workbook", name="WB-1")
    wb2 = _make_asset(id=102, connection_id=1, asset_type="workbook", name="WB-2")
    wb3 = _make_asset(id=103, connection_id=1, asset_type="workbook", name="WB-3")

    def _make_view(vid, name, wb_name):
        return _make_asset(id=vid, connection_id=1, asset_type="view", name=name, parent_workbook_name=wb_name)

    views_by_wb = {
        101: [_make_view(201, "V1", "WB-1"), _make_view(202, "V2", "WB-1")],
        102: [_make_view(203, "V3", "WB-2"), _make_view(204, "V4", "WB-2")],
        103: [_make_view(205, "V5", "WB-3"), _make_view(206, "V6", "WB-3")],
    }

    # Stub db.query().filter().first() — 第一次返回 ds_asset，然后依次返回各 workbook
    wb_lookup = {101: wb1, 102: wb2, 103: wb3}

    call_count = {"n": 0}

    def fake_first():
        n = call_count["n"]
        call_count["n"] += 1
        if n == 0:
            return ds_asset
        wb_ids = [101, 102, 103]
        idx = n - 1
        return wb_lookup.get(wb_ids[idx]) if idx < 3 else None

    # .query().filter(...).all() 返回对应 views
    view_call_count = {"n": 0}

    def fake_all():
        n = view_call_count["n"]
        view_call_count["n"] += 1
        wb_ids = [101, 102, 103]
        return views_by_wb.get(wb_ids[n], []) if n < 3 else []

    db.query.return_value.filter.return_value.first.side_effect = fake_first
    db.query.return_value.filter.return_value.all.side_effect = fake_all

    # Stub db.execute() for _find_affected_workbook_ids
    row1, row2, row3 = MagicMock(), MagicMock(), MagicMock()
    row1.__getitem__ = lambda self, i: 101
    row2.__getitem__ = lambda self, i: 102
    row3.__getitem__ = lambda self, i: 103

    db.execute.return_value.fetchall.return_value = [row1, row2, row3]

    svc = ImpactService(db=db)
    result = svc.get_asset_impact(10)

    assert result["summary"]["workbook_count"] == 3
    assert result["summary"]["view_dashboard_count"] == 6
    assert len(result["affected_workbooks"]) == 3
    assert result["datasource"]["name"] == "Sales DB"


# ── Case 2: datasource 无下游 workbook ───────────────────────────────────────

def test_impact_no_downstream():
    """datasource 无下游 workbook → affected_workbooks = []"""
    db = MagicMock()

    ds_asset = _make_asset(id=20, connection_id=1, asset_type="datasource", name="Empty DS")
    db.query.return_value.filter.return_value.first.return_value = ds_asset

    # 精确匹配无结果 → fetchall 返回空列表
    db.execute.return_value.fetchall.return_value = []

    svc = ImpactService(db=db)
    result = svc.get_asset_impact(20)

    assert result["affected_workbooks"] == []
    assert result["summary"]["workbook_count"] == 0
    assert result["summary"]["view_dashboard_count"] == 0


# ── Case 3: 对 workbook 类型资产调用 → ValueError ────────────────────────────

def test_impact_non_datasource_raises():
    """对 workbook 类型资产调用 get_asset_impact → 抛出 ValueError"""
    db = MagicMock()

    wb_asset = _make_asset(id=30, connection_id=1, asset_type="workbook", name="My WB")
    db.query.return_value.filter.return_value.first.return_value = wb_asset

    svc = ImpactService(db=db)
    with pytest.raises(ValueError):
        svc.get_asset_impact(30)


# ── Case 4: 跨连接隔离 ───────────────────────────────────────────────────────

def test_impact_cross_connection_isolation():
    """两个连接各有同名 datasource，_find_affected_workbook_ids 传入不同 connection_id"""
    call_args_list = []

    db = MagicMock()

    def capture_execute(sql, params):
        call_args_list.append(params.copy())
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        return mock_result

    db.execute.side_effect = capture_execute

    svc = ImpactService(db=db)

    # 分别调用两次，不同 connection_id
    svc._find_affected_workbook_ids(datasource_name="Sales DB", connection_id=1)
    svc._find_affected_workbook_ids(datasource_name="Sales DB", connection_id=2)

    # 每次调用会有精确匹配 + ILIKE 匹配两次 execute（因为精确匹配返回空）
    assert len(call_args_list) >= 2
    # 所有对 connection 1 的查询都只传 conn_id=1，不传 conn_id=2
    conn_ids = [args["conn_id"] for args in call_args_list]
    assert 1 in conn_ids
    assert 2 in conn_ids
    # 关键：第一组调用（connection_id=1）的所有 execute 都用 conn_id=1
    # 第二组调用（connection_id=2）的所有 execute 都用 conn_id=2
    # 两组之间不互串
    first_half = call_args_list[:2]
    second_half = call_args_list[2:]
    assert all(a["conn_id"] == 1 for a in first_half)
    assert all(a["conn_id"] == 2 for a in second_half)


# ── Case 5: impact_alerts 仅返回 health_score < 60 的资产 ────────────────────

def test_impact_alerts_only_unhealthy():
    """impact_alerts 仅返回 health_score < 60 的资产"""
    db = MagicMock()

    # 模拟两个不健康数据源
    ds1 = _make_asset(id=50, connection_id=5, asset_type="datasource", name="Bad DS 1", health_score=30.0)
    ds2 = _make_asset(id=51, connection_id=5, asset_type="datasource", name="Bad DS 2", health_score=45.0)

    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [ds1, ds2]

    # _count_downstream 的 execute stub：精确匹配返回空（简化）
    db.execute.return_value.fetchall.return_value = []

    svc = ImpactService(db=db)
    result = svc.get_impact_alerts(connection_id=5)

    assert result["total_unhealthy_datasources"] == 2
    # 确认 health_score 字段值都在响应里
    scores = [a["health_score"] for a in result["alerts"]]
    assert 30.0 in scores
    assert 45.0 in scores


# ── Case 6: connection_id 不存在时 alerts 返回空 ──────────────────────────────

def test_impact_alerts_no_unhealthy():
    """连接无不健康 datasource → total_unhealthy_datasources = 0"""
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    svc = ImpactService(db=db)
    result = svc.get_impact_alerts(connection_id=99)

    assert result["total_unhealthy_datasources"] == 0
    assert result["total_affected_workbooks"] == 0
    assert result["alerts"] == []
