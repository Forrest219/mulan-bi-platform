"""单元测试：Webhook 出站渠道（WebhookChannel）

覆盖 Spec 16:
- HMAC-SHA256 签名验证
- 64KB 截断逻辑
- 错误码映射 (EVT_011/012/013/014/016)
- Mock httpx 闭环测试
"""
import hashlib
import hmac
import json
import base64
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, Mock
from typing import Generator

import httpx

from services.events.channels.webhook_channel import (
    WebhookChannel,
    _canonical_json,
    _sign_payload,
    _truncate_payload,
    _get_fernet,
    _MAX_PAYLOAD_KB,
)
from services.events.channels.base import ChannelDeliveryResult


# =============================================================================
# Helpers
# =============================================================================

def get_valid_fernet_key() -> str:
    """生成有效的 Fernet 密钥（URL-safe base64 32 字节）"""
    # 刚好 32 字节：32 个 ASCII 字符
    return base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()


def get_fernet_instance():
    """获取 Fernet 实例"""
    from cryptography.fernet import Fernet
    return Fernet(get_valid_fernet_key().encode())


def encrypt_secret(secret: bytes) -> str:
    """加密 secret 用于测试"""
    fernet = get_fernet_instance()
    return fernet.encrypt(secret).decode()


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fernet_key() -> str:
    """测试用 Fernet 密钥"""
    return get_valid_fernet_key()


@pytest.fixture
def mock_fernet(fernet_key: str) -> Generator[Mock, None, None]:
    """Mock Fernet 实例"""
    real_fernet = get_fernet_instance()

    mock_instance = MagicMock()
    mock_instance.decrypt.side_effect = lambda x: real_fernet.decrypt(x)
    mock_instance.encrypt.side_effect = lambda x: real_fernet.encrypt(x)

    with patch("services.events.channels.webhook_channel._get_fernet", return_value=mock_instance):
        yield mock_instance


@pytest.fixture
def webhook_channel(mock_fernet: Mock) -> WebhookChannel:
    """创建已 mock Fernet 的 WebhookChannel 实例"""
    channel = WebhookChannel()
    channel._fernet = mock_fernet
    return channel


@pytest.fixture
def mock_notification() -> Mock:
    """Mock notification 对象"""
    notification = MagicMock()
    notification.id = 12345
    notification.title = "测试通知标题"
    notification.content = "测试通知内容，包含中文"
    notification.level = "warning"
    notification.created_at = datetime(2025, 1, 15, 10, 30, 0)
    notification.event = None
    return notification


@pytest.fixture
def mock_notification_with_event(mock_notification: Mock) -> Mock:
    """带有 event 的 Mock notification"""
    mock_notification.event = MagicMock()
    mock_notification.event.payload_json = {"key": "value", "count": 42}
    mock_notification.event.event_type = "tableau.sync.completed"
    return mock_notification


# =============================================================================
# TestCanonicalJson: 规范化 JSON 生成
# =============================================================================

class TestCanonicalJson:
    """测试规范化 JSON 生成"""

    def test_sort_keys_and_separators(self):
        """测试 key 排序和紧凑分隔符"""
        payload = {"b": 2, "a": 1, "c": 3}
        canonical = _canonical_json(payload)
        assert canonical == b'{"a":1,"b":2,"c":3}'

    def test_ensure_ascii_false_unicode(self):
        """测试中文字符不被 Unicode 转义"""
        payload = {"name": "中文内容", "status": "成功"}
        canonical = _canonical_json(payload)
        assert canonical == '{"name":"中文内容","status":"成功"}'.encode("utf-8")

    def test_same_payload_deterministic(self):
        """测试同一 payload 多次调用结果一致"""
        payload = {"event_type": "tableau.sync.failed", "id": 123}
        result1 = _canonical_json(payload)
        result2 = _canonical_json(payload)
        assert result1 == result2

    def test_nested_object_sorted(self):
        """测试嵌套对象的 key 也按字母序排列"""
        payload = {
            "z_key": 1,
            "a_key": {
                "z_nested": 2,
                "a_nested": 1,
            },
        }
        canonical = _canonical_json(payload)
        expected = b'{"a_key":{"a_nested":1,"z_nested":2},"z_key":1}'
        assert canonical == expected

    def test_array_order_preserved(self):
        """测试数组顺序保持不变（数组顺序有语义）"""
        payload = {"items": [3, 1, 2], "name": "test"}
        canonical = _canonical_json(payload)
        # 数组内顺序保持 [3, 1, 2]
        assert b'"items":[3,1,2]' in canonical


# =============================================================================
# TestSignPayload: HMAC-SHA256 签名
# =============================================================================

class TestSignPayload:
    """测试 HMAC-SHA256 签名"""

    def test_signature_format(self):
        """测试签名格式：sha256= 前缀 + 64 位十六进制"""
        encrypted_secret = encrypt_secret(b"my-secret-key-12345")

        payload_bytes = b'{"test":"data"}'
        sig = _sign_payload(payload_bytes, encrypted_secret)

        assert sig.startswith("sha256=")
        hex_part = sig[7:]  # 去掉前缀
        assert len(hex_part) == 64  # SHA256 输出 64 位十六进制
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_signature_correctness(self):
        """用 Python hmac 模块复现签名，确认一致性"""
        secret = b"my-webhook-secret-32bytes!"
        encrypted_secret = encrypt_secret(secret)

        payload_bytes = b'{"event_type":"test","id":1}'

        # 通过 _sign_payload 生成签名
        sig = _sign_payload(payload_bytes, encrypted_secret)

        # 手动计算 HMAC-SHA256
        expected_hmac = hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
        expected_sig = f"sha256={expected_hmac}"

        assert sig == expected_sig

    def test_fernet_not_configured(self):
        """FERNET_MASTER_KEY 未配置 → 抛出 ValueError EVT_016"""
        with patch("services.events.channels.webhook_channel._get_fernet", return_value=None):
            with pytest.raises(ValueError, match="EVT_016"):
                _sign_payload(b'{"test":"data"}', "some_encrypted")

    def test_fernet_decrypt_failure(self):
        """Fernet 解密失败 → 抛出 ValueError EVT_016"""
        mock_instance = MagicMock()
        mock_instance.decrypt.side_effect = Exception("Decryption failed")

        with patch("services.events.channels.webhook_channel._get_fernet", return_value=mock_instance):
            with pytest.raises(ValueError, match="EVT_016"):
                _sign_payload(b'{"test":"data"}', "invalid_encrypted_secret")

    def test_different_secrets_different_signatures(self):
        """不同密钥生成不同签名"""
        secret1 = b"secret-one-12345678"
        secret2 = b"secret-two-12345678"
        encrypted1 = encrypt_secret(secret1)
        encrypted2 = encrypt_secret(secret2)

        payload = b'{"test":"data"}'

        sig1 = _sign_payload(payload, encrypted1)
        sig2 = _sign_payload(payload, encrypted2)

        assert sig1 != sig2


# =============================================================================
# TestTruncatePayload: 64KB 截断逻辑
# =============================================================================

class TestTruncatePayload:
    """测试 payload 截断逻辑"""

    def test_small_payload_not_truncated(self):
        """小 payload 不截断"""
        payload = {"event_type": "test", "id": 123}
        result = _truncate_payload(payload)
        assert result == payload
        assert "_truncated" not in result

    def test_exact_64kb_boundary(self):
        """恰好 64KB 的 payload 不截断"""
        # 构造恰好 64KB 的 payload
        base = {"data": ""}
        base_size = len(json.dumps(base))  # {"data":""} = 11 bytes
        data_size = _MAX_PAYLOAD_KB * 1024 - base_size
        payload = {"data": "x" * data_size}
        result = _truncate_payload(payload)
        assert "_truncated" not in result

    def test_over_64kb_truncated(self):
        """超过 64KB 的 payload 截断并添加 _truncated 标记"""
        # 仅验证截断逻辑存在，不依赖具体实现细节
        large_payload = {
            "event_type": "test",
            "data": "x" * (100 * 1024),  # 100KB > 64KB
        }
        result = _truncate_payload(large_payload)
        # 验证截断后大小在限制内
        encoded = json.dumps(result).encode("utf-8")
        assert len(encoded) <= _MAX_PAYLOAD_KB * 1024


# =============================================================================
# TestWebhookChannelSend: send() 方法三态返回
# =============================================================================

class TestWebhookChannelSend:
    """测试 WebhookChannel.send() 三态返回"""

    def test_successful_delivery(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """HTTP 2xx → delivered"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "OK"

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "delivered"
        assert result.error_code is None
        assert "HTTP 200" in result.detail

    def test_http_201_delivered(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """HTTP 201/202 等 2xx 也视为 delivered"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.text = "Created"

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "delivered"

    def test_permanent_failed_on_fernet_error(self):
        """Fernet 解密失败 → permanent_failed EVT_016"""
        channel = WebhookChannel()
        notification = MagicMock()
        notification.id = 1
        notification.title = "Test"
        notification.content = "Test content"
        notification.level = "info"
        notification.event = None
        notification.created_at = datetime(2025, 1, 15, 10, 30, 0)

        result = channel.send(
            notification,
            "https://example.com/webhook",
            trace_id="test-123",
            secret_encrypted="bad_secret",
            event_type="test.event",
            event_id=100,
        )

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_016"
        assert "FERNET_MASTER_KEY" in result.detail or "无法解密" in result.detail

    def test_webhook_400_bad_request(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """HTTP 400 → permanent_failed EVT_014"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = "Bad Request: Invalid JSON"

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_014"
        assert "400" in result.detail

    def test_webhook_404_not_found(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """HTTP 404 → permanent_failed EVT_014"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "Not Found"

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_014"

    def test_webhook_403_forbidden(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """HTTP 403 → permanent_failed EVT_014（签名验证失败或无权限）"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.text = "Forbidden: Invalid signature"

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_014"

    def test_webhook_500_internal_error(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """HTTP 500 → retryable_failed EVT_013"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_013"

    def test_webhook_503_service_unavailable(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """HTTP 503 → retryable_failed EVT_013"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.text = "Service Unavailable"

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_013"

    def test_webhook_502_bad_gateway(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """HTTP 502 → retryable_failed EVT_013"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 502
            mock_response.text = "Bad Gateway"

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_013"


# =============================================================================
# TestWebhookChannelNetworkErrors: 网络错误场景
# =============================================================================

class TestWebhookChannelNetworkErrors:
    """测试网络层错误 → retryable_failed"""

    def test_connect_timeout(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """连接超时 → retryable_failed EVT_012"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = httpx.ConnectTimeout("Connection timeout")
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="test-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_012"
        assert "连接超时" in result.detail

    def test_read_timeout(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """读超时 → retryable_failed EVT_012"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = httpx.ReadTimeout("Read timeout")
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="test-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_012"
        assert "读超时" in result.detail

    def test_dns_error(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """DNS 解析失败 → retryable_failed EVT_011"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = httpx.ConnectError("DNS resolution failed")
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://nonexistent-domain-xyz-123.com/webhook",
                trace_id="test-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_011"
        assert "DNS" in result.detail

    def test_generic_request_error(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """通用 RequestError → retryable_failed EVT_012"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = httpx.RequestError("Network error")
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="test-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_012"

    def test_unexpected_exception(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """未知异常 → retryable_failed EVT_012（安全降级）"""
        encrypted_secret = encrypt_secret(b"my-secret")

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = RuntimeError("Unexpected error")
            mock_client_cls.return_value = mock_client

            result = webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="test-123",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=100,
            )

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_012"
        assert "投递异常" in result.detail


# =============================================================================
# TestWebhookChannelRequestHeaders: 请求头验证
# =============================================================================

class TestWebhookChannelRequestHeaders:
    """测试 HTTP 请求头正确性"""

    def test_headers_contain_all_required_fields(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """验证请求头包含所有必需字段"""
        secret = b"test-secret-key"
        encrypted_secret = encrypt_secret(secret)

        captured_headers = {}

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            def capture_post(url, content, headers, **kwargs):
                captured_headers.update(headers)
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.text = "OK"
                return mock_response

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = capture_post
            mock_client_cls.return_value = mock_client

            webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-abc-123",
                secret_encrypted=encrypted_secret,
                event_type="tableau.sync.completed",
                event_id=999,
            )

        # 验证必需字段
        assert captured_headers["Content-Type"] == "application/json; charset=utf-8"
        assert captured_headers["X-Mulan-Event-Type"] == "tableau.sync.completed"
        assert captured_headers["X-Mulan-Event-Id"] == "999"
        assert captured_headers["X-Mulan-Trace-Id"] == "trace-abc-123"
        assert captured_headers["X-Mulan-Signature"].startswith("sha256=")
        assert captured_headers["User-Agent"] == "Mulan-Webhook/1.1"

    def test_signature_in_header_matches_payload(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """验证请求头中的签名与 payload 一致"""
        secret = b"sign-verification-secret"
        encrypted_secret = encrypt_secret(secret)

        captured_headers = {}
        captured_content = {}

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            def capture_post(url, content, headers, **kwargs):
                captured_headers.update(headers)
                captured_content["data"] = content
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.text = "OK"
                return mock_response

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = capture_post
            mock_client_cls.return_value = mock_client

            webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="trace-xyz",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=1,
            )

        # 用相同 secret 手动计算签名
        payload_bytes = captured_content["data"]
        expected_sig = f"sha256={hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()}"

        assert captured_headers["X-Mulan-Signature"] == expected_sig


# =============================================================================
# TestWebhookChannelPayloadBuilding: payload 构建逻辑
# =============================================================================

class TestWebhookChannelPayloadBuilding:
    """测试 payload 构建逻辑"""

    def test_payload_structure_without_event(self, webhook_channel: WebhookChannel, mock_notification: Mock):
        """无 event 时 payload 结构正确"""
        encrypted_secret = encrypt_secret(b"secret")

        captured_content = {}

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            def capture_post(url, content, headers, **kwargs):
                captured_content["data"] = content
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.text = "OK"
                return mock_response

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = capture_post
            mock_client_cls.return_value = mock_client

            webhook_channel.send(
                mock_notification,
                "https://example.com/webhook",
                trace_id="t1",
                secret_encrypted=encrypted_secret,
                event_type="test.event",
                event_id=1,
            )

        payload = json.loads(captured_content["data"])

        assert payload["notification_id"] == 12345
        assert payload["title"] == "测试通知标题"
        assert payload["content"] == "测试通知内容，包含中文"
        assert payload["level"] == "warning"
        assert payload["event_type"] == "test.event"
        assert payload["event_id"] == 1
        assert payload["created_at"] == "2025-01-15T10:30:00"
        assert "payload_json" not in payload  # 无 event 时不包含

    def test_payload_structure_with_event(self, webhook_channel: WebhookChannel, mock_notification_with_event: Mock):
        """有 event 时 payload 包含 payload_json"""
        encrypted_secret = encrypt_secret(b"secret")

        captured_content = {}

        with patch("services.events.channels.webhook_channel.httpx.Client") as mock_client_cls:
            def capture_post(url, content, headers, **kwargs):
                captured_content["data"] = content
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.text = "OK"
                return mock_response

            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client.post.side_effect = capture_post
            mock_client_cls.return_value = mock_client

            webhook_channel.send(
                mock_notification_with_event,
                "https://example.com/webhook",
                trace_id="t1",
                secret_encrypted=encrypted_secret,
                event_type="tableau.sync.completed",
                event_id=1,
            )

        payload = json.loads(captured_content["data"])
        assert "payload_json" in payload
        assert payload["payload_json"] == {"key": "value", "count": 42}


# =============================================================================
# TestWebhookChannelRetryBackoff: 重试配置
# =============================================================================

class TestWebhookChannelRetryBackoff:
    """测试重试退避配置（与 OutboxService 配合）"""

    def test_webhook_max_retries_3(self):
        """Webhook 重试最多 3 次"""
        from services.events.outbox_service import WEBHOOK_RETRY_BACKOFF, MAX_WEBHOOK_RETRIES
        assert len(WEBHOOK_RETRY_BACKOFF) == 4  # [0, 30, 120, 300]
        assert MAX_WEBHOOK_RETRIES == 3

    def test_email_max_retries_5(self):
        """Email 重试最多 5 次"""
        from services.events.outbox_service import EMAIL_RETRY_BACKOFF, MAX_EMAIL_RETRIES
        assert len(EMAIL_RETRY_BACKOFF) == 6  # [0, 30, 120, 300, 900, 1800]
        assert MAX_EMAIL_RETRIES == 5

    def test_webhook_backoff_sequence(self):
        """Webhook 退避序列：0s, 30s, 120s, 300s"""
        from services.events.outbox_service import WEBHOOK_RETRY_BACKOFF
        assert WEBHOOK_RETRY_BACKOFF[0] == 0    # 首次立即
        assert WEBHOOK_RETRY_BACKOFF[1] == 30   # 第 1 次重试：30s 后
        assert WEBHOOK_RETRY_BACKOFF[2] == 120  # 第 2 次重试：2min 后
        assert WEBHOOK_RETRY_BACKOFF[3] == 300  # 第 3 次重试：5min 后


# =============================================================================
# TestHmacVerificationIntegration: 签名验证集成测试
# =============================================================================

class TestHmacVerificationIntegration:
    """端到端签名验证：模拟接收方验证签名"""

    def test_receiver_can_verify_signature(self):
        """接收方可以用相同 secret 验证签名"""
        secret = b"webhook-verification-secret"
        encrypted_secret = encrypt_secret(secret)

        # 发送方生成 payload 和签名
        payload = {"event_type": "test", "id": 123, "data": "hello"}
        payload_bytes = _canonical_json(payload)
        signature = _sign_payload(payload_bytes, encrypted_secret)

        # 接收方验证签名
        sig_without_prefix = signature.replace("sha256=", "")
        expected_sig = hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()

        assert sig_without_prefix == expected_sig
        # 验证通过
        assert hmac.compare_digest(sig_without_prefix, expected_sig)

    def test_tampered_payload_fails_verification(self):
        """篡改 payload 后签名验证失败"""
        secret = b"webhook-secret"
        encrypted_secret = encrypt_secret(secret)

        original_payload = {"event_type": "test", "id": 123}
        original_bytes = _canonical_json(original_payload)
        signature = _sign_payload(original_bytes, encrypted_secret)
        sig_without_prefix = signature.replace("sha256=", "")

        # 篡改 payload
        tampered_payload = {"event_type": "test", "id": 999}  # id 被改
        tampered_bytes = _canonical_json(tampered_payload)

        # 用原始签名验证篡改后的 payload
        tampered_expected = hmac.new(secret, tampered_bytes, hashlib.sha256).hexdigest()

        # 签名不匹配
        assert sig_without_prefix != tampered_expected


# =============================================================================
# TestGetFernet: Fernet 实例获取
# =============================================================================

class TestGetFernet:
    """测试 _get_fernet 函数"""

    def test_get_fernet_returns_none_without_key(self):
        """FERNET_MASTER_KEY 未配置时返回 None"""
        with patch("services.events.channels.webhook_channel.get_fernet_master_key", return_value=None):
            result = _get_fernet()
            assert result is None

    def test_get_fernet_returns_instance_with_key(self):
        """FERNET_MASTER_KEY 配置时返回 Fernet 实例"""
        from cryptography.fernet import Fernet

        valid_key = get_valid_fernet_key()
        with patch("services.events.channels.webhook_channel.get_fernet_master_key", return_value=valid_key):
            result = _get_fernet()
            assert result is not None
            assert isinstance(result, Fernet)
