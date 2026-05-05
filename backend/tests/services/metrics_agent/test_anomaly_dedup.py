"""
Metrics Agent — 异常检测去重窗口与误报反馈学习测试

测试目标：Spec 30 §4.6 实现的两个机制：
1. 1小时去重窗口：同 (metric_id, algorithm, direction, dimension_context_hash) 在 1 小时内只写 1 条 anomaly
2. 24h 误报反馈学习：用户标记 false_positive 后，24h 内相同特征自动 auto_suppressed

策略：
- 使用真实 db_session + PostgreSQL test DB
- mock _fetch_daily_values，绕开数据源/SQL 层
- 每个测试后由 conftest 的 rollback 清理数据
"""

import os

# 环境变量必须在所有 import 之前设置
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

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


def _make_active_metric(
    db_session,
    name: Optional[str] = None,
    filters: Optional[dict] = None,
) -> BiMetricDefinition:
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
        filters=filters,
        is_active=True,
        lineage_status="resolved",
        sensitivity_level="public",
        created_by=USER_A,
        published_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(metric)
    db_session.flush()
    return metric


def _make_anomaly(
    db_session,
    metric: BiMetricDefinition,
    status: str = "detected",
    direction: str = "up",
    algorithm: Optional[str] = "zscore",
    magnitude_bucket: str = "medium",
    detected_at: Optional[datetime] = None,
    dimension_context_hash: Optional[str] = None,
) -> BiMetricAnomaly:
    """直接写入一条异常记录。"""
    anomaly = BiMetricAnomaly(
        tenant_id=TENANT_ID,
        metric_id=metric.id,
        datasource_id=1,
        detection_method=algorithm or "zscore",
        algorithm=algorithm,
        direction=direction,
        dimension_context_hash=dimension_context_hash,
        magnitude_bucket=magnitude_bucket,
        metric_value=50.0,
        expected_value=10.0,
        deviation_score=8.5,
        deviation_threshold=3.0,
        detected_at=detected_at or datetime.now(timezone.utc).replace(tzinfo=None),
        last_seen_at=detected_at or datetime.now(timezone.utc).replace(tzinfo=None),
        status=status,
    )
    db_session.add(anomaly)
    db_session.flush()
    return anomaly


# ---------------------------------------------------------------------------
# 辅助数据生成
# ---------------------------------------------------------------------------


def _spike_values(n: int = 30, spike: float = 999.0) -> list[float]:
    """生成 n-1 天正常值 + 最后一天异常值。"""
    import math
    normal = [10.0 + 0.2 * math.sin(i) for i in range(n - 1)]
    return normal + [spike]


# =============================================================================
# 用例 1：去重窗口命中时只更新 last_seen_at，不 INSERT 新记录
# =============================================================================

async def test_dedup_window_hits_updates_last_seen_at_no_new_insert(db_session):
    """
    在 1 小时去重窗口内再次检测到相同特征的异常，
    应只更新 existing.last_seen_at，不 INSERT 新记录。
    """
    from services.metrics_agent.anomaly_service import (
        run_anomaly_detection,
        _check_dedup_window,
    )

    metric = _make_active_metric(db_session, filters={"region": "us"})
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 先写入一条 active anomaly（1小时内）
    existing_anomaly = _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="large",
        detected_at=now - timedelta(minutes=30),  # 30分钟前
        dimension_context_hash="abc123",
    )
    existing_id = existing_anomaly.id
    original_last_seen = existing_anomaly.last_seen_at

    spike_vals = _spike_values(30, spike=999.0)

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=spike_vals,
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    # 不应写入新 anomaly
    assert result["anomaly_count"] == 0
    assert result["anomaly_ids"] == []

    # 验证 existing anomaly 的 last_seen_at 被更新
    db_session.expire(existing_anomaly)
    updated_anomaly = db_session.query(BiMetricAnomaly).filter(BiMetricAnomaly.id == existing_id).first()
    assert updated_anomaly is not None
    assert updated_anomaly.last_seen_at is not None
    assert updated_anomaly.last_seen_at > original_last_seen


# =============================================================================
# 用例 2：去重窗口外正常 INSERT 新记录
# =============================================================================

async def test_dedup_window_miss_inserts_new_anomaly(db_session):
    """
    超过 1 小时去重窗口，再次检测到异常应正常 INSERT 新记录。
    """
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    metric = _make_active_metric(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 先写入一条 old anomaly（超过1小时）
    _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(hours=2),  # 2小时前，超过去重窗口
    )

    spike_vals = _spike_values(30, spike=999.0)

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=spike_vals,
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    # 应写入新 anomaly
    assert result["anomaly_count"] == 1
    assert len(result["anomaly_ids"]) == 1


# =============================================================================
# 用例 3：false_positive 标记后 24h 内同特征自动 auto_suppressed
# =============================================================================

def test_false_positive_triggers_auto_suppress_same_features(db_session):
    """
    用户将 anomaly 标记为 false_positive 后，
    24h 内相同 (metric_id, algorithm, direction, magnitude_bucket) 的 active anomaly
    应自动变更为 auto_suppressed。
    """
    from services.metrics_agent.anomaly_service import (
        update_anomaly_status,
        _auto_suppress_false_positives,
    )

    _ensure_deps(db_session)
    metric = _make_active_metric(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 创建当前要标记为 false_positive 的 anomaly
    fp_anomaly = _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(hours=1),
    )

    # 创建另一个 24h 内的相同特征 active anomaly
    same_feature_anomaly = _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(hours=2),
    )

    # 创建另一个 24h 内的不同 magnitude_bucket 的 active anomaly
    different_bucket_anomaly = _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="large",  # 不同 bucket
        detected_at=now - timedelta(hours=2),
    )

    # 标记第一个为 false_positive（这会触发 _auto_suppress_false_positives）
    update_anomaly_status(
        db=db_session,
        anomaly_id=fp_anomaly.id,
        tenant_id=TENANT_ID,
        new_status="false_positive",
    )

    # 刷新数据
    db_session.expire_all()

    # 相同特征应被 auto_suppressed
    same_feature = db_session.query(BiMetricAnomaly).filter(
        BiMetricAnomaly.id == same_feature_anomaly.id
    ).first()
    assert same_feature.status == "auto_suppressed"

    # 不同 bucket 不应被影响
    different_bucket = db_session.query(BiMetricAnomaly).filter(
        BiMetricAnomaly.id == different_bucket_anomaly.id
    ).first()
    assert different_bucket.status == "detected"

    # false_positive 的那个状态不变
    fp = db_session.query(BiMetricAnomaly).filter(
        BiMetricAnomaly.id == fp_anomaly.id
    ).first()
    assert fp.status == "false_positive"


# =============================================================================
# 用例 4：跨 magnitude_bucket 不互相抑制
# =============================================================================

def test_auto_suppress_respects_magnitude_bucket(db_session):
    """
    auto_suppress 只对相同 magnitude_bucket 生效，跨 bucket 不互相影响。
    """
    from services.metrics_agent.anomaly_service import update_anomaly_status

    _ensure_deps(db_session)
    metric = _make_active_metric(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 创建 tiny bucket anomaly
    tiny_anomaly = _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="tiny",
        detected_at=now - timedelta(hours=1),
    )

    # 创建 small bucket anomaly
    small_anomaly = _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="small",
        detected_at=now - timedelta(hours=1),
    )

    # 将 tiny 标记为 false_positive
    update_anomaly_status(
        db=db_session,
        anomaly_id=tiny_anomaly.id,
        tenant_id=TENANT_ID,
        new_status="false_positive",
    )

    db_session.expire_all()

    # tiny 变为 false_positive
    tiny = db_session.query(BiMetricAnomaly).filter(
        BiMetricAnomaly.id == tiny_anomaly.id
    ).first()
    assert tiny.status == "false_positive"

    # small 仍为 detected（不受 tiny 影响）
    small = db_session.query(BiMetricAnomaly).filter(
        BiMetricAnomaly.id == small_anomaly.id
    ).first()
    assert small.status == "detected"


# =============================================================================
# 用例 5：方向不同不互相去重/抑制
# =============================================================================

async def test_dedup_respects_direction(db_session):
    """
    方向（up/down）不同，不触发去重窗口。
    """
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    metric = _make_active_metric(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 写入一条 "down" 方向的 anomaly
    _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="down",  # 不同于 "up"
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(minutes=10),
    )

    # 产生 "up" 方向的异常数据
    # 当前值 > 期望值 → up
    spike_vals = [100.0] * 29 + [999.0]  # 异常高值 = up

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=spike_vals,
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    # 应写入新 anomaly（方向不同，不触发去重）
    assert result["anomaly_count"] == 1
    assert len(result["anomaly_ids"]) == 1


# =============================================================================
# 用例 6：dimension_context_hash 不同不互相去重
# =============================================================================

async def test_dedup_respects_dimension_context_hash(db_session):
    """
    dimension_context_hash 不同，不触发去重窗口。
    """
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    # 两个 metric 带有不同的 filters（会产生不同的 hash）
    metric1 = _make_active_metric(db_session, filters={"region": "us"})
    metric2 = _make_active_metric(db_session, filters={"region": "eu"})

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 写入一条 metric1 的 anomaly
    _make_anomaly(
        db_session,
        metric1,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(minutes=10),
    )

    # metric2 产生异常
    spike_vals = _spike_values(30, spike=999.0)

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=spike_vals,
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric2.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    # metric2 应写入新 anomaly（hash 不同，不触发去重）
    assert result["anomaly_count"] == 1
    assert len(result["anomaly_ids"]) == 1


# =============================================================================
# 用例 7：24h 外的 false_positive 不触发 auto_suppress
# =============================================================================

def test_auto_suppress_respects_24h_window(db_session):
    """
    只有 24h 内的相同特征 anomaly 会被 auto_suppressed。
    超过 24h 的不受影响。
    """
    from services.metrics_agent.anomaly_service import update_anomaly_status

    _ensure_deps(db_session)
    metric = _make_active_metric(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 创建当前要标记为 false_positive 的 anomaly
    fp_anomaly = _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(hours=1),
    )

    # 创建 25 小时前的相同特征 anomaly（超过 24h 窗口）
    old_anomaly = _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(hours=25),  # 超过 24h
    )

    # 标记为 false_positive
    update_anomaly_status(
        db=db_session,
        anomaly_id=fp_anomaly.id,
        tenant_id=TENANT_ID,
        new_status="false_positive",
    )

    db_session.expire_all()

    # 24h 内的被 auto_suppressed
    old = db_session.query(BiMetricAnomaly).filter(
        BiMetricAnomaly.id == old_anomaly.id
    ).first()
    assert old.status == "detected"  # 超过 24h，不受影响


# =============================================================================
# 用例 8：resolved 状态的 anomaly 仍参与去重窗口
# =============================================================================

async def test_dedup_window_includes_resolved_status(db_session):
    """
    去重窗口查询 status in ('detected', 'resolved')，
    resolved 的 anomaly 也应触发去重窗口。
    """
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    metric = _make_active_metric(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 写入一条 resolved 状态的 anomaly
    _make_anomaly(
        db_session,
        metric,
        status="resolved",  # resolved 状态
        direction="up",
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(minutes=30),
    )

    spike_vals = _spike_values(30, spike=999.0)

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=spike_vals,
    ):
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    # resolved 状态也触发去重，不写入新 anomaly
    assert result["anomaly_count"] == 0
    assert result["anomaly_ids"] == []


# =============================================================================
# 用例 9：_check_dedup_window 函数直接测试
# =============================================================================

def test_check_dedup_window_returns_true_when_match(db_session):
    """_check_dedup_window 在匹配时应返回 True。"""
    from services.metrics_agent.anomaly_service import _check_dedup_window

    metric = _make_active_metric(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="up",
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(minutes=20),
        dimension_context_hash="hash123",
    )

    result = _check_dedup_window(
        session=db_session,
        metric_id=metric.id,
        algorithm="zscore",
        direction="up",
        dimension_context_hash="hash123",
    )

    assert result is True


def test_check_dedup_window_returns_false_when_no_match(db_session):
    """_check_dedup_window 在不匹配时应返回 False。"""
    from services.metrics_agent.anomaly_service import _check_dedup_window

    metric = _make_active_metric(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 写入一条不同 direction 的 anomaly
    _make_anomaly(
        db_session,
        metric,
        status="detected",
        direction="down",  # 不同方向
        algorithm="zscore",
        magnitude_bucket="medium",
        detected_at=now - timedelta(minutes=20),
    )

    result = _check_dedup_window(
        session=db_session,
        metric_id=metric.id,
        algorithm="zscore",
        direction="up",  # 查询 "up"
        dimension_context_hash=None,
    )

    assert result is False


# =============================================================================
# 用例 10：_compute_magnitude_bucket 边界测试
# =============================================================================

class TestComputeMagnitudeBucket:
    """_compute_magnitude_bucket 边界条件测试。"""

    def test_tiny_bucket(self):
        from services.metrics_agent.anomaly_service import _compute_magnitude_bucket
        # score=3.0, threshold=3.0 → ratio=1.0 → tiny
        assert _compute_magnitude_bucket(3.0, 3.0) == "tiny"

    def test_small_bucket(self):
        from services.metrics_agent.anomaly_service import _compute_magnitude_bucket
        # score=5.0, threshold=3.0 → ratio=1.67 → small
        assert _compute_magnitude_bucket(5.0, 3.0) == "small"

    def test_medium_bucket(self):
        from services.metrics_agent.anomaly_service import _compute_magnitude_bucket
        # score=10.0, threshold=3.0 → ratio=3.33 → medium
        assert _compute_magnitude_bucket(10.0, 3.0) == "medium"

    def test_large_bucket(self):
        from services.metrics_agent.anomaly_service import _compute_magnitude_bucket
        # score=15.0, threshold=3.0 → ratio=5.0 → large
        assert _compute_magnitude_bucket(15.0, 3.0) == "large"

    def test_extreme_bucket(self):
        from services.metrics_agent.anomaly_service import _compute_magnitude_bucket
        # score=20.0, threshold=3.0 → ratio=6.67 → extreme
        assert _compute_magnitude_bucket(20.0, 3.0) == "extreme"

    def test_zero_threshold(self):
        from services.metrics_agent.anomaly_service import _compute_magnitude_bucket
        # threshold=0 时应返回 tiny（避免除零）
        assert _compute_magnitude_bucket(10.0, 0.0) == "tiny"


# =============================================================================
# 用例 11：_compute_direction 边界测试
# =============================================================================

class TestComputeDirection:
    """_compute_direction 边界条件测试。"""

    def test_up_when_metric_value_greater(self):
        from services.metrics_agent.anomaly_service import _compute_direction
        assert _compute_direction(15.0, 10.0) == "up"

    def test_down_when_metric_value_less(self):
        from services.metrics_agent.anomaly_service import _compute_direction
        assert _compute_direction(5.0, 10.0) == "down"

    def test_down_when_equal(self):
        from services.metrics_agent.anomaly_service import _compute_direction
        # 相等时视为 down（不视为正常）
        assert _compute_direction(10.0, 10.0) == "down"


# =============================================================================
# 用例 12：_compute_dimension_context_hash 测试
# =============================================================================

class TestComputeDimensionContextHash:
    """_compute_dimension_context_hash 测试。"""

    def test_none_returns_none(self):
        from services.metrics_agent.anomaly_service import _compute_dimension_context_hash
        assert _compute_dimension_context_hash(None) is None

    def test_same_context_produces_same_hash(self):
        from services.metrics_agent.anomaly_service import _compute_dimension_context_hash
        ctx1 = {"region": "us", "product": "A"}
        ctx2 = {"region": "us", "product": "A"}
        assert _compute_dimension_context_hash(ctx1) == _compute_dimension_context_hash(ctx2)

    def test_different_context_produces_different_hash(self):
        from services.metrics_agent.anomaly_service import _compute_dimension_context_hash
        ctx1 = {"region": "us"}
        ctx2 = {"region": "eu"}
        assert _compute_dimension_context_hash(ctx1) != _compute_dimension_context_hash(ctx2)

    def test_key_order_does_not_affect_hash(self):
        from services.metrics_agent.anomaly_service import _compute_dimension_context_hash
        ctx1 = {"region": "us", "product": "A"}
        ctx2 = {"product": "A", "region": "us"}
        assert _compute_dimension_context_hash(ctx1) == _compute_dimension_context_hash(ctx2)
