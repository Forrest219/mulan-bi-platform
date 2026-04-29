"""通知渠道层"""
from .base import BaseChannel, ChannelDeliveryResult, DeliveryStatus
from .email_channel import EmailChannel
from .webhook_channel import WebhookChannel

__all__ = [
    "BaseChannel",
    "ChannelDeliveryResult",
    "DeliveryStatus",
    "EmailChannel",
    "WebhookChannel",
]