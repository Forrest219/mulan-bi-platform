"""
Metrics Agent — 异常告警事件通知集成测试（Spec 30）

测试目标：
1. run_anomaly_detection 检出异常时，publish_anomaly_event 被调用
2. emit_event 将 event + notification 写入 DB
3. 订阅用户收到通知

前置：bi_event_subscriptions 表存在（通过 Alembic 迁移或 fixture 幂等写入）

环境变量（必须在 import 之前设置）：
  DATABASE_URL=postgresql://mulan:mulan@localhost:5432/mulan_bi_test
  SESSION_SECRET=test-session-secret-for-ci-!!
  DATASOURCE_ENCRYPTION_KEY=test-datasource-key-32-bytes-ok!!
  TABLEAU_ENCRYPTION_KEY=test-tableau-key-32-bytes-ok!!
  LLM_ENCRYPTION_KEY=test-llm-key-32-bytes-ok!!!!
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:***@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from models.metrics import BiMetricAnomaly, BiMetricDefinition
from services.events.models import BiEvent, BiNotification, BiEventSubscription


# -----------------------------------------------------------------------
# 常量
# -----------------------------------------------------------------------

TENANT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_A = 1
USER_B = 2


# -----------------------------------------------------------------------
# Fixture：构造测试依赖数据
# -----------------------------------------------------------------------

def _ensure_deps(db_session):
    """确保 bi_data_sources + auth_users 存在（幂等）"""
    from sqlalchemy import text

    db_session.execute(
        text(
            "INSERT INTO bi_data_sources "
            "(id, name, db_type, host, port, database_name, username, "
            "password_encrypted, is_active, owner_id) "
            "VALUES (1, 'test_ds', 'postgresql', 'localhost', 5432, "
            "'testdb', 'user', 'enc_pwd', true, 1) "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    for uid, uname, role in [(1, "creator", "data_admin"), (2, "analyst", "analyst")]:
        db_session.execute(
            text(
                "INSERT INTO auth_users "
                "(id, username, display_name, password_hash, email, role, is_active) "
                "VALUES (:id, :uname, :uname, 'hash', :email, :role, true) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": uid, "uname": uname, "email": f"{uname}@test.local", "role": role},
        )
    db_session.flush()


def _make_active_metric(db_session, name=None):
    """创建 is_active=True 的指标"""
    _ensure_deps(db_session)
    metric = BiMetricDefinition(
        tenant_id=TENANT_ID,
        name=name or f"anomaly_test_metric_{uuid.uuid4().hex[:8]}",
        metric_type="atomic",
        datasource_id=1,
        table_name="fact_orders",
        column_name="amount",
        formula="SUM(amount)",
        is_active=True,
        lineage_status="resolved",
        sensitivity_level="public",
        created_by=USER_A,
        published_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(metric)
    db_session.flush()
    return metric


def _ensure_subscriptions_table(db_session):
    """确保 bi_event_subscriptions 表存在（test DB 可能未执行迁移）"""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError

    try:
        db_session.execute(
            text(
                "SELECT 1 FROM bi_event_subscriptions LIMIT 1"
            )
        )
    except ProgrammingError:
        # 表不存在，创建它
        db_session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS bi_event_subscriptions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                    event_type VARCHAR(64) NOT NULL,
                    target_id VARCHAR(128),
                    is_active BOOLEAN NOT NULL DEFAULT true,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP
                )
                """
            )
        )
        db_session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_event_sub_user_id "
                "ON bi_event_subscriptions(user_id)"
            )
        )
        db_session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_event_sub_event_type "
                "ON bi_event_subscriptions(event_type)"
            )
        )
        db_session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_event_sub_target_id "
                "ON bi_event_subscriptions(target_id)"
            )
        )
        db_session.flush()


# -----------------------------------------------------------------------
# 用例 1：检测到异常 → publish_anomaly_event 被调用（mock 验证）
# -----------------------------------------------------------------------

async def test_run_anomaly_detection_calls_publish_anomaly_event(db_session):
    """检测到异常时，run_anomaly_detection 应调用 publish_anomaly_event"""
    from services.metrics_agent.anomaly_service import run_anomaly_detection

    _ensure_deps(db_session)
    metric = _make_active_metric(db_session)

    # 30 天正常 + 最后一天异常值（zscore 触发）
    import math
    spike_values = [10.0 + 0.2 * math.sin(i) for i in range(29)] + [999.0]

    with patch(
        "services.metrics_agent.anomaly_service._fetch_daily_values",
        return_value=spike_values,
    ), patch(
        "services.metrics_agent.events.publish_anomaly_event"
    ) as mock_publish:
        result = await run_anomaly_detection(
            db=db_session,
            tenant_id=TENANT_ID,
            metric_ids=[metric.id],
            detection_method="zscore",
            window_days=30,
            threshold=3.0,
        )

    assert result["anomaly_count"] == 1
    # publish_anomaly_event 应被调用一次
    mock_publish.assert_called_once()
    call_kwargs = mock_publish.call_args.kwargs
    assert call_kwargs["metric_id"] == metric.id
    assert call_kwargs["metric_name"] == metric.name
    assert call_kwargs["algorithm"] == "zscore"
    assert call_kwargs["anomaly_count"] == 1


# -----------------------------------------------------------------------
# 用例 2：publish_anomaly_event → 事件写入 bi_events + bi_notifications
# -----------------------------------------------------------------------

async def test_publish_anomaly_event_writes_event_and_notification(db_session):
    """publish_anomaly_event 应写入 bi_events，且路由至订阅用户时写入 bi_notifications"""
    from services.metrics_agent.events import publish_anomaly_event

    _ensure_deps(db_session)
    _ensure_subscriptions_table(db_session)
    metric = _make_active_metric(db_session)

    # USER_A 订阅该 metric 的 anomaly.detected
    from sqlalchemy import text
    db_session.execute(
        text(
            "INSERT INTO bi_event_subscriptions "
            "(user_id, event_type, target_id, is_active) "
            "VALUES (:uid, 'anomaly.detected', :tid, true) "
            "ON CONFLICT DO NOTHING"
        ),
        {"uid": USER_A, "tid": str(metric.id)},
    )
    db_session.commit()

    # 调用 publish_anomaly_event
    publish_anomaly_event(
        db=db_session,
        metric_id=metric.id,
        metric_name=metric.name,
        algorithm="zscore",
        anomaly_count=1,
        max_score=8.5,
        window_start="2026-04-01",
        window_end="2026-04-30",
        tenant_id=TENANT_ID,
        detected_at=datetime.now(timezone.utc),
    )

    # 验证 bi_events 有记录
    events = db_session.query(BiEvent).filter(
        BiEvent.event_type == "anomaly.detected",
    ).all()
    assert len(events) >= 1
    evt = events[0]
    assert evt.source_module == "metrics"
    assert evt.severity == "warning"
    payload = evt.payload_json
    assert payload["metric_id"] == str(metric.id)
    assert payload["metric_name"] == metric.name
    assert payload["algorithm"] == "zscore"
    assert payload["anomaly_count"] == 1
    assert "detected_at" in payload

    # 验证 bi_notifications 有记录（路由至订阅用户 USER_A）
    notifs = db_session.query(BiNotification).filter(
        BiNotification.event_id == evt.id,
    ).all()
    assert len(notifs) >= 1
    # 确认通知目标包含 USER_A
    notif_user_ids = {n.user_id for n in notifs}
    assert USER_A in notif_user_ids


# -----------------------------------------------------------------------
# 用例 3：订阅用户收到通知，非订阅用户不收到通知
# -----------------------------------------------------------------------

async def test_only_subscribed_users_receive_notification(db_session):
    """只有订阅了对应 metric 的用户才收到通知"""
    from services.metrics_agent.events import publish_anomaly_event

    _ensure_deps(db_session)
    _ensure_subscriptions_table(db_session)
    metric = _make_active_metric(db_session)

    # USER_A 订阅该 metric，USER_B 不订阅
    from sqlalchemy import text
    db_session.execute(
        text(
            "INSERT INTO bi_event_subscriptions "
            "(user_id, event_type, target_id, is_active) "
            "VALUES (:uid, 'anomaly.detected', :tid, true) "
            "ON CONFLICT DO NOTHING"
        ),
        {"uid": USER_A, "tid": str(metric.id)},
    )
    db_session.commit()

    publish_anomaly_event(
        db=db_session,
        metric_id=metric.id,
        metric_name=metric.name,
        algorithm="quantile",
        anomaly_count=2,
        max_score=3.7,
        window_start="2026-04-01",
        window_end="2026-04-30",
        tenant_id=TENANT_ID,
    )

    evt = db_session.query(BiEvent).filter(
        BiEvent.event_type == "anomaly.detected",
    ).order_by(BiEvent.id.desc()).first()

    notifs = db_session.query(BiNotification).filter(
        BiNotification.event_id == evt.id,
    ).all()
    notif_user_ids = {n.user_id for n in notifs}

    # USER_A 收到通知
    assert USER_A in notif_user_ids
    # USER_B（未订阅）不收到通知
    assert USER_B not in notif_user_ids


# -----------------------------------------------------------------------
# 用例 4：窗口期覆盖 — anomaly_count 和 max_score 字段正确
# -----------------------------------------------------------------------

async def test_anomaly_event_payload_fields(db_session):
    """anomaly.detected 事件 payload 包含所有必需字段"""
    from services.metrics_agent.events import publish_anomaly_event

    _ensure_deps(db_session)
    metric = _make_active_metric(db_session)

    publish_anomaly_event(
        db=db_session,
        metric_id=metric.id,
        metric_name=metric.name,
        algorithm="trend_deviation",
        anomaly_count=5,
        max_score=12.345,
        window_start="2026-04-01",
        window_end="2026-04-30",
        tenant_id=TENANT_ID,
    )

    evt = db_session.query(BiEvent).filter(
        BiEvent.event_type == "anomaly.detected",
    ).order_by(BiEvent.id.desc()).first()

    payload = evt.payload_json
    assert "metric_id" in payload
    assert "metric_name" in payload
    assert "algorithm" in payload
    assert payload["algorithm"] == "trend_deviation"
    assert "anomaly_count" in payload
    assert payload["anomaly_count"] == 5
    assert "max_score" in payload
    assert abs(payload["max_score"] - 12.345) < 0.001
    assert "window_start" in payload
    assert "window_end" in payload
    assert "detected_at" in payload
