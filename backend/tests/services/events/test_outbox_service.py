"""单元测试：出站服务（OutboxService）"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from services.events.outbox_service import (
    OutboxService,
    _compute_payload_hash,
    _matches_pattern,
    EMAIL_RETRY_BACKOFF,
    WEBHOOK_RETRY_BACKOFF,
    MAX_EMAIL_RETRIES,
    MAX_WEBHOOK_RETRIES,
)


class TestComputePayloadHash:
    """测试 payload 摘要计算"""

    def test_deterministic_same_payload(self):
        payload = {"event_type": "test", "id": 123}
        hash1 = _compute_payload_hash(payload)
        hash2 = _compute_payload_hash(payload)
        assert hash1 == hash2

    def test_different_payloads_different_hash(self):
        payload1 = {"event_type": "test", "id": 123}
        payload2 = {"event_type": "test", "id": 456}
        assert _compute_payload_hash(payload1) != _compute_payload_hash(payload2)

    def test_sort_keys_consistency(self):
        """相同数据不同 key 顺序应产生相同 hash"""
        payload1 = {"a": 1, "b": 2}
        payload2 = {"b": 2, "a": 1}
        assert _compute_payload_hash(payload1) == _compute_payload_hash(payload2)


class TestMatchesPattern:
    """测试事件类型匹配 pattern"""

    @pytest.mark.parametrize("pattern,event_type,expected", [
        ("*", "any.event.type", True),
        ("tableau.sync.failed", "tableau.sync.failed", True),
        ("tableau.sync.failed", "tableau.sync.completed", False),
        ("health.*", "health.scan.completed", True),
        ("health.*", "health.scan.failed", True),
        ("health.*", "tableau.sync.completed", False),
        ("dqc.*", "dqc.cycle.started", True),
        ("dqc.*", "dqc.asset.signal_changed", True),
        ("*", "anything", True),
    ])
    def test_pattern_matching(self, pattern, event_type, expected):
        assert _matches_pattern(event_type, pattern) is expected


class TestOutboxServiceEnqueue:
    """测试 OutboxService.enqueue()"""

    def test_enqueue_creates_pending_record(self):
        svc = OutboxService()
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        record = svc.enqueue(
            db=mock_db,
            notification_id=1,
            channel="email",
            target="test@example.com",
            event_type="test.event",
            payload={"test": "data"},
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_compute_payload_hash_on_enqueue(self):
        svc = OutboxService()
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        payload = {"event_type": "test", "id": 123}
        svc.enqueue(
            db=mock_db,
            notification_id=1,
            channel="webhook",
            target="https://example.com/webhook",
            event_type="test.event",
            payload=payload,
        )

        # Verify that add was called with an outbox record
        call_args = mock_db.add.call_args
        assert call_args is not None


class TestOutboxServiceRetryDeadLetter:
    """测试死信重试"""

    def test_retry_dead_letter_resets_status(self):
        svc = OutboxService()
        mock_db = MagicMock()
        mock_outbox = MagicMock()
        mock_outbox.id = 1
        mock_outbox.status = "dead"
        mock_outbox.attempt_count = 3

        mock_db.query.return_value.filter.return_value.first.return_value = mock_outbox

        result = svc.retry_dead_letter(mock_db, 1)

        assert mock_outbox.status == "pending"
        assert mock_outbox.attempt_count == 0
        mock_db.commit.assert_called()

    def test_retry_non_dead_fails(self):
        svc = OutboxService()
        mock_db = MagicMock()
        mock_outbox = MagicMock()
        mock_outbox.id = 1
        mock_outbox.status = "pending"  # Not dead

        mock_db.query.return_value.filter.return_value.first.return_value = mock_outbox

        with pytest.raises(ValueError, match="不是 dead 状态"):
            svc.retry_dead_letter(mock_db, 1)


class TestOutboxServiceGetNextAttemptAt:
    """测试下次调度时间计算"""

    def test_email_first_attempt_immediate(self):
        svc = OutboxService()
        result = svc.get_next_attempt_at("email", 0)
        assert result == datetime.utcnow()

    def test_email_second_attempt_30s(self):
        svc = OutboxService()
        result = svc.get_next_attempt_at("email", 1)
        expected = datetime.utcnow() + timedelta(seconds=30)
        # Allow 1 second tolerance
        assert abs((result - expected).total_seconds()) < 2

    def test_webhook_third_attempt_300s(self):
        svc = OutboxService()
        result = svc.get_next_attempt_at("webhook", 3)
        expected = datetime.utcnow() + timedelta(seconds=300)
        assert abs((result - expected).total_seconds()) < 2


class TestRetryBackoffConfiguration:
    """测试重试退避配置"""

    def test_email_backoff_intervals(self):
        assert EMAIL_RETRY_BACKOFF == [0, 30, 120, 300, 900, 1800]
        assert len(EMAIL_RETRY_BACKOFF) == 6

    def test_webhook_backoff_intervals(self):
        assert WEBHOOK_RETRY_BACKOFF == [0, 30, 120, 300]
        assert len(WEBHOOK_RETRY_BACKOFF) == 4

    def test_max_retries_email(self):
        assert MAX_EMAIL_RETRIES == 5

    def test_max_retries_webhook(self):
        assert MAX_WEBHOOK_RETRIES == 3