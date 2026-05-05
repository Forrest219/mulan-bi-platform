"""Metrics Agent — events 模块测试"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from services.metrics_agent.events import (
    emit_anomaly_detected,
    emit_consistency_failed,
    emit_metric_published,
    publish_anomaly_event,
)


class TestEmitMetricPublished:
    """emit_metric_published 事件发射测试"""

    @patch("services.metrics_agent.events.emit_event")
    @patch("services.metrics_agent.events._post_to_webhook")
    def test_emits_event_and_webhook(self, mock_webhook, mock_emit_event):
        """验证写入 bi_events 表并触发 Webhook POST"""
        mock_db = MagicMock()
        metric_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        emit_metric_published(
            db=mock_db,
            metric_id=metric_id,
            name="test_metric",
            tenant_id=tenant_id,
        )

        mock_emit_event.assert_called_once()
        mock_webhook.assert_called_once()
        call_args = mock_webhook.call_args
        assert call_args[0][0] == "metric.published"
        assert call_args[0][1]["metric_id"] == str(metric_id)

    @patch("services.metrics_agent.events.emit_event")
    @patch("services.metrics_agent.events._post_to_webhook")
    def test_emit_event_failure_does_not_raise(self, mock_webhook, mock_emit_event):
        """验证 emit_event 失败时不阻断 Webhook POST"""
        mock_db = MagicMock()
        mock_emit_event.side_effect = Exception("DB error")
        metric_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # 不应抛出异常
        emit_metric_published(
            db=mock_db,
            metric_id=metric_id,
            name="test_metric",
            tenant_id=tenant_id,
        )

        # Webhook 仍应被调用
        mock_webhook.assert_called_once()


class TestEmitAnomalyDetected:
    """emit_anomaly_detected 事件发射测试"""

    @patch("services.metrics_agent.events.emit_event")
    @patch("services.metrics_agent.events._post_to_webhook")
    def test_emits_event_with_correct_payload(self, mock_webhook, mock_emit_event):
        """验证异常检测事件载荷包含所有必要字段"""
        mock_db = MagicMock()
        anomaly_id = uuid.uuid4()
        metric_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        emit_anomaly_detected(
            db=mock_db,
            anomaly_id=anomaly_id,
            metric_id=metric_id,
            metric_name="DAU",
            detection_method="zscore",
            deviation_score=3.5,
            tenant_id=tenant_id,
        )

        mock_emit_event.assert_called_once()
        call_kwargs = mock_emit_event.call_args[1]
        assert call_kwargs["payload"]["anomaly_id"] == str(anomaly_id)
        assert call_kwargs["payload"]["deviation_score"] == 3.5

        mock_webhook.assert_called_once()
        webhook_payload = mock_webhook.call_args[0][1]
        assert webhook_payload["detection_method"] == "zscore"

    @patch("services.metrics_agent.events.emit_event")
    @patch("services.metrics_agent.events._post_to_webhook")
    def test_webhook_failure_does_not_propagate(self, mock_webhook, mock_emit_event):
        """验证 Webhook POST 失败不阻断主流程"""
        mock_db = MagicMock()
        mock_webhook.side_effect = Exception("Webhook error")
        metric_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # 不应抛出异常
        emit_anomaly_detected(
            db=mock_db,
            anomaly_id=uuid.uuid4(),
            metric_id=metric_id,
            metric_name="DAU",
            detection_method="zscore",
            deviation_score=3.5,
            tenant_id=tenant_id,
        )

        # emit_event 仍应成功调用
        mock_emit_event.assert_called_once()


class TestEmitConsistencyFailed:
    """emit_consistency_failed 事件发射测试"""

    @patch("services.metrics_agent.events.emit_event")
    @patch("services.metrics_agent.events._post_to_webhook")
    def test_emits_consistency_failed_event(self, mock_webhook, mock_emit_event):
        """验证一致性校验失败事件正确发射"""
        mock_db = MagicMock()
        check_id = uuid.uuid4()
        metric_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        emit_consistency_failed(
            db=mock_db,
            check_id=check_id,
            metric_id=metric_id,
            metric_name="revenue",
            difference_pct=12.5,
            tenant_id=tenant_id,
        )

        mock_emit_event.assert_called_once()
        call_kwargs = mock_emit_event.call_args[1]
        assert call_kwargs["payload"]["difference_pct"] == 12.5

        mock_webhook.assert_called_once()
        webhook_payload = mock_webhook.call_args[0][1]
        assert webhook_payload["difference_pct"] == 12.5

    @patch("services.metrics_agent.events.emit_event")
    @patch("services.metrics_agent.events._post_to_webhook")
    def test_none_difference_pct_handled(self, mock_webhook, mock_emit_event):
        """验证 None 差值百分比的边界情况"""
        mock_db = MagicMock()
        metric_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        emit_consistency_failed(
            db=mock_db,
            check_id=uuid.uuid4(),
            metric_id=metric_id,
            metric_name="revenue",
            difference_pct=None,
            tenant_id=tenant_id,
        )

        mock_emit_event.assert_called_once()
        mock_webhook.assert_called_once()


class TestPublishAnomalyEvent:
    """publish_anomaly_event (Spec 30) 测试"""

    @patch("services.metrics_agent.events.emit_event")
    @patch("services.metrics_agent.events._post_to_webhook")
    def test_publishes_anomaly_detected_event(self, mock_webhook, mock_emit_event):
        """验证 anomaly.detected 事件包含完整 extra_data (Spec 30)"""
        mock_db = MagicMock()
        metric_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        publish_anomaly_event(
            db=mock_db,
            metric_id=metric_id,
            metric_name="DAU",
            algorithm="zscore",
            anomaly_count=2,
            max_score=4.2,
            window_start="2024-01-01",
            window_end="2024-01-31",
            tenant_id=tenant_id,
        )

        mock_emit_event.assert_called_once()
        call_kwargs = mock_emit_event.call_args[1]
        assert call_kwargs["payload"]["algorithm"] == "zscore"
        assert call_kwargs["payload"]["anomaly_count"] == 2
        assert call_kwargs["payload"]["max_score"] == 4.2

        mock_webhook.assert_called_once()
        webhook_payload = mock_webhook.call_args[0][1]
        assert webhook_payload["algorithm"] == "zscore"

    @patch("services.metrics_agent.events.emit_event")
    @patch("services.metrics_agent.events._post_to_webhook")
    def test_detected_at_defaults_to_now(self, mock_webhook, mock_emit_event):
        """验证 detected_at 为 None 时使用当前时间"""
        mock_db = MagicMock()
        metric_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        publish_anomaly_event(
            db=mock_db,
            metric_id=metric_id,
            metric_name="DAU",
            algorithm="quantile",
            anomaly_count=1,
            max_score=2.1,
            window_start="2024-01-01",
            window_end="2024-01-31",
            tenant_id=tenant_id,
            detected_at=None,
        )

        mock_emit_event.assert_called_once()
        call_kwargs = mock_emit_event.call_args[1]
        assert "detected_at" in call_kwargs["payload"]
        # ISO 格式字符串
        assert "T" in call_kwargs["payload"]["detected_at"]


class TestWebhookPost:
    """Webhook POST 隔离测试"""

    @patch("urllib.request.urlopen")
    @patch("services.metrics_agent.events.get_settings")
    def test_posts_to_configured_url(self, mock_get_settings, mock_urlopen):
        """验证 POST 到配置的 Webhook URL"""
        mock_settings = MagicMock()
        mock_settings.ALERT_WEBHOOK_ENABLED = True
        mock_settings.ALERT_WEBHOOK_URL = "https://example.com/webhook"
        mock_get_settings.return_value = mock_settings

        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        from services.metrics_agent.events import _post_to_webhook
        _post_to_webhook("metric.published", {"metric_id": "123"})

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://example.com/webhook"

    @patch("urllib.request.urlopen")
    @patch("services.metrics_agent.events.get_settings")
    def test_does_not_post_when_disabled(self, mock_get_settings, mock_urlopen):
        """验证 ALERT_WEBHOOK_ENABLED=False 时不发送"""
        mock_settings = MagicMock()
        mock_settings.ALERT_WEBHOOK_ENABLED = False
        mock_settings.ALERT_WEBHOOK_URL = "https://example.com/webhook"
        mock_get_settings.return_value = mock_settings

        from services.metrics_agent.events import _post_to_webhook
        _post_to_webhook("metric.published", {"metric_id": "123"})

        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch("services.metrics_agent.events.get_settings")
    def test_http_error_does_not_raise(self, mock_get_settings, mock_urlopen):
        """验证 HTTP 错误不阻断主流程"""
        import urllib.error

        mock_settings = MagicMock()
        mock_settings.ALERT_WEBHOOK_ENABLED = True
        mock_settings.ALERT_WEBHOOK_URL = "https://example.com/webhook"
        mock_get_settings.return_value = mock_settings

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://example.com/webhook",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )

        from services.metrics_agent.events import _post_to_webhook

        # 不应抛出异常
        _post_to_webhook("metric.published", {"metric_id": "123"})
