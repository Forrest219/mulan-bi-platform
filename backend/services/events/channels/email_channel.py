"""邮件出站渠道（EmailChannel）"""
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from .base import BaseChannel, ChannelDeliveryResult
from services.common.settings import get_smtp_config

logger = logging.getLogger(__name__)


def _render_template(event_type: str, notification, event, payload: dict, base_url: str) -> str:
    """渲染 Jinja2 邮件模板，优先找类型专用模板，回退到 default"""
    from jinja2 import Environment, FileSystemLoader, TemplateNotFound

    template_dir = os.path.join(os.path.dirname(__file__), "../email_templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)

    # 模板文件名映射（去掉 event_type 中的点，如 tableau.sync.failed -> tableau_sync_failed）
    safe_name = event_type.replace(".", "_")
    template_file = f"{safe_name}.html.j2"

    context = {
        "notification": notification,
        "event": event,
        "payload": payload,
        "event_type": event_type,
        "event_id": getattr(event, "id", None) if event else None,
        "base_url": base_url or "https://mulan-bi.example.com",
    }

    try:
        template = env.get_template(template_file)
        return template.render(**context)
    except TemplateNotFound:
        # 回退到 default
        try:
            template = env.get_template("default.html.j2")
            return template.render(**context)
        except TemplateNotFound:
            # 完全无法渲染，使用纯文本兜底
            return f"{notification.title}\n\n{notification.content}"


class EmailChannel(BaseChannel):
    """邮件出站渠道（继承 BaseChannel）"""

    def __init__(self):
        cfg = get_smtp_config()
        self._host = cfg["host"]
        self._port = cfg["port"]
        self._user = cfg["user"]
        self._password = cfg["password"]
        self._use_tls = cfg["use_tls"]
        self._from_addr = cfg["from_addr"]
        self._configured = bool(self._host and self._user and self._password and self._from_addr)
        if not self._configured:
            logger.warning("EmailChannel 未配置 SMTP，邮件投递将被永久拒绝")

    def send(
        self,
        notification,
        recipient: str,
        *,
        trace_id: str,
    ) -> ChannelDeliveryResult:
        """
        发送邮件。

        Returns:
            delivered: SMTP 250 OK
            retryable_failed: SMTP 4xx / 连接超时 / DNS 故障
            permanent_failed: SMTP 5xx / 地址不存在 / 模板渲染异常
        """
        if not self._configured:
            return ChannelDeliveryResult(
                status="permanent_failed",
                detail="SMTP 配置缺失（EVT_010）",
                error_code="EVT_010",
            )

        # 获取通知关联的事件信息
        event = getattr(notification, "event", None)
        event_type = getattr(event, "event_type", "unknown") if event else "unknown"
        payload = (event.payload_json or {}) if event else {}

        try:
            # 构建邮件
            msg = MIMEMultipart("alternative")
            msg["Subject"] = notification.title
            msg["From"] = self._from_addr
            msg["To"] = recipient
            msg["X-Mulan-Trace-Id"] = trace_id

            # 渲染 HTML 正文
            html_body = _render_template(event_type, notification, event, payload, "")
            text_part = MIMEText(html_body, "html", "utf-8")
            msg.attach(text_part)

            # 发送
            with self._create_smtp() as server:
                server.sendmail(self._from_addr, [recipient], msg.as_bytes())

            logger.info("[%s] 邮件已发送: to=%s, subject=%s", trace_id, recipient, notification.title)
            return ChannelDeliveryResult(
                status="delivered",
                detail="SMTP 250 OK",
            )

        except smtplib.SMTPAuthenticationError as e:
            logger.warning("[%s] SMTP 认证失败: %s", trace_id, e)
            return ChannelDeliveryResult(
                status="permanent_failed",
                detail=f"SMTP 认证失败: {e}",
                error_code="EVT_010",
            )
        except smtplib.SMTPRecipientsRefused as e:
            # 收件人被拒 → permanent
            logger.warning("[%s] 收件人被拒: %s, recipient=%s", trace_id, e, recipient)
            return ChannelDeliveryResult(
                status="permanent_failed",
                detail=f"收件人被拒: {e}",
                error_code="EVT_014",
            )
        except smtplib.SMTPServerDisconnected as e:
            logger.warning("[%s] SMTP 服务器断开: %s", trace_id, e)
            return ChannelDeliveryResult(
                status="retryable_failed",
                detail=f"SMTP 服务器断开: {e}",
                error_code="EVT_010",
            )
        except smtplib.SMTPException as e:
            # 其他 SMTP 错误，判断是否为永久失败
            if e.smtp_code and 500 <= e.smtp_code < 600:
                return ChannelDeliveryResult(
                    status="permanent_failed",
                    detail=f"SMTP 5xx 错误: {e}",
                    error_code="EVT_010",
                )
            return ChannelDeliveryResult(
                status="retryable_failed",
                detail=f"SMTP 错误: {e}",
                error_code="EVT_010",
            )
        except Exception as e:
            # 模板渲染失败等 → permanent
            logger.error("[%s] 邮件发送异常: %s", trace_id, e)
            return ChannelDeliveryResult(
                status="permanent_failed",
                detail=f"邮件发送异常: {e}",
                error_code="EVT_015" if "template" in str(e).lower() else "EVT_010",
            )

    def _create_smtp(self):
        """创建 SMTP 连接（根据配置使用 SSL 或 TLS）"""
        if self._port == 465:
            return smtplib.SMTP_SSL(self._host, self._port, timeout=10)
        else:
            server = smtplib.SMTP(self._host, self._port, timeout=10)
            if self._use_tls:
                server.starttls()
            server.login(self._user, self._password)
            return server