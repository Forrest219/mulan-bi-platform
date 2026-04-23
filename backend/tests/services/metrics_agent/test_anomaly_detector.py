"""
Metrics Agent — 异常检测引擎测试

算法层测试（纯 Python，无数据库依赖）：
- Z-Score 检测
- 分位数检测
- 趋势偏离检测
- 数据点不足处理

状态流转测试（需 db fixture）：
- 合法流转：detected → investigating → resolved
- 非法流转：400 错误
"""

import os
import uuid

# 环境变量必须在所有 import 之前设置
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.metrics_agent.anomaly_detector import (
    AnomalyResult,
    detect_quantile,
    detect_trend_deviation,
    detect_zscore,
)


# =============================================================================
# 算法层测试（纯 Python，无数据库）
# =============================================================================

class TestDetectZscore:
    """Z-Score 检测算法测试"""

    def test_detects_anomaly(self):
        """明显异常值（均值约 10，当前值 50）应被检测出来。"""
        values = [10.0, 10.2, 9.8, 10.1, 9.9, 50.0]
        result = detect_zscore(values, threshold=2.0)

        assert isinstance(result, AnomalyResult)
        assert result.is_anomaly is True
        assert result.metric_value == 50.0
        assert result.deviation_score > 2.0
        assert result.deviation_threshold == 2.0

    def test_no_anomaly_for_normal_value(self):
        """正常范围内的值不应被检测为异常。"""
        values = [10.0, 10.2, 9.8, 10.1, 9.9, 10.3]
        result = detect_zscore(values, threshold=3.0)

        assert result.is_anomaly is False
        assert result.metric_value == 10.3

    def test_expected_value_is_mean_of_history(self):
        """expected_value 应为历史值均值。"""
        values = [10.0, 20.0, 30.0, 100.0]
        result = detect_zscore(values, threshold=100.0)  # 高阈值，不触发异常

        expected_mean = (10.0 + 20.0 + 30.0) / 3
        assert abs(result.expected_value - expected_mean) < 1e-9

    def test_zero_std_returns_no_anomaly(self):
        """历史值全部相同（std=0）时，不应视为异常。"""
        values = [5.0, 5.0, 5.0, 5.0, 5.0, 10.0]
        result = detect_zscore(values, threshold=3.0)

        assert result.is_anomaly is False
        assert result.deviation_score == 0.0

    def test_threshold_boundary(self):
        """设置极高阈值时，即使有偏差也不触发异常。"""
        # values 均值约 10，std 极小，z-score 对于 10.5 约 0.5
        values = [10.0, 10.0, 10.0, 10.0, 10.0, 10.5]
        # z-score 约 0.5，设置阈值 3.0，不应触发
        result = detect_zscore(values, threshold=3.0)
        assert result.is_anomaly is False


class TestDetectQuantile:
    """分位数检测算法测试"""

    def test_detects_anomaly_above_upper(self):
        """值远超上分位数（95%）应被检测为异常。"""
        values = list(range(1, 21)) + [100.0]  # 历史 [1..20]，当前 100
        result = detect_quantile(values)

        assert result.is_anomaly is True
        assert result.metric_value == 100.0
        assert result.deviation_score > 0

    def test_no_anomaly_for_median_value(self):
        """历史中位数附近的值不应被检测为异常。"""
        values = list(range(1, 21)) + [10.0]  # 历史 [1..20]，当前 10（中位）
        result = detect_quantile(values)

        assert result.is_anomaly is False

    def test_detects_anomaly_below_lower(self):
        """值远低于下分位数（5%）应被检测为异常。"""
        values = list(range(50, 71)) + [-100.0]  # 历史 [50..70]，当前 -100
        result = detect_quantile(values)

        assert result.is_anomaly is True
        assert result.deviation_score > 0


class TestDetectTrendDeviation:
    """趋势偏离检测算法测试"""

    def test_detects_anomaly_with_large_deviation(self):
        """线性上升趋势中，当前值远超预测（20 vs 约 6）应触发异常。"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 20.0]
        result = detect_trend_deviation(values, threshold_pct=20.0)

        assert result.is_anomaly is True
        assert result.metric_value == 20.0
        # 预测值应接近 6.0（线性外推）
        assert abs(result.expected_value - 6.0) < 1.0

    def test_no_anomaly_for_trend_consistent_value(self):
        """符合线性趋势的当前值不应触发异常。"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        result = detect_trend_deviation(values, threshold_pct=20.0)

        assert result.is_anomaly is False

    def test_deviation_score_is_percentage(self):
        """deviation_score 应为百分比偏差值。"""
        values = [10.0, 10.0, 10.0, 10.0, 10.0, 100.0]
        result = detect_trend_deviation(values, threshold_pct=20.0)

        assert result.is_anomaly is True
        assert result.deviation_score > 20.0

    def test_threshold_pct_controls_sensitivity(self):
        """高阈值时，同样的偏差不触发异常。"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 20.0]
        result = detect_trend_deviation(values, threshold_pct=500.0)

        assert result.is_anomaly is False


class TestInsufficientData:
    """数据点不足时的行为测试"""

    def test_zscore_insufficient_data_returns_no_anomaly(self):
        """Z-Score：少于 3 个点时，直接返回无异常。"""
        result = detect_zscore([10.0, 20.0])  # 只有 2 个点
        assert result.is_anomaly is False
        assert result.deviation_score == 0.0

    def test_zscore_single_point(self):
        """Z-Score：只有 1 个点时，直接返回无异常。"""
        result = detect_zscore([10.0])
        assert result.is_anomaly is False

    def test_zscore_empty_list(self):
        """Z-Score：空列表时，直接返回无异常。"""
        result = detect_zscore([])
        assert result.is_anomaly is False

    def test_quantile_insufficient_data_returns_no_anomaly(self):
        """分位数：少于 3 个点时，直接返回无异常。"""
        result = detect_quantile([10.0, 20.0])
        assert result.is_anomaly is False

    def test_trend_deviation_insufficient_data_returns_no_anomaly(self):
        """趋势偏离：少于 3 个点时，直接返回无异常。"""
        result = detect_trend_deviation([10.0, 20.0])
        assert result.is_anomaly is False

    def test_exactly_three_points(self):
        """恰好 3 个点时应正常运行（不报数据不足）。"""
        values = [10.0, 10.0, 50.0]
        result = detect_zscore(values, threshold=1.0)
        # 有 2 个历史点，能计算 std，正常运行
        assert isinstance(result, AnomalyResult)


class TestAnomalyResultFields:
    """AnomalyResult 字段完整性测试"""

    def test_all_fields_present(self):
        """AnomalyResult 应包含所有必要字段。"""
        values = [10.0, 10.2, 9.8, 10.1, 9.9, 50.0]
        result = detect_zscore(values, threshold=2.0)

        assert hasattr(result, "is_anomaly")
        assert hasattr(result, "metric_value")
        assert hasattr(result, "expected_value")
        assert hasattr(result, "deviation_score")
        assert hasattr(result, "deviation_threshold")

        assert isinstance(result.is_anomaly, bool)
        assert isinstance(result.metric_value, float)
        assert isinstance(result.expected_value, float)
        assert isinstance(result.deviation_score, float)
        assert isinstance(result.deviation_threshold, float)

    def test_metric_value_is_last_element(self):
        """metric_value 应始终等于 values[-1]。"""
        values = [1.0, 2.0, 3.0, 4.0, 99.9]
        result = detect_zscore(values)
        assert result.metric_value == 99.9

        result2 = detect_quantile(values)
        assert result2.metric_value == 99.9

        result3 = detect_trend_deviation(values)
        assert result3.metric_value == 99.9


# =============================================================================
# 状态流转测试（需 db fixture）
# =============================================================================

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_A = 1
USER_B = 2


def _make_metric_fixture(db_session) -> object:
    """创建一个最小化的 BiMetricDefinition 记录，用于异常检测测试。"""
    from sqlalchemy import text

    # 确保依赖数据存在
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

    from models.metrics import BiMetricDefinition

    metric = BiMetricDefinition(
        tenant_id=TENANT_ID,
        name=f"anomaly_test_metric_{uuid.uuid4().hex[:8]}",
        metric_type="atomic",
        datasource_id=1,
        table_name="fact_orders",
        column_name="amount",
        formula="SUM(amount)",
        is_active=True,
        lineage_status="resolved",
        sensitivity_level="public",
        created_by=USER_A,
    )
    db_session.add(metric)
    db_session.flush()
    return metric


def _make_anomaly_fixture(db_session, metric, status: str = "detected") -> object:
    """创建一个 BiMetricAnomaly 记录，用于状态流转测试。"""
    from datetime import datetime, timezone
    from models.metrics import BiMetricAnomaly

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


class TestStatusTransition:
    """状态流转测试"""

    def test_valid_transition_detected_to_investigating(self, db_session):
        """detected → investigating 应成功。"""
        from services.metrics_agent.anomaly_service import update_anomaly_status
        from app.core.errors import MulanError

        metric = _make_metric_fixture(db_session)
        anomaly = _make_anomaly_fixture(db_session, metric, status="detected")

        updated = update_anomaly_status(
            db=db_session,
            anomaly_id=anomaly.id,
            tenant_id=TENANT_ID,
            new_status="investigating",
        )

        assert updated.status == "investigating"

    def test_valid_transition_investigating_to_resolved(self, db_session):
        """investigating → resolved 应成功，并记录 resolved_at / resolved_by。"""
        from services.metrics_agent.anomaly_service import update_anomaly_status

        metric = _make_metric_fixture(db_session)
        anomaly = _make_anomaly_fixture(db_session, metric, status="investigating")

        updated = update_anomaly_status(
            db=db_session,
            anomaly_id=anomaly.id,
            tenant_id=TENANT_ID,
            new_status="resolved",
            resolved_by=USER_B,
            resolution_note="已确认并修复数据管道问题",
        )

        assert updated.status == "resolved"
        assert updated.resolved_by == USER_B
        assert updated.resolved_at is not None
        assert updated.resolution_note == "已确认并修复数据管道问题"

    def test_valid_transition_detected_to_false_positive(self, db_session):
        """detected → false_positive 应成功。"""
        from services.metrics_agent.anomaly_service import update_anomaly_status

        metric = _make_metric_fixture(db_session)
        anomaly = _make_anomaly_fixture(db_session, metric, status="detected")

        updated = update_anomaly_status(
            db=db_session,
            anomaly_id=anomaly.id,
            tenant_id=TENANT_ID,
            new_status="false_positive",
        )

        assert updated.status == "false_positive"

    def test_valid_transition_investigating_to_false_positive(self, db_session):
        """investigating → false_positive 应成功。"""
        from services.metrics_agent.anomaly_service import update_anomaly_status

        metric = _make_metric_fixture(db_session)
        anomaly = _make_anomaly_fixture(db_session, metric, status="investigating")

        updated = update_anomaly_status(
            db=db_session,
            anomaly_id=anomaly.id,
            tenant_id=TENANT_ID,
            new_status="false_positive",
        )

        assert updated.status == "false_positive"

    def test_invalid_transition_resolved_to_investigating(self, db_session):
        """resolved → investigating 应返回 400 MC_400。"""
        from services.metrics_agent.anomaly_service import update_anomaly_status
        from app.core.errors import MulanError

        metric = _make_metric_fixture(db_session)
        anomaly = _make_anomaly_fixture(db_session, metric, status="investigating")

        # 先流转到 resolved
        update_anomaly_status(
            db=db_session,
            anomaly_id=anomaly.id,
            tenant_id=TENANT_ID,
            new_status="resolved",
            resolved_by=USER_B,
        )

        # 再尝试从 resolved → investigating → 应该失败
        with pytest.raises(MulanError) as exc_info:
            update_anomaly_status(
                db=db_session,
                anomaly_id=anomaly.id,
                tenant_id=TENANT_ID,
                new_status="investigating",
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "MC_400"

    def test_invalid_transition_false_positive_to_resolved(self, db_session):
        """false_positive → resolved 应返回 400。"""
        from services.metrics_agent.anomaly_service import update_anomaly_status
        from app.core.errors import MulanError

        metric = _make_metric_fixture(db_session)
        anomaly = _make_anomaly_fixture(db_session, metric, status="false_positive")

        with pytest.raises(MulanError) as exc_info:
            update_anomaly_status(
                db=db_session,
                anomaly_id=anomaly.id,
                tenant_id=TENANT_ID,
                new_status="resolved",
            )

        assert exc_info.value.status_code == 400

    def test_anomaly_not_found_returns_404(self, db_session):
        """不存在的 anomaly_id 应返回 404。"""
        from services.metrics_agent.anomaly_service import update_anomaly_status
        from app.core.errors import MulanError

        with pytest.raises(MulanError) as exc_info:
            update_anomaly_status(
                db=db_session,
                anomaly_id=uuid.uuid4(),  # 随机不存在的 ID
                tenant_id=TENANT_ID,
                new_status="investigating",
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.error_code == "MC_404"

    def test_tenant_isolation(self, db_session):
        """不同 tenant_id 不应能操作其他 tenant 的异常记录。"""
        from services.metrics_agent.anomaly_service import update_anomaly_status
        from app.core.errors import MulanError

        metric = _make_metric_fixture(db_session)
        anomaly = _make_anomaly_fixture(db_session, metric, status="detected")

        other_tenant = uuid.UUID("00000000-0000-0000-0000-000000000099")

        with pytest.raises(MulanError) as exc_info:
            update_anomaly_status(
                db=db_session,
                anomaly_id=anomaly.id,
                tenant_id=other_tenant,
                new_status="investigating",
            )

        assert exc_info.value.status_code == 404
