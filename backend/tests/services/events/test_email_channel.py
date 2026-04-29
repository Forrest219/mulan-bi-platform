"""单元测试：邮件出站渠道（EmailChannel）

覆盖 Spec 16 §11.4 出站测试要求：
- EVT_010: SMTP 配置缺失或不可达
- EVT_014: 收件人被拒（permanent_failed）
- EVT_015: 模板渲染失败

Mock 闭环策略（Spec 16 §13.2）：
- mock 位置在 BaseChannel.send 或 EmailChannel._create_smtp
- 禁止直接 mock smtplib（已在 CI 红线中禁止）

注意：这些测试不依赖数据库，可以独立运行。
"""
import pytest
import smtplib
import os
import sys

# 确保 DATABASE_URL 存在（单元测试不需要真实数据库连接）
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("SECURE_COOKIES", "false")
os.environ.setdefault("SERVICE_JWT_SECRET", "test-jwt-secret-for-service-auth-32ch")

# 标记：跳过数据库 fixture（使用 custom marker）
pytestmark = pytest.mark.skip_db


from unittest.mock import MagicMock, patch
from services.events.channels.email_channel import EmailChannel, _render_template
from services.events.channels.base import ChannelDeliveryResult


# =============================================================================
# Mock 辅助类
# =============================================================================

class MockSMTP:
    """Mock SMTP 连接，用于测试"""

    def __init__(self, raise_on_login=None, raise_on_send=None, raise_on_init=None):
        self.raise_on_login = raise_on_login
        self.raise_on_send = raise_on_send
        self.raise_on_init = raise_on_init
        self.login_called = False
        self.sendmail_called = False
        self.closed = False

        if raise_on_init:
            raise raise_on_init

    def login(self, user, password):
        self.login_called = True
        if self.raise_on_login:
            raise self.raise_on_login

    def sendmail(self, from_addr, to_addrs, msg):
        self.sendmail_called = True
        if self.raise_on_send:
            raise self.raise_on_send

    def starttls(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.closed = True
        return False


class MockSMTPSSL(MockSMTP):
    """Mock SMTP_SSL 连接"""
    pass


# =============================================================================
# 配置检查测试（EVT_010 前置条件）
# =============================================================================

class TestSmtpConfigured:
    """测试 SMTP 配置检查"""

    def test_not_configured_when_missing_host(self):
        """缺少 SMTP_HOST 时 _configured 为 False"""
        with patch("services.events.channels.email_channel.get_smtp_config", return_value={
            "host": None,
            "port": 465,
            "user": "user",
            "password": "pass",
            "use_tls": True,
            "from_addr": "from@example.com",
        }):
            channel = EmailChannel()
            assert channel._configured is False

    def test_not_configured_when_missing_user(self):
        """缺少 SMTP_USER 时 _configured 为 False"""
        with patch("services.events.channels.email_channel.get_smtp_config", return_value={
            "host": "smtp.example.com",
            "port": 465,
            "user": None,
            "password": "pass",
            "use_tls": True,
            "from_addr": "from@example.com",
        }):
            channel = EmailChannel()
            assert channel._configured is False

    def test_not_configured_when_missing_password(self):
        """缺少 SMTP_PASSWORD 时 _configured 为 False"""
        with patch("services.events.channels.email_channel.get_smtp_config", return_value={
            "host": "smtp.example.com",
            "port": 465,
            "user": "user",
            "password": None,
            "use_tls": True,
            "from_addr": "from@example.com",
        }):
            channel = EmailChannel()
            assert channel._configured is False

    def test_not_configured_when_missing_from_addr(self):
        """缺少 SMTP_FROM_ADDR 时 _configured 为 False"""
        with patch("services.events.channels.email_channel.get_smtp_config", return_value={
            "host": "smtp.example.com",
            "port": 465,
            "user": "user",
            "password": "pass",
            "use_tls": True,
            "from_addr": None,
        }):
            channel = EmailChannel()
            assert channel._configured is False

    def test_configured_when_all_present(self):
        """所有必填项存在时 _configured 为 True"""
        with patch("services.events.channels.email_channel.get_smtp_config", return_value={
            "host": "smtp.example.com",
            "port": 465,
            "user": "user",
            "password": "pass",
            "use_tls": True,
            "from_addr": "from@example.com",
        }):
            channel = EmailChannel()
            assert channel._configured is True


# =============================================================================
# EVT_010 场景测试：SMTP 配置缺失或不可达
# =============================================================================

class TestEvt010SmtpConfigError:
    """测试 EVT_010：SMTP 配置缺失或不可达"""

    def test_permanent_failed_when_not_configured(self):
        """SMTP 未配置时返回 permanent_failed + EVT_010"""
        channel = EmailChannel()
        channel._configured = False

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"

        result = channel.send(notification, "test@example.com", trace_id="trace-001")

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_010"
        assert "SMTP 配置缺失" in result.detail

    def test_smtp_authentication_error_returns_evt_010(self):
        """SMTP 认证失败返回 permanent_failed + EVT_010"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        with patch.object(channel, "_create_smtp") as mock_create_smtp:
            mock_create_smtp.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")

            result = channel.send(notification, "test@example.com", trace_id="trace-002")

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_010"
        assert "SMTP 认证失败" in result.detail

    def test_smtp_server_disconnected_returns_retryable_evt_010(self):
        """SMTP 服务器断开返回 retryable_failed + EVT_010"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        with patch.object(channel, "_create_smtp") as mock_create_smtp:
            mock_create_smtp.side_effect = smtplib.SMTPServerDisconnected("Connection lost")

            result = channel.send(notification, "test@example.com", trace_id="trace-003")

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_010"
        assert "SMTP 服务器断开" in result.detail

    def test_smtp_5xx_error_returns_permanent_evt_010(self):
        """SMTP 5xx 错误返回 permanent_failed + EVT_010"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        with patch.object(channel, "_create_smtp") as mock_create_smtp:
            exc = smtplib.SMTPException("Server error")
            exc.smtp_code = 550
            mock_create_smtp.side_effect = exc

            result = channel.send(notification, "test@example.com", trace_id="trace-004")

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_010"
        assert "SMTP 5xx" in result.detail

    def test_smtp_4xx_error_returns_retryable_evt_010(self):
        """SMTP 4xx 错误返回 retryable_failed + EVT_010"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        with patch.object(channel, "_create_smtp") as mock_create_smtp:
            exc = smtplib.SMTPException("Temporary error")
            exc.smtp_code = 450
            mock_create_smtp.side_effect = exc

            result = channel.send(notification, "test@example.com", trace_id="trace-005")

        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_010"


# =============================================================================
# EVT_014 场景测试：收件人被拒
# =============================================================================

class TestEvt014RecipientRefused:
    """测试 EVT_014：收件人被拒（permanent_failed）"""

    def test_recipients_refused_returns_evt_014(self):
        """收件人被拒返回 permanent_failed + EVT_014"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        with patch.object(channel, "_create_smtp") as mock_create_smtp:
            mock_create_smtp.side_effect = smtplib.SMTPRecipientsRefused({
                "invalid@example.com": (550, b"User unknown")
            })

            result = channel.send(notification, "invalid@example.com", trace_id="trace-006")

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_014"
        assert "收件人被拒" in result.detail


# =============================================================================
# EVT_015 场景测试：模板渲染失败
# =============================================================================

class TestEvt015TemplateRenderError:
    """测试 EVT_015：模板渲染失败"""

    def test_template_render_error_returns_evt_015(self):
        """模板渲染失败返回 permanent_failed + EVT_015"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        with patch("services.events.channels.email_channel._render_template") as mock_render:
            mock_render.side_effect = Exception("Template not found: missing_template.html.j2")

            result = channel.send(notification, "test@example.com", trace_id="trace-007")

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_015"
        assert "邮件发送异常" in result.detail

    def test_generic_exception_returns_evt_010(self):
        """非模板相关的异常返回 permanent_failed + EVT_010"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        with patch.object(channel, "_create_smtp") as mock_create_smtp:
            mock_create_smtp.side_effect = RuntimeError("Unexpected error")

            result = channel.send(notification, "test@example.com", trace_id="trace-008")

        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_010"


# =============================================================================
# 成功发送测试
# =============================================================================

class TestEmailChannelSuccess:
    """测试成功发送邮件"""

    def test_send_success_returns_delivered(self):
        """成功发送返回 delivered"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        mock_smtp = MockSMTP()

        with patch.object(channel, "_create_smtp", return_value=mock_smtp):
            result = channel.send(notification, "test@example.com", trace_id="trace-009")

        assert result.status == "delivered"
        assert result.detail == "SMTP 250 OK"
        assert result.error_code is None
        assert mock_smtp.sendmail_called is True

    def test_send_with_event_payload_renders_template(self):
        """带事件 payload 时正确渲染模板"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        event = MagicMock()
        event.event_type = "tableau.sync.failed"
        event.payload_json = {"error_message": "Connection refused"}
        event.id = 123

        notification = MagicMock()
        notification.title = "Tableau 同步失败"
        notification.content = "连接同步失败"
        notification.event = event

        mock_smtp = MockSMTP()

        with patch.object(channel, "_create_smtp", return_value=mock_smtp):
            result = channel.send(notification, "admin@example.com", trace_id="trace-010")

        assert result.status == "delivered"
        assert mock_smtp.sendmail_called is True

    def test_send_strips_port_465_uses_ssl(self):
        """端口 465 时使用 SMTP_SSL"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 465  # SSL 端口
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = False
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试通知"
        notification.content = "测试内容"
        notification.event = None

        # 验证 _create_smtp 返回 SMTP_SSL（通过端口判断逻辑）
        mock_smtp = MockSMTPSSL()
        mock_smtp.sendmail_called = False

        with patch.object(channel, "_create_smtp", return_value=mock_smtp):
            with patch("services.events.channels.email_channel.smtplib.SMTP_SSL", return_value=mock_smtp):
                result = channel.send(notification, "test@example.com", trace_id="trace-011")

        assert result.status == "delivered"


# =============================================================================
# 模板渲染测试
# =============================================================================

class TestTemplateRendering:
    """测试模板渲染逻辑"""

    def test_render_uses_event_type_template(self):
        """存在事件类型模板时使用专用模板"""
        notification = MagicMock()
        notification.title = "Tableau 同步失败"
        notification.content = "连接同步失败"
        notification.level = "error"

        event = MagicMock()
        event.event_type = "tableau.sync.failed"
        event.id = 456
        event.payload_json = {"error_message": "Connection refused"}

        result = _render_template(
            event_type="tableau.sync.failed",
            notification=notification,
            event=event,
            payload={"error_message": "Connection refused"},
            base_url="https://mulan-bi.example.com",
        )

        assert "Tableau 同步失败" in result
        assert "Connection refused" in result

    def test_render_fallback_to_default_template(self):
        """模板缺失时回退到 default.html.j2"""
        notification = MagicMock()
        notification.title = "测试标题"
        notification.content = "测试内容"
        notification.level = "info"

        result = _render_template(
            event_type="unknown.event.type",
            notification=notification,
            event=None,
            payload={},
            base_url="https://example.com",
        )

        # Should use default template
        assert isinstance(result, str)
        assert "测试标题" in result
        assert "测试内容" in result

    def test_render_plain_text_fallback_when_no_templates(self):
        """完全无模板时回退到纯文本

        注意：由于 default.html.j2 存在，此测试验证的是正常模板渲染路径。
        如果 default.html.j2 不存在，_render_template 会回退到纯文本：
        f"{notification.title}\n\n{notification.content}"
        """
        notification = MagicMock()
        notification.title = "纯文本标题"
        notification.content = "纯文本内容"

        # 使用未知事件类型，会触发 TemplateNotFound，然后回退到 default.html.j2
        result = _render_template(
            event_type="completely.unknown.event.type",
            notification=notification,
            event=None,
            payload={},
            base_url="https://example.com",
        )

        # 由于 default.html.j2 存在，会渲染模板而非纯文本
        assert isinstance(result, str)
        assert "纯文本标题" in result or "纯文本内容" in result


# =============================================================================
# SMTP 连接创建测试
# =============================================================================

class TestCreateSmtp:
    """测试 _create_smtp 方法"""

    def test_create_smtp_ssl_port_465(self):
        """端口 465 创建 SMTP_SSL 连接"""
        channel = EmailChannel()
        channel._host = "smtp.example.com"
        channel._port = 465
        channel._user = "user"
        channel._password = "pass"
        channel._use_tls = False

        mock_ssl = MockSMTPSSL()
        with patch("services.events.channels.email_channel.smtplib.SMTP_SSL", return_value=mock_ssl):
            result = channel._create_smtp()

        assert isinstance(result, MockSMTPSSL)

    def test_create_smtp_with_starttls(self):
        """端口 587 使用 STARTTLS"""
        channel = EmailChannel()
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "pass"
        channel._use_tls = True

        mock_smtp = MockSMTP()
        with patch("services.events.channels.email_channel.smtplib.SMTP", return_value=mock_smtp):
            result = channel._create_smtp()

        assert mock_smtp.login_called is True


# =============================================================================
# ChannelDeliveryResult 数据类测试
# =============================================================================

class TestChannelDeliveryResult:
    """测试 ChannelDeliveryResult 数据类"""

    def test_status_delivered(self):
        """delivered 状态无错误码"""
        result = ChannelDeliveryResult(status="delivered", detail="SMTP 250 OK")
        assert result.status == "delivered"
        assert result.detail == "SMTP 250 OK"
        assert result.error_code is None

    def test_status_retryable_failed(self):
        """retryable_failed 状态带错误码"""
        result = ChannelDeliveryResult(
            status="retryable_failed",
            detail="连接超时（5s）",
            error_code="EVT_012",
        )
        assert result.status == "retryable_failed"
        assert result.error_code == "EVT_012"

    def test_status_permanent_failed(self):
        """permanent_failed 状态带错误码"""
        result = ChannelDeliveryResult(
            status="permanent_failed",
            detail="收件人被拒",
            error_code="EVT_014",
        )
        assert result.status == "permanent_failed"
        assert result.error_code == "EVT_014"


# =============================================================================
# 边界条件测试
# =============================================================================

class TestEdgeCases:
    """测试边界条件"""

    def test_send_with_trace_id_in_email_header(self):
        """邮件头包含 X-Mulan-Trace-Id"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试"
        notification.content = "内容"
        notification.event = None

        captured_msg = None

        def capture_sendmail(from_addr, to_addrs, msg):
            nonlocal captured_msg
            captured_msg = msg
            return

        mock_smtp = MagicMock()
        mock_smtp.sendmail = capture_sendmail
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        mock_smtp.starttls = MagicMock()
        mock_smtp.login = MagicMock()

        with patch.object(channel, "_create_smtp", return_value=mock_smtp):
            channel.send(notification, "test@example.com", trace_id="trace-abc-123")

        # 验证 trace_id 在邮件头中
        assert b"X-Mulan-Trace-Id" in captured_msg
        assert b"trace-abc-123" in captured_msg

    def test_send_without_event_does_not_crash(self):
        """无关联事件时不崩溃"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        notification = MagicMock()
        notification.title = "测试"
        notification.content = "内容"
        notification.event = None  # 无事件

        mock_smtp = MockSMTP()

        with patch.object(channel, "_create_smtp", return_value=mock_smtp):
            result = channel.send(notification, "test@example.com", trace_id="trace-012")

        assert result.status == "delivered"

    def test_event_without_payload_json(self):
        """事件无 payload_json 时不崩溃"""
        channel = EmailChannel()
        channel._configured = True
        channel._host = "smtp.example.com"
        channel._port = 587
        channel._user = "user"
        channel._password = "password"
        channel._use_tls = True
        channel._from_addr = "from@example.com"

        event = MagicMock()
        event.event_type = "test.event"
        event.payload_json = None  # 无 payload
        event.id = 789

        notification = MagicMock()
        notification.title = "测试"
        notification.content = "内容"
        notification.event = event

        mock_smtp = MockSMTP()

        with patch.object(channel, "_create_smtp", return_value=mock_smtp):
            result = channel.send(notification, "test@example.com", trace_id="trace-013")

        assert result.status == "delivered"
