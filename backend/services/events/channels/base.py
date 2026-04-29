"""通知渠道抽象基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional


DeliveryStatus = Literal["delivered", "retryable_failed", "permanent_failed"]


@dataclass
class ChannelDeliveryResult:
    """渠道投递结果（三态）"""
    status: DeliveryStatus
    detail: str
    error_code: Optional[str] = None


class BaseChannel(ABC):
    """出站渠道抽象基类"""

    @abstractmethod
    def send(
        self,
        notification,
        recipient: str,
        *,
        trace_id: str,
    ) -> ChannelDeliveryResult:
        """发送通知，返回投递结果"""
        ...