"""
Metrics Agent — 异常检测服务编排层测试

测试目标：services/metrics_agent/anomaly_service.py
覆盖路径：run_anomaly_detection 主干分支 + update_anomaly_status 补充用例

策略：
- mock _fetch_daily_values，绕开数据源/SQL 层
- mock emit_anomaly_detected，验证事件发射
- 使用真实 db_session + PostgreSQL test DB，测试写 BiMetricAnomaly 路径
- 每个测试后由 conftest 的 rollback 清理数据

注意事项：
- run_anomaly_detection 是 async 函数，pytest.ini 已配置 asyncio_mode=auto，
  async def test_* 函数会被 pytest-asyncio 自动识别并运行。
- run_anomaly_detection 内部调用 db.commit()，commit 后由 fixture 级别的 rollback 清理。
"""

import os

# 环境变量必须在所有 import 之前设置
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from models.metrics import BiMetricAnomaly, BiMetricDefinition

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TENANT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_A = 1
USER_B = 2

# ---------------------------------------------------------------------------
# 内部辅助 — 构造指标和数据源
# ---------------------------------------------------------------------------


def _ensure_deps(db_session):
    """确保 bi_data_sources id=1 和 auth_users id=1,2 存在（幂等）。"""
    from sqlalchemy import text

    db_session.execute(
        text(
            """
            INSERT INTO bi_data_sources
                (id, name, db_type, host, port, database_name, username,
                 password_encrypted, is_active, owner_id)
            VALUES
                (1, 'test_ds', 'postgresql', 'localhost', 5432,
                 'testdb', 'user', 'enc_pwd', true, 1)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    for uid, uname in [(1, "creator"), (2, "reviewer")]:
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


def _make_active_metric(db_session, name: str | None = None) -> BiMetricDefinition:
    """创建一个 is_active=True 的已发布指标（直接写 DB，跳过审核流）。"""
    _ensure_deps(db_session)
    metric = BiMetricDefinition(
        tenant_id=TENANT_ID,
        name=name or f"svc_test_metric_{uuid.uuid4().hex[:8]}",
        metric_type="atomic",
        datasource_id=1,
        table_name="fact_orders",
        column_name="amount",
        formula="SUM(amount)",
        is_active=True,        # 直接激活，绕过审核流程
        lineage_status="resolved",
        sensitivity_level="public",
        created_by=USER_A,
        published_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(metric)
    db_session.flush()
    return metric


def _make_anomaly(db_session, metric: BiMetricDefinition, status: str = "detected") -> BiMetricAnomaly:
    """直接写入一条异常记录。"""
    anomaly = BiMetricAnomaly(
        tenant_id=TENANT_ID,
        metric_id=metric.id,
        datasource_id=1,
        detection_method="zscore",
        metric_value=50.0,
        expected_value=10.0,
        deviation_score=8.5,
        deviation_threshold=3.0,
        detected_at=datetime.now(timezone.utc).replace(tzinfo=None),
        status=status,
    )
    db_session.add(anomaly)
    db_session.flush()
    return anomaly


# ---------------------------------------------------------------------------
# 正常数据 & 异常数据生成
# ---------------------------------------------------------------------------

def _normal_values(n: int = 30) -> list[float]:
    """生成 n 天正常值（在 9.5–10.5 区间，无明显离群点）。"""
    import math
    return [10.0 + 0.2 * math.sin(i) for i in range(n)]


def _anomaly_values(n: int = 30, spike: float = 999.0) -> list[float]:
    """生成 n-1 天正常值 + 最后一天异常值。"""
    values = _normal_values(n - 1)
    values.append(spike)
    return values


# =============================================================================
# 用例 A：run_anomaly_detection 检测无异常
# =============================================================================

async def test_run_anomaly_detection_no_anomaly(db_session):
    """30 天正常数据，zscore 检测应返回 anomaly_count=0，不写 DB 记录。"""
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    metric = _make_active_metric(db_session)
    normal_vals = _normal_values(30)

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=normal_vals,
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    assert result["checked_count"] == 1
    assert result["anomaly_count"] == 0
    assert result["anomaly_ids"] == []

    # 确认 DB 中没有新写入的异常记录
    count = (
        db_session.query(BiMetricAnomaly)
        .filter(
            BiMetricAnomaly.metric_id == metric.id,
            BiMetricAnomaly.tenant_id == TENANT_ID,
        )
        .count()
    )
    assert count == 0


# =============================================================================
# 用例 B：run_anomaly_detection 检测到异常，写 DB + 发射事件
# =============================================================================

async def test_run_anomaly_detection_with_anomaly_writes_db_and_emits_event(db_session):
    """最后一天异常值（999），zscore 应检测为异常，写 DB，并调用 emit_anomaly_detected。"""
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    metric = _make_active_metric(db_session)
    spike_vals = _anomaly_values(30, spike=999.0)

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=spike_vals,
    ), patch(
        "services.metrics_agent.events.emit_anomaly_detected"
    ) as mock_emit:
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    assert result["anomaly_count"] == 1
    assert len(result["anomaly_ids"]) == 1

    # 确认 DB 中有对应记录
    anomaly_id = uuid.UUID(result["anomaly_ids"][0])
    record = db_session.query(BiMetricAnomaly).filter(BiMetricAnomaly.id == anomaly_id).first()
    assert record is not None
    assert record.metric_id == metric.id
    assert record.tenant_id == TENANT_ID
    assert record.detection_method == "zscore"
    assert record.status == "detected"

    # 确认事件被发射一次
    mock_emit.assert_called_once()


# =============================================================================
# 用例 C：metric_ids=None 时检测全 tenant 活跃指标
# =============================================================================

async def test_run_anomaly_detection_all_tenant_metrics(db_session):
    """metric_ids=None 时，should 检测该 tenant 下所有 is_active=True 的指标。"""
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    # 创建 2 个激活指标
    metric1 = _make_active_metric(db_session)
    metric2 = _make_active_metric(db_session)

    normal_vals = _normal_values(30)

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=normal_vals,
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=None,    # 全量检测
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    # checked_count 应 >= 2（可能还有其他测试遗留数据，因此用 >= 而非 ==）
    assert result["checked_count"] >= 2
    assert result["anomaly_count"] == 0


# =============================================================================
# 用例 D：单个指标 _fetch_daily_values 返回空列表（模拟数据源异常），其余继续处理
# =============================================================================

async def test_run_anomaly_detection_fetch_failure_skips_metric(db_session):
    """_fetch_daily_values 返回空列表（数据点 < 3）时，该指标跳过但不中断整体流程。"""
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    metric1 = _make_active_metric(db_session)
    metric2 = _make_active_metric(db_session)

    normal_vals = _normal_values(30)

    # 第一个 metric 返回空列表（< 3 点，跳过），第二个返回正常数据
    call_count = 0

    def _side_effect(db, metric, window_days):
        nonlocal call_count
        call_count += 1
        if metric.id == metric1.id:
            return []   # 触发"数据点不足，跳过"分支
        return normal_vals

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        side_effect=_side_effect,
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric1.id, metric2.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    # 两个指标都被"checked"（checked_count 计数在跳过 continue 之前）
    assert result["checked_count"] == 2
    # 两个都无异常（一个跳过，一个正常）
    assert result["anomaly_count"] == 0
    # _fetch_daily_values 被调用了 2 次
    assert call_count == 2


# =============================================================================
# 用例 D2：_fetch_daily_values 的 executor 抛出异常（连接失败），其余指标继续处理
# =============================================================================

async def test_run_anomaly_detection_executor_exception_is_resilient(db_session):
    """
    第一个指标 executor 抛出异常，_fetch_daily_values 返回空列表（内部已 catch），
    第二个指标正常，整体函数不崩溃。
    """
    from services.metrics_agent.anomaly_service import run_anomaly_detection
    from services.metrics_agent import anomaly_service as _svc_mod

    metric1 = _make_active_metric(db_session)
    metric2 = _make_active_metric(db_session)

    spike_vals = _anomaly_values(30, spike=999.0)

    def _side_effect(db, metric, window_days):
        if metric.id == metric1.id:
            # 模拟 _fetch_daily_values 内部 executor 抛异常后返回 []
            return []
        return spike_vals

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        side_effect=_side_effect,
    ), patch(
        "services.metrics_agent.events.emit_anomaly_detected"
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric1.id, metric2.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    # 函数不整体崩溃
    assert result["checked_count"] == 2
    # 第二个指标检测到异常
    assert result["anomaly_count"] == 1


# =============================================================================
# 用例 E：detection_method="threshold_breach"
# =============================================================================

async def test_run_anomaly_detection_threshold_breach(db_session):
    """threshold_breach 方法：当前值 6.0 > threshold 5.0，应检测为异常。"""
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    metric = _make_active_metric(db_session)

    # 构造数据：历史 29 天约 4.0，最后一天 6.0（超过阈值 5.0）
    vals = [4.0] * 29 + [6.0]

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=vals,
    ), patch(
        "services.metrics_agent.events.emit_anomaly_detected"
    ) as mock_emit:
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="threshold_breach",
            window_days=30,
            threshold=5.0,
        )

    assert result["anomaly_count"] == 1
    assert len(result["anomaly_ids"]) == 1
    mock_emit.assert_called_once()


# =============================================================================
# 用例 E2：detection_method 非法，提前抛出 MulanError
# =============================================================================

async def test_run_anomaly_detection_invalid_method_raises(db_session):
    """非法 detection_method 应立即抛出 MulanError(MC_400, 400)，不执行检测。"""
    from services.metrics_agent.anomaly_service import run_anomaly_detection
    from app.core.errors import MulanError

    metric = _make_active_metric(db_session)

    with pytest.raises(MulanError) as exc_info:
        await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="unknown_method",
            window_days=30,
            threshold=3.0,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "MC_400"


# =============================================================================
# 用例 G：_call_detection_algorithm 直接单元测试（无 DB）
# =============================================================================

class TestCallDetectionAlgorithm:
    """_call_detection_algorithm 内部分发逻辑单元测试（无需 DB）。"""

    def test_zscore_dispatch(self):
        from services.metrics_agent.anomaly_service import _call_detection_algorithm
        # 历史值需要有正常方差，最后一天远超均值才能触发 zscore
        # 均值 ~10，std ~0.2，最后值 100 → z-score >> 2
        import math
        vals = [10.0 + 0.2 * math.sin(i) for i in range(29)] + [100.0]
        result = _call_detection_algorithm(vals, "zscore", threshold=2.0)
        assert result.is_anomaly is True

    def test_quantile_dispatch(self):
        from services.metrics_agent.anomaly_service import _call_detection_algorithm
        vals = list(range(1, 30)) + [999]
        result = _call_detection_algorithm(vals, "quantile", threshold=3.0)
        assert result.is_anomaly is True

    def test_trend_deviation_dispatch(self):
        from services.metrics_agent.anomaly_service import _call_detection_algorithm
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]
        result = _call_detection_algorithm(vals, "trend_deviation", threshold=20.0)
        assert result.is_anomaly is True

    def test_threshold_breach_above(self):
        from services.metrics_agent.anomaly_service import _call_detection_algorithm
        vals = [1.0] * 5 + [10.0]
        result = _call_detection_algorithm(vals, "threshold_breach", threshold=5.0)
        assert result.is_anomaly is True
        assert result.metric_value == 10.0
        assert result.deviation_score == 5.0  # 10 - 5

    def test_threshold_breach_below(self):
        from services.metrics_agent.anomaly_service import _call_detection_algorithm
        vals = [1.0] * 5 + [3.0]
        result = _call_detection_algorithm(vals, "threshold_breach", threshold=5.0)
        assert result.is_anomaly is False
        assert result.deviation_score == 0.0

    def test_threshold_breach_empty_values(self):
        from services.metrics_agent.anomaly_service import _call_detection_algorithm
        result = _call_detection_algorithm([], "threshold_breach", threshold=5.0)
        # current = 0.0（空列表），0.0 < 5.0，无异常
        assert result.is_anomaly is False

    def test_unknown_method_raises_mulan_error(self):
        from services.metrics_agent.anomaly_service import _call_detection_algorithm
        from app.core.errors import MulanError
        with pytest.raises(MulanError) as exc_info:
            _call_detection_algorithm([1.0, 2.0, 3.0], "bad_method", threshold=3.0)
        assert exc_info.value.status_code == 400


# =============================================================================
# 用例 H：_validate_identifier 安全校验
# =============================================================================

class TestValidateIdentifier:
    """_validate_identifier 标识符白名单校验。"""

    def test_valid_identifiers(self):
        from services.metrics_agent.anomaly_service import _validate_identifier
        # 合法标识符不应抛出
        _validate_identifier("fact_orders", "table_name")
        _validate_identifier("order_amount", "column_name")
        _validate_identifier("schema.table", "table_name")

    def test_invalid_identifier_with_space(self):
        from services.metrics_agent.anomaly_service import _validate_identifier
        with pytest.raises(ValueError, match="非法标识符"):
            _validate_identifier("fact orders", "table_name")

    def test_invalid_identifier_with_semicolon(self):
        from services.metrics_agent.anomaly_service import _validate_identifier
        with pytest.raises(ValueError, match="非法标识符"):
            _validate_identifier("fact_orders; DROP TABLE", "table_name")

    def test_invalid_identifier_with_dash(self):
        from services.metrics_agent.anomaly_service import _validate_identifier
        with pytest.raises(ValueError, match="非法标识符"):
            _validate_identifier("fact-orders", "table_name")


# =============================================================================
# 用例 I：update_anomaly_status 补充覆盖 resolution_note 在非 resolved 状态
# =============================================================================

def test_update_anomaly_status_investigating_with_note(db_session):
    """detected → investigating，同时设置 resolution_note，note 应被保存。"""
    from services.metrics_agent.anomaly_service import update_anomaly_status
    _ensure_deps(db_session)
    metric = _make_active_metric(db_session)
    anomaly = _make_anomaly(db_session, metric, status="detected")

    updated = update_anomaly_status(
        db=db_session,
        anomaly_id=anomaly.id,
        tenant_id=TENANT_ID,
        new_status="investigating",
        resolution_note="正在排查数据管道",
    )

    assert updated.status == "investigating"
    assert updated.resolution_note == "正在排查数据管道"
    # resolved_at 不应被设置（只有 resolved 才设置）
    assert updated.resolved_at is None


def test_update_anomaly_status_false_positive_with_note(db_session):
    """investigating → false_positive，设置 resolution_note，note 应被保存。"""
    from services.metrics_agent.anomaly_service import update_anomaly_status
    _ensure_deps(db_session)
    metric = _make_active_metric(db_session)
    anomaly = _make_anomaly(db_session, metric, status="investigating")

    updated = update_anomaly_status(
        db=db_session,
        anomaly_id=anomaly.id,
        tenant_id=TENANT_ID,
        new_status="false_positive",
        resolution_note="数据录入错误，非真实异常",
    )

    assert updated.status == "false_positive"
    assert updated.resolution_note == "数据录入错误，非真实异常"
