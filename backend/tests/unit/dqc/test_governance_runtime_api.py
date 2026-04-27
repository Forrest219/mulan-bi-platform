"""Governance Runtime API 单元测试

测试覆盖:
- POST /governance/rules       — 创建规则
- GET  /governance/rules/{id}  — 获取规则
- PUT  /governance/rules/{id}  — 更新规则
- DELETE /governance/rules/{id}— 删除规则
- POST /governance/scan        — 触发扫描
- GET  /governance/results/{id}— 查询扫描结果
- GET  /governance/drift/{id}  — 漂移数据
- GET  /governance/signal/{id}  — 信号灯判定
- 信号灯判定边界值测试（Spec 31 §7.9）
"""
import pytest
from datetime import datetime
from uuid import uuid4
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fake model objects (matching services.dqc.models field shapes)
# ---------------------------------------------------------------------------

class FakeAsset:
    def __init__(self, **fields):
        self.id = fields.get("id", 1)
        self.datasource_id = fields.get("datasource_id", 1)
        self.schema_name = fields.get("schema_name", "dws")
        self.table_name = fields.get("table_name", "dws_order_daily")
        self.display_name = fields.get("display_name", "订单日汇总表")
        self.description = fields.get("description")
        self.dimension_weights = fields.get("dimension_weights", {
            d: 1.0 / 6 for d in
            ["completeness", "accuracy", "timeliness", "validity", "uniqueness", "consistency"]
        })
        self.signal_thresholds = fields.get("signal_thresholds", {
            "p0_score": 60.0, "p1_score": 80.0,
            "drift_p0": 20.0, "drift_p1": 10.0,
            "confidence_p0": 60.0, "confidence_p1": 80.0,
        })
        self.profile_json = fields.get("profile_json", {})
        self.status = fields.get("status", "enabled")
        self.owner_id = fields.get("owner_id", 1)
        self.created_by = fields.get("created_by", 1)
        self.created_at = fields.get("created_at") or datetime(2025, 1, 1, 0, 0, 0)
        self.updated_at = fields.get("updated_at") or datetime(2025, 1, 1, 0, 0, 0)


class FakeRule:
    def __init__(self, **fields):
        self.id = fields.get("id", 1)
        self.asset_id = fields.get("asset_id", 1)
        self.name = fields.get("name", "user_id 非空率")
        self.description = fields.get("description", "user_id 空值率必须 ≥ 99.5%")
        self.dimension = fields.get("dimension", "completeness")
        self.rule_type = fields.get("rule_type", "null_rate")
        self.rule_config = fields.get("rule_config", {"column": "user_id", "max_rate": 0.005})
        self.is_active = fields.get("is_active", True)
        self.is_system_suggested = fields.get("is_system_suggested", False)
        self.suggested_by_llm_analysis_id = fields.get("suggested_by_llm_analysis_id")
        self.created_by = fields.get("created_by", 1)
        self.updated_by = fields.get("updated_by")
        self.created_at = fields.get("created_at") or datetime(2025, 1, 1, 0, 0, 0)
        self.updated_at = fields.get("updated_at") or datetime(2025, 1, 1, 0, 0, 0)


class FakeCycle:
    def __init__(self, **fields):
        self.id = fields.get("id", uuid4())
        self.trigger_type = fields.get("trigger_type", "scheduled")
        self.status = fields.get("status", "completed")
        self.scope = fields.get("scope", "full")
        self.started_at = fields.get("started_at") or datetime(2025, 1, 1, 0, 5, 0)
        self.completed_at = fields.get("completed_at") or datetime(2025, 1, 1, 0, 10, 0)
        self.assets_total = fields.get("assets_total", 37)
        self.assets_processed = fields.get("assets_processed", 37)
        self.assets_failed = fields.get("assets_failed", 0)
        self.rules_executed = fields.get("rules_executed", 412)
        self.p0_count = fields.get("p0_count", 1)
        self.p1_count = fields.get("p1_count", 4)
        self.triggered_by = fields.get("triggered_by")
        self.error_message = fields.get("error_message")
        self.created_at = fields.get("created_at") or datetime(2025, 1, 1, 0, 0, 0)


class FakeSnapshot:
    def __init__(self, **fields):
        self.id = fields.get("id", 1)
        self.cycle_id = fields.get("cycle_id", uuid4())
        self.asset_id = fields.get("asset_id", 1)
        self.confidence_score = fields.get("confidence_score", 76.4)
        self.signal = fields.get("signal", "P1")
        self.prev_signal = fields.get("prev_signal", "GREEN")
        self.dimension_scores = fields.get("dimension_scores", {
            "completeness": 92.0, "accuracy": 70.5, "timeliness": 100.0,
            "validity": 68.0, "uniqueness": 100.0, "consistency": 80.0,
        })
        self.dimension_signals = fields.get("dimension_signals", {
            "completeness": "GREEN", "accuracy": "P1", "timeliness": "GREEN",
            "validity": "P1", "uniqueness": "GREEN", "consistency": "GREEN",
        })
        self.computed_at = fields.get("computed_at") or datetime(2025, 1, 1, 0, 0, 0)


class FakeDimScore:
    """Fake DqcDimensionScore row"""
    def __init__(self, dimension, score, **fields):
        self.asset_id = fields.get("asset_id", 1)
        self.dimension = dimension
        self.score = score
        self.rules_total = fields.get("rules_total", 2)
        self.rules_passed = fields.get("rules_passed", 2)
        self.computed_at = fields.get("computed_at") or datetime(2025, 1, 1, 0, 0, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fake_dim_scores(mapping):
    """mapping: {dimension_name: score} -> [FakeDimScore]"""
    return {dim: FakeDimScore(dim, score) for dim, score in mapping.items()}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


@pytest.fixture
def admin_user():
    return {"id": 1, "role": "admin"}


@pytest.fixture
def data_admin_user():
    return {"id": 2, "role": "data_admin"}


@pytest.fixture
def regular_user():
    return {"id": 3, "role": "user"}


@pytest.fixture
def fake_asset():
    return FakeAsset()


@pytest.fixture
def fake_rule():
    return FakeRule()


@pytest.fixture
def fake_cycle():
    return FakeCycle()


@pytest.fixture
def fake_snapshot():
    return FakeSnapshot()


# ---------------------------------------------------------------------------
# POST /governance/rules
# ---------------------------------------------------------------------------

class TestCreateGovernanceRule:
    """POST /governance/rules"""

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_create_rule_ok(self, mock_cls, mock_db, admin_user, fake_asset, fake_rule):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.rule_name_exists.return_value = False
        mock_dao.create_rule.return_value = fake_rule

        from app.api.governance_runtime import create_governance_rule, GovernanceRuleCreate

        body = GovernanceRuleCreate(
            asset_id=1,
            name="user_id 非空率",
            description="user_id 空值率必须 ≥ 99.5%",
            dimension="completeness",
            rule_type="null_rate",
            rule_config={"column": "user_id", "max_rate": 0.005},
            is_active=True,
        )

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            create_governance_rule(body, current_user=admin_user, db=mock_db)
        )
        assert result.id == fake_rule.id
        assert result.name == fake_rule.name
        assert result.dimension == "completeness"
        mock_dao.create_rule.assert_called_once()
        mock_db.commit.assert_called()

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_create_rule_asset_not_found(self, mock_cls, mock_db, admin_user):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = None

        from app.api.governance_runtime import create_governance_rule, GovernanceRuleCreate
        from app.core.errors import MulanError

        body = GovernanceRuleCreate(
            asset_id=999, name="test",
            dimension="completeness", rule_type="null_rate",
            rule_config={"column": "id", "max_rate": 0.01},
        )

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                create_governance_rule(body, current_user=admin_user, db=mock_db)
            )
        assert exc.value.error_code == "DQC_001"

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_create_rule_duplicate_name(self, mock_cls, mock_db, admin_user, fake_asset):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.rule_name_exists.return_value = True

        from app.api.governance_runtime import create_governance_rule, GovernanceRuleCreate
        from app.core.errors import MulanError

        body = GovernanceRuleCreate(
            asset_id=1, name="existing_rule",
            dimension="completeness", rule_type="null_rate",
            rule_config={"column": "id", "max_rate": 0.01},
        )

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                create_governance_rule(body, current_user=admin_user, db=mock_db)
            )
        assert exc.value.error_code == "DQC_023"

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_create_rule_unsupported_rule_type(self, mock_cls, mock_db, admin_user, fake_asset):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset

        from app.api.governance_runtime import create_governance_rule, GovernanceRuleCreate
        from app.core.errors import MulanError

        body = GovernanceRuleCreate(
            asset_id=1, name="test",
            dimension="completeness", rule_type="unsupported_type",
            rule_config={},
        )

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                create_governance_rule(body, current_user=admin_user, db=mock_db)
            )
        assert exc.value.error_code == "DQC_020"


# ---------------------------------------------------------------------------
# GET /governance/rules/{rule_id}
# ---------------------------------------------------------------------------

class TestGetGovernanceRule:
    """GET /governance/rules/{rule_id}"""

    @patch("app.core.dependencies.get_current_user")
    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_rule_ok(self, mock_cls, mock_get_user, mock_db, admin_user, fake_rule):
        mock_get_user.return_value = admin_user
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_rule.return_value = fake_rule

        from app.api.governance_runtime import get_governance_rule

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_governance_rule(rule_id=1, request=MagicMock(), db=mock_db)
        )
        assert result.id == fake_rule.id
        assert result.name == fake_rule.name

    @patch("app.core.dependencies.get_current_user")
    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_rule_not_found(self, mock_cls, mock_get_user, mock_db, admin_user):
        mock_get_user.return_value = admin_user
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_rule.return_value = None

        from app.api.governance_runtime import get_governance_rule
        from app.core.errors import MulanError

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                get_governance_rule(rule_id=999, request=MagicMock(), db=mock_db)
            )
        assert exc.value.error_code == "DQC_024"


# ---------------------------------------------------------------------------
# PUT /governance/rules/{rule_id}
# ---------------------------------------------------------------------------

class TestUpdateGovernanceRule:
    """PUT /governance/rules/{rule_id}"""

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_update_rule_ok(self, mock_cls, mock_db, admin_user, fake_asset, fake_rule):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_rule.return_value = fake_rule
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.rule_name_exists.return_value = False

        updated_rule = FakeRule(id=1, name="updated_name", description="新的描述")
        mock_dao.get_rule.side_effect = [fake_rule, updated_rule]

        from app.api.governance_runtime import update_governance_rule, GovernanceRuleUpdate

        body = GovernanceRuleUpdate(name="updated_name", description="新的描述")

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            update_governance_rule(rule_id=1, body=body, current_user=admin_user, db=mock_db)
        )
        assert result.name == "updated_name"
        mock_dao.update_rule.assert_called_once()
        mock_db.commit.assert_called()

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_update_rule_not_found(self, mock_cls, mock_db, admin_user):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_rule.return_value = None

        from app.api.governance_runtime import update_governance_rule, GovernanceRuleUpdate
        from app.core.errors import MulanError

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                update_governance_rule(
                    rule_id=999, body=GovernanceRuleUpdate(),
                    current_user=admin_user, db=mock_db
                )
            )
        assert exc.value.error_code == "DQC_024"


# ---------------------------------------------------------------------------
# DELETE /governance/rules/{rule_id}
# ---------------------------------------------------------------------------

class TestDeleteGovernanceRule:
    """DELETE /governance/rules/{rule_id}"""

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_delete_rule_ok(self, mock_cls, mock_db, admin_user, fake_asset, fake_rule):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_rule.return_value = fake_rule
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.delete_rule.return_value = True

        from app.api.governance_runtime import delete_governance_rule

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            delete_governance_rule(rule_id=1, current_user=admin_user, db=mock_db)
        )
        assert result["message"] == "规则已删除"
        assert result["rule_id"] == 1
        mock_dao.delete_rule.assert_called_once_with(mock_db, 1)
        mock_db.commit.assert_called()

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_delete_rule_not_found(self, mock_cls, mock_db, admin_user):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_rule.return_value = None

        from app.api.governance_runtime import delete_governance_rule
        from app.core.errors import MulanError

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                delete_governance_rule(rule_id=999, current_user=admin_user, db=mock_db)
            )
        assert exc.value.error_code == "DQC_024"


# ---------------------------------------------------------------------------
# POST /governance/scan
# ---------------------------------------------------------------------------

class TestTriggerGovernanceScan:
    """POST /governance/scan"""

    @patch("app.api.governance_runtime.is_cycle_locked", return_value=False)
    @patch("app.api.governance_runtime.run_daily_full_cycle")
    def test_trigger_full_scan(self, mock_task, mock_locked, mock_db, admin_user):
        mock_task.delay.return_value = MagicMock(id="celery-task-uuid-123")

        from app.api.governance_runtime import trigger_governance_scan, GovernanceScanRequest

        body = GovernanceScanRequest(scope="full")

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            trigger_governance_scan(body, current_user=admin_user, db=mock_db)
        )
        assert "celery-task-uuid-123" in result.task_ids
        assert "full" in result.message

    @patch("app.api.governance_runtime.is_cycle_locked", return_value=False)
    @patch("app.api.governance_runtime.run_hourly_light_cycle")
    def test_trigger_hourly_light_scan(self, mock_task, mock_locked, mock_db, admin_user):
        mock_task.delay.return_value = MagicMock(id="celery-task-uuid-456")

        from app.api.governance_runtime import trigger_governance_scan, GovernanceScanRequest

        body = GovernanceScanRequest(scope="hourly_light")

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            trigger_governance_scan(body, current_user=admin_user, db=mock_db)
        )
        assert "celery-task-uuid-456" in result.task_ids
        assert "hourly_light" in result.message

    @patch("app.api.governance_runtime.is_cycle_locked", return_value=True)
    def test_trigger_scan_locked(self, mock_locked, mock_db, admin_user):
        from app.api.governance_runtime import trigger_governance_scan, GovernanceScanRequest
        from app.core.errors import MulanError

        body = GovernanceScanRequest(scope="full")

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                trigger_governance_scan(body, current_user=admin_user, db=mock_db)
            )
        assert exc.value.error_code == "DQC_030"

    @patch("app.api.governance_runtime.is_cycle_locked", return_value=False)
    @patch("app.api.governance_runtime.run_for_asset_task")
    @patch("app.api.governance_runtime.DqcDatabase")
    def test_trigger_asset_ids_scan(self, mock_cls, mock_task, mock_locked, mock_db, admin_user, fake_asset):
        mock_task.delay.return_value = MagicMock(id="asset-task-uuid-789")
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        # Return enabled assets for both asset_ids
        mock_dao.get_asset.return_value = fake_asset

        from app.api.governance_runtime import trigger_governance_scan, GovernanceScanRequest

        body = GovernanceScanRequest(scope="full", asset_ids=[1, 2])

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            trigger_governance_scan(body, current_user=admin_user, db=mock_db)
        )
        assert len(result.task_ids) == 2
        assert "scan triggered for 2 asset" in result.message


# ---------------------------------------------------------------------------
# GET /governance/results/{scan_id}
# ---------------------------------------------------------------------------

class TestGetGovernanceScanResults:
    """GET /governance/results/{scan_id}"""

    @patch("app.core.dependencies.get_current_user")
    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_results_by_cycle_id(self, mock_cls, mock_get_user, mock_db, admin_user, fake_cycle, fake_snapshot):
        mock_get_user.return_value = admin_user
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        cycle_id = fake_cycle.id
        mock_dao.get_cycle.return_value = fake_cycle
        mock_dao.get_snapshots_for_cycle.return_value = [fake_snapshot]
        mock_dao.get_asset.return_value = FakeAsset(id=1)
        mock_dao.get_latest_dimension_scores.return_value = fake_dim_scores({
            "completeness": 92.0, "accuracy": 70.5, "timeliness": 100.0,
            "validity": 68.0, "uniqueness": 100.0, "consistency": 80.0,
        })
        mock_dao.get_prev_dimension_scores.return_value = {"completeness": 95.0}
        mock_dao.get_7d_avg_dimension_scores.return_value = {"completeness": 93.0}
        mock_dao.get_rule_results_for_cycle.return_value = []

        from app.api.governance_runtime import get_governance_scan_results

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_governance_scan_results(scan_id=str(cycle_id), request=MagicMock(), db=mock_db)
        )
        assert result.scan_id == str(cycle_id)
        assert result.status == fake_cycle.status
        assert len(result.results) == 1
        assert result.results[0]["asset_id"] == fake_snapshot.asset_id

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_results_cycle_not_found(self, mock_cls, mock_db, admin_user):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_cycle.return_value = None
        mock_dao.list_cycles.return_value = {"items": []}

        from app.api.governance_runtime import get_governance_scan_results
        from app.core.errors import MulanError

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                get_governance_scan_results(scan_id="nonexistent-uuid", request=MagicMock(), db=mock_db)
            )
        assert exc.value.error_code == "DQC_031"


# ---------------------------------------------------------------------------
# GET /governance/drift/{asset_id}
# ---------------------------------------------------------------------------

class TestGetAssetDrift:
    """GET /governance/drift/{asset_id}"""

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_drift_ok(self, mock_cls, mock_db, admin_user, fake_asset):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.get_latest_dimension_scores.return_value = fake_dim_scores({
            "completeness": 85.0, "accuracy": 70.5,
        })
        mock_dao.get_prev_dimension_scores.return_value = {"completeness": 90.0}
        mock_dao.get_7d_avg_dimension_scores.return_value = {"completeness": 88.0}

        from app.api.governance_runtime import get_asset_drift

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_asset_drift(asset_id=1, request=MagicMock(), db=mock_db)
        )
        assert result["asset_id"] == 1
        assert "drift_24h" in result
        assert "drift_vs_7d_avg" in result
        # drift_24h completeness = 85 - 90 = -5
        assert result["drift_24h"]["completeness"] == -5.0

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_drift_asset_not_found(self, mock_cls, mock_db, admin_user):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = None

        from app.api.governance_runtime import get_asset_drift
        from app.core.errors import MulanError

        import asyncio
        with pytest.raises(MulanError) as exc:
            asyncio.get_event_loop().run_until_complete(
                get_asset_drift(asset_id=999, request=MagicMock(), db=mock_db)
            )
        assert exc.value.error_code == "DQC_001"

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_drift_no_prev_score(self, mock_cls, mock_db, admin_user, fake_asset):
        """prev_score=None 时 drift_24h 为 None（不报错）"""
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.get_latest_dimension_scores.return_value = fake_dim_scores({"completeness": 85.0})
        mock_dao.get_prev_dimension_scores.return_value = {}  # 无历史
        mock_dao.get_7d_avg_dimension_scores.return_value = {}  # 无7日均

        from app.api.governance_runtime import get_asset_drift

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_asset_drift(asset_id=1, request=MagicMock(), db=mock_db)
        )
        assert result["drift_24h"]["completeness"] is None
        assert result["drift_vs_7d_avg"]["completeness"] is None


# ---------------------------------------------------------------------------
# GET /governance/signal/{asset_id}
# ---------------------------------------------------------------------------

class TestGetAssetSignal:
    """GET /governance/signal/{asset_id}"""

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_signal_with_snapshot(self, mock_cls, mock_db, admin_user, fake_asset, fake_snapshot):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.get_latest_snapshot.return_value = fake_snapshot

        from app.api.governance_runtime import get_asset_signal

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_asset_signal(asset_id=1, request=MagicMock(), db=mock_db)
        )
        # worst dim among GREEN,P1,GREEN,P1,GREEN,GREEN = P1
        # CS=76.4, p0=60, p1=80 → 60<76.4<80 → CS_signal=P1
        # final = max(P1, P1) = P1
        assert result["signal"] == "P1"
        assert result["confidence_score"] == 76.4

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_get_signal_no_snapshot(self, mock_cls, mock_db, admin_user, fake_asset):
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.get_latest_snapshot.return_value = None

        from app.api.governance_runtime import get_asset_signal

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_asset_signal(asset_id=1, request=MagicMock(), db=mock_db)
        )
        assert result["signal"] is None
        assert "No scan results yet" in result["message"]

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_signal_cs_below_p0_threshold(self, mock_cls, mock_db, admin_user, fake_asset):
        """所有维度 GREEN，但 CS=55 < 60 → 资产信号 P0"""
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.get_latest_snapshot.return_value = FakeSnapshot(
            confidence_score=55.0,
            dimension_signals={
                d: "GREEN" for d in
                ["completeness", "accuracy", "timeliness", "validity", "uniqueness", "consistency"]
            },
        )

        from app.api.governance_runtime import get_asset_signal

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_asset_signal(asset_id=1, request=MagicMock(), db=mock_db)
        )
        assert result["signal"] == "P0"
        assert result["confidence_score_signal"] == "P0"

    @patch("app.api.governance_runtime.DqcDatabase")
    def test_signal_dim_p0_dominates(self, mock_cls, mock_db, admin_user, fake_asset):
        """存在 P0 维度时，资产信号为 P0"""
        mock_dao = MagicMock()
        mock_cls.return_value = mock_dao
        mock_dao.get_asset.return_value = fake_asset
        mock_dao.get_latest_snapshot.return_value = FakeSnapshot(
            confidence_score=90.0,
            dimension_signals={
                "completeness": "GREEN", "accuracy": "GREEN",
                "timeliness": "GREEN", "validity": "P0",
                "uniqueness": "GREEN", "consistency": "GREEN",
            },
        )

        from app.api.governance_runtime import get_asset_signal

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_asset_signal(asset_id=1, request=MagicMock(), db=mock_db)
        )
        assert result["signal"] == "P0"
        assert result["worst_dimension"] == "P0"


# ---------------------------------------------------------------------------
# Signal judgment boundary tests (Spec 31 §7.9 acceptance criteria)
# ---------------------------------------------------------------------------

class TestSignalJudgmentBoundaries:
    """Spec 31 §7.9 信号灯判定边界值验收点"""

    def test_score_59_9_is_p0(self):
        """某维度分=59.9 → P0"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        result = scorer.judge_dimension_signal(
            59.9, drift_24h=None,
            thresholds={"p0_score": 60, "p1_score": 80, "drift_p0": 20, "drift_p1": 10}
        )
        assert result == "P0"

    def test_score_60_0_is_p1(self):
        """某维度分=60.0 → P1（严格 < 80 为 P1）"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        result = scorer.judge_dimension_signal(
            60.0, drift_24h=None,
            thresholds={"p0_score": 60, "p1_score": 80, "drift_p0": 20, "drift_p1": 10}
        )
        assert result == "P1"

    def test_score_80_0_is_green(self):
        """某维度分=80.0 → GREEN"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        result = scorer.judge_dimension_signal(
            80.0, drift_24h=None,
            thresholds={"p0_score": 60, "p1_score": 80, "drift_p0": 20, "drift_p1": 10}
        )
        assert result == "GREEN"

    def test_drift_minus_20_is_p0(self):
        """跌幅 = -20.0 → P0"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        result = scorer.judge_dimension_signal(
            85.0, drift_24h=-20.0,
            thresholds={"p0_score": 60, "p1_score": 80, "drift_p0": 20, "drift_p1": 10}
        )
        assert result == "P0"

    def test_drift_minus_19_99_is_p1(self):
        """跌幅 = -19.99 → P1"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        result = scorer.judge_dimension_signal(
            85.0, drift_24h=-19.99,
            thresholds={"p0_score": 60, "p1_score": 80, "drift_p0": 20, "drift_p1": 10}
        )
        assert result == "P1"

    def test_all_green_but_cs_59_is_p0(self):
        """所有维度 GREEN 但 CS=59 → 资产 P0"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        dim_signals = {d: "GREEN" for d in
                       ["completeness", "accuracy", "timeliness", "validity", "uniqueness", "consistency"]}
        result = scorer.judge_asset_signal(
            dim_signals, 59.0,
            {"confidence_p0": 60, "confidence_p1": 80}
        )
        assert result == "P0"

    def test_prev_score_none_skips_drift(self):
        """prev_score=None 时不触发 drift 判定"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        # score=85, drift=None → GREEN (85 >= 80)
        result = scorer.judge_dimension_signal(
            85.0, drift_24h=None,
            thresholds={"p0_score": 60, "p1_score": 80, "drift_p0": 20, "drift_p1": 10}
        )
        assert result == "GREEN"

    def test_worst_dim_p0_dominates_asset(self):
        """dim_signals={GREEN×5, P0} → 资产 P0"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        dim_signals = {
            "completeness": "GREEN", "accuracy": "GREEN",
            "timeliness": "GREEN", "validity": "GREEN",
            "uniqueness": "GREEN", "consistency": "P0",
        }
        result = scorer.judge_asset_signal(
            dim_signals, 90.0,
            {"confidence_p0": 60, "confidence_p1": 80}
        )
        assert result == "P0"

    def test_cs_60_0_is_p1(self):
        """CS=60.0 → P1（confidence_p0=60 严格小于）"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        dim_signals = {d: "GREEN" for d in
                       ["completeness", "accuracy", "timeliness", "validity", "uniqueness", "consistency"]}
        result = scorer.judge_asset_signal(
            dim_signals, 60.0,
            {"confidence_p0": 60, "confidence_p1": 80}
        )
        assert result == "P1"

    def test_cs_60_01_is_p1(self):
        """CS=60.01 → P1 (60 < 60.01 < 80, strict < boundary)"""
        from services.dqc.scorer import DqcScorer
        scorer = DqcScorer()
        dim_signals = {d: "GREEN" for d in
                       ["completeness", "accuracy", "timeliness", "validity", "uniqueness", "consistency"]}
        result = scorer.judge_asset_signal(
            dim_signals, 60.01,
            {"confidence_p0": 60, "confidence_p1": 80}
        )
        assert result == "P1"
