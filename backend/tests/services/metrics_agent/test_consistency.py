"""
Metrics Agent — 一致性校验引擎测试

测试策略：
- mock get_executor 使两个数据源返回可控的值
- 直接调用 run_consistency_check（async）
- 复用 test_registry.py 中已有的 valid_datasource / valid_user fixtures
- 通过 patch emit_consistency_failed 验证事件发射

运行：
    cd /Users/forrest/Projects/mulan-bi-platform/backend
    pytest tests/services/metrics_agent/test_consistency.py -v
"""
import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# 环境变量必须在所有 import 之前设置
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from app.core.errors import MulanError
from services.metrics_agent import registry
from services.metrics_agent.schemas import MetricCreate

# ---------------------------------------------------------------------------
# 共享常量 & helpers
# ---------------------------------------------------------------------------

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_A = 1
USER_B = 2
DS_A = 1
DS_B = 2


def _make_create_data(**kwargs) -> MetricCreate:
    defaults = {
        "name": f"cons_metric_{uuid.uuid4().hex[:8]}",
        "metric_type": "atomic",
        "datasource_id": DS_A,
        "table_name": "fact_orders",
        "column_name": "amount",
        "formula": "SUM(amount)",
        "sensitivity_level": "public",
    }
    defaults.update(kwargs)
    return MetricCreate(**defaults)


def _create_published_metric(db_session):
    """创建并发布一个测试指标，返回 metric ORM 对象。"""
    data = _make_create_data()
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    registry.submit_review(db_session, metric.id, user_id=USER_A, tenant_id=TENANT_ID)
    registry.approve_metric(db_session, metric.id, reviewer_id=USER_B, tenant_id=TENANT_ID)
    metric.lineage_status = "resolved"
    db_session.commit()
    db_session.refresh(metric)
    registry.publish_metric(db_session, metric.id, user_id=USER_B, tenant_id=TENANT_ID)
    db_session.refresh(metric)
    return metric


# ---------------------------------------------------------------------------
# fixtures（复用 test_registry.py 中的模式）
# ---------------------------------------------------------------------------

@pytest.fixture()
def valid_datasource(db_session):
    """确保 bi_data_sources 中有 id=1,2 的数据源（幂等插入）。"""
    from sqlalchemy import text
    for ds_id, ds_name in [(1, "test_ds_a"), (2, "test_ds_b")]:
        existing = db_session.execute(
            text("SELECT id FROM bi_data_sources WHERE id = :id"), {"id": ds_id}
        ).first()
        if existing is None:
            db_session.execute(
                text(
                    """
                    INSERT INTO bi_data_sources
                        (id, name, db_type, host, port, database_name, username,
                         password_encrypted, is_active, owner_id)
                    VALUES
                        (:id, :name, 'postgresql', 'localhost', 5432,
                         'testdb', 'user', 'enc_pwd', true, 1)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": ds_id, "name": ds_name},
            )
    db_session.flush()
    return DS_A, DS_B


@pytest.fixture()
def valid_user(db_session):
    """确保 auth_users 中有 id=1,2 的用户（幂等插入）。"""
    from sqlalchemy import text
    for uid, uname in [(1, "creator"), (2, "reviewer")]:
        existing = db_session.execute(
            text("SELECT id FROM auth_users WHERE id = :id"), {"id": uid}
        ).first()
        if existing is None:
            db_session.execute(
                text(
                    """
                    INSERT INTO auth_users (id, username, display_name, password_hash, email, role, is_active)
                    VALUES (:id, :uname, :uname, 'hash', :email, 'data_admin', true)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": uid, "uname": uname, "email": f"{uname}@test.local"},
            )
    db_session.flush()


# ---------------------------------------------------------------------------
# 辅助：patch _fetch_metric_value 以控制两个数据源的返回值
# ---------------------------------------------------------------------------

def _run_check_with_mocked_values(db_session, metric_id, value_a, value_b, tolerance_pct=5.0):
    """
    调用 run_consistency_check，mock _fetch_metric_value 使 DS_A 返回 value_a，DS_B 返回 value_b。
    返回 check 结果 dict。
    """
    from services.metrics_agent import consistency

    call_count = [0]

    async def _mock_fetch(datasource_id, sql, db, timeout=30):
        call_count[0] += 1
        # 按调用顺序区分 A/B（asyncio.gather 顺序确定）
        if call_count[0] == 1:
            return value_a
        return value_b

    with patch.object(consistency, "_fetch_metric_value", side_effect=_mock_fetch):
        result = asyncio.get_event_loop().run_until_complete(
            consistency.run_consistency_check(
                db=db_session,
                metric_id=metric_id,
                tenant_id=TENANT_ID,
                datasource_id_a=DS_A,
                datasource_id_b=DS_B,
                tolerance_pct=tolerance_pct,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Case 1: 差值在容差内 → check_status="pass"
# ---------------------------------------------------------------------------

def test_consistency_pass(db_session, valid_datasource, valid_user):
    """value_a=100, value_b=102, tolerance=5% → diff_pct=2% → pass"""
    metric = _create_published_metric(db_session)

    result = _run_check_with_mocked_values(
        db_session, metric.id, value_a=100.0, value_b=102.0, tolerance_pct=5.0
    )

    assert result["check_status"] == "pass"
    assert result["metric_id"] == str(metric.id)
    assert result["value_a"] == pytest.approx(100.0)
    assert result["value_b"] == pytest.approx(102.0)
    assert result["difference"] == pytest.approx(-2.0)
    # diff_pct = (-2 / 102) * 100 ≈ -1.96%
    assert abs(result["difference_pct"]) < 5.0
    assert result["id"] is not None


# ---------------------------------------------------------------------------
# Case 2: 差值超出容差 2x 以内 → check_status="warning"
# ---------------------------------------------------------------------------

def test_consistency_warning(db_session, valid_datasource, valid_user):
    """value_a=100, value_b=107, tolerance=5% → diff_pct≈6.5% (5%~10%) → warning"""
    metric = _create_published_metric(db_session)

    result = _run_check_with_mocked_values(
        db_session, metric.id, value_a=100.0, value_b=107.0, tolerance_pct=5.0
    )

    assert result["check_status"] == "warning"
    # diff_pct = (-7 / 107) * 100 ≈ -6.54%，绝对值在 5%~10% 之间
    assert 5.0 < abs(result["difference_pct"]) <= 10.0


# ---------------------------------------------------------------------------
# Case 3: 差值超出容差 2x → check_status="fail"，触发 emit_consistency_failed
# ---------------------------------------------------------------------------

def test_consistency_fail_emits_event(db_session, valid_datasource, valid_user):
    """value_a=100, value_b=120, tolerance=5% → diff_pct≈16.7% > 10% → fail + event"""
    metric = _create_published_metric(db_session)

    with patch(
        "services.metrics_agent.consistency.emit_consistency_failed"
    ) as mock_emit:
        result = _run_check_with_mocked_values(
            db_session, metric.id, value_a=100.0, value_b=120.0, tolerance_pct=5.0
        )

    assert result["check_status"] == "fail"
    assert abs(result["difference_pct"]) > 10.0

    # 验证事件发射被调用一次
    mock_emit.assert_called_once()
    call_kwargs = mock_emit.call_args.kwargs
    assert call_kwargs["metric_id"] == metric.id
    assert call_kwargs["metric_name"] == metric.name
    assert call_kwargs["tenant_id"] == TENANT_ID


# ---------------------------------------------------------------------------
# Case 4: value_b=0 → 除零保护 → difference_pct=None，若 value_a!=0 则 fail
# ---------------------------------------------------------------------------

def test_consistency_zero_divisor_fail(db_session, valid_datasource, valid_user):
    """value_a=100, value_b=0 → 除零，difference_pct=None，check_status=fail"""
    metric = _create_published_metric(db_session)

    with patch("services.metrics_agent.consistency.emit_consistency_failed") as mock_emit:
        result = _run_check_with_mocked_values(
            db_session, metric.id, value_a=100.0, value_b=0.0, tolerance_pct=5.0
        )

    assert result["difference_pct"] is None
    assert result["difference"] == pytest.approx(100.0)
    assert result["check_status"] == "fail"
    mock_emit.assert_called_once()


def test_consistency_both_zero_pass(db_session, valid_datasource, valid_user):
    """value_a=0, value_b=0 → difference=0, difference_pct=None, check_status=pass"""
    metric = _create_published_metric(db_session)

    with patch("services.metrics_agent.consistency.emit_consistency_failed") as mock_emit:
        result = _run_check_with_mocked_values(
            db_session, metric.id, value_a=0.0, value_b=0.0, tolerance_pct=5.0
        )

    assert result["difference"] == pytest.approx(0.0)
    assert result["difference_pct"] is None
    assert result["check_status"] == "pass"
    mock_emit.assert_not_called()


# ---------------------------------------------------------------------------
# Case 5: 查询超时 → 429 MC_429
# ---------------------------------------------------------------------------

def test_consistency_timeout_raises_429(db_session, valid_datasource, valid_user):
    """_fetch_metric_value 超时 → run_consistency_check 抛出 MulanError(MC_429, 429)"""
    metric = _create_published_metric(db_session)

    from services.metrics_agent import consistency

    async def _mock_timeout(datasource_id, sql, db, timeout=30):
        raise asyncio.TimeoutError()

    with patch.object(consistency, "_fetch_metric_value", side_effect=_mock_timeout):
        with pytest.raises(MulanError) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                consistency.run_consistency_check(
                    db=db_session,
                    metric_id=metric.id,
                    tenant_id=TENANT_ID,
                    datasource_id_a=DS_A,
                    datasource_id_b=DS_B,
                    tolerance_pct=5.0,
                )
            )

    assert exc_info.value.status_code == 429
    assert exc_info.value.error_code == "MC_429"


# ---------------------------------------------------------------------------
# Case 6: 指标不存在 → 404 MC_404
# ---------------------------------------------------------------------------

def test_consistency_metric_not_found(db_session, valid_datasource, valid_user):
    """不存在的 metric_id → MulanError(MC_404, 404)"""
    nonexistent_id = uuid.uuid4()

    from services.metrics_agent import consistency

    async def _mock_fetch(*args, **kwargs):
        return 100.0

    with patch.object(consistency, "_fetch_metric_value", side_effect=_mock_fetch):
        with pytest.raises(MulanError) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                consistency.run_consistency_check(
                    db=db_session,
                    metric_id=nonexistent_id,
                    tenant_id=TENANT_ID,
                    datasource_id_a=DS_A,
                    datasource_id_b=DS_B,
                )
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "MC_404"
