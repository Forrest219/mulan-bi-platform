"""Webhook 出站渠道（WebhookChannel）"""
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Optional

import httpx

from .base import BaseChannel, ChannelDeliveryResult
from services.common.settings import get_fernet_master_key

logger = logging.getLogger(__name__)

# Webhook 配置
_CONNECT_TIMEOUT = 5
_READ_TIMEOUT = 10
_MAX_PAYLOAD_KB = 64


def _get_fernet():
    """获取 Fernet 实例（惰性加载）"""
    master_key = get_fernet_master_key()
    if not master_key:
        return None
    from cryptography.fernet import Fernet
    return Fernet(master_key.encode())


def _canonical_json(payload: dict) -> bytes:
    """生成规范化的 JSON bytes（sort_keys + 紧凑分隔）"""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sign_payload(payload_bytes: bytes, secret_encrypted: str) -> str:
    """对 payload 进行 HMAC-SHA256 签名"""
    fernet = _get_fernet()
    if not fernet:
        raise ValueError("EVT_016: FERNET_MASTER_KEY 未配置")
    try:
        secret_bytes = fernet.decrypt(secret_encrypted.encode())
    except Exception:
        raise ValueError("EVT_016: Webhook secret 无法解密")
    sig = hmac.new(secret_bytes, payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _truncate_payload(payload: dict) -> dict:
    """payload > 64KB 时截断 data 字段并添加 _truncated: true"""
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) <= _MAX_PAYLOAD_KB * 1024:
        return payload
    # 截断：复制 payload，缩短 data 字段
    truncated = payload.copy()
    if "data" in truncated and isinstance(truncated["data"], str):
        # 计算目标大小（留出余量给 _truncated 字段）
        target_size = _MAX_PAYLOAD_KB * 1024 - 200
        # 逐步缩短直到满足大小
        while len(json.dumps(truncated, ensure_ascii=False).encode("utf-8")) > target_size and len(truncated["data"]) > 0:
            truncated["data"] = truncated["data"][:-1000]
    truncated["_truncated"] = True
    return truncated


class WebhookChannel(BaseChannel):
    """Webhook 出站渠道（继承 BaseChannel）"""

    def __init__(self):
        self._fernet = _get_fernet()

    def send(
        self,
        notification,
        recipient: str,
        *,
        trace_id: str,
        secret_encrypted: str,
        event_type: str = "unknown",
        event_id: Optional[int] = None,
    ) -> ChannelDeliveryResult:
        """
        发送 Webhook POST 请求。

        Returns:
            delivered: HTTP 2xx
            retryable_failed: HTTP 5xx / 连接超时 / DNS 故障 / 读超时
            permanent_failed: HTTP 4xx / URL 校验失败 / Fernet 解密失败
        """
        # 构建 payload
        event = getattr(notification, "event", None)
        payload_dict = {
            "notification_id": notification.id,
            "title": notification.title,
            "content": notification.content,
            "level": notification.level,
            "event_type": event_type,
            "event_id": event_id,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        }
        if event:
            payload_dict["payload_json"] = event.payload_json or {}

        # 截断检查
        payload_dict = _truncate_payload(payload_dict)

        # 生成规范 JSON
        canonical = _canonical_json(payload_dict)

        # 签名
        try:
            signature = _sign_payload(canonical, secret_encrypted)
        except ValueError as e:
            return ChannelDeliveryResult(
                status="permanent_failed",
                detail=str(e),
                error_code="EVT_016",
            )

        # 请求头
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Mulan-Event-Type": event_type,
            "X-Mulan-Event-Id": str(event_id) if event_id else "",
            "X-Mulan-Trace-Id": trace_id,
            "X-Mulan-Signature": signature,
            "User-Agent": "Mulan-Webhook/1.1",
        }

        try:
            start = time.time()
            with httpx.Client(timeout=httpx.Timeout(_CONNECT_TIMEOUT, _READ_TIMEOUT)) as client:
                resp = client.post(recipient, content=canonical, headers=headers)
            latency_ms = int((time.time() - start) * 1000)

            if resp.status_code < 400:
                logger.info(
                    "[%s] Webhook 投递成功: url=%s, status=%s, latency_ms=%s",
                    trace_id, recipient, resp.status_code, latency_ms,
                )
                return ChannelDeliveryResult(
                    status="delivered",
                    detail=f"HTTP {resp.status_code} in {latency_ms}ms",
                )
            elif resp.status_code < 500:
                # 4xx → permanent_failed，不重试
                logger.warning(
                    "[%s] Webhook 接收端返回 4xx: url=%s, status=%s",
                    trace_id, recipient, resp.status_code,
                )
                return ChannelDeliveryResult(
                    status="permanent_failed",
                    detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    error_code="EVT_014",
                )
            else:
                # 5xx → retryable_failed
                logger.warning(
                    "[%s] Webhook 接收端返回 5xx: url=%s, status=%s",
                    trace_id, recipient, resp.status_code,
                )
                return ChannelDeliveryResult(
                    status="retryable_failed",
                    detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    error_code="EVT_013",
                )

        except httpx.ConnectTimeout:
            logger.warning("[%s] Webhook 连接超时: url=%s", trace_id, recipient)
            return ChannelDeliveryResult(
                status="retryable_failed",
                detail="连接超时（5s）",
                error_code="EVT_012",
            )
        except httpx.ReadTimeout:
            logger.warning("[%s] Webhook 读超时: url=%s", trace_id, recipient)
            return ChannelDeliveryResult(
                status="retryable_failed",
                detail="读超时（10s）",
                error_code="EVT_012",
            )
        except httpx.ConnectError as e:
            logger.warning("[%s] Webhook 连接失败（含 DNS）: url=%s, error=%s", trace_id, recipient, e)
            return ChannelDeliveryResult(
                status="retryable_failed",
                detail=f"连接失败: {e}",
                error_code="EVT_011",
            )
        except httpx.RequestError as e:
            logger.warning("[%s] Webhook 请求错误: url=%s, error=%s", trace_id, recipient, e)
            return ChannelDeliveryResult(
                status="retryable_failed",
                detail=f"请求错误: {e}",
                error_code="EVT_012",
            )
        except Exception as e:
            logger.error("[%s] Webhook 投递异常: url=%s, error=%s", trace_id, recipient, e)
            return ChannelDeliveryResult(
                status="retryable_failed",
                detail=f"投递异常: {e}",
                error_code="EVT_012",
            )