"""Capability Wrapper 异常体系 — CAP_001~CAP_010

所有 Capability 相关的业务异常都定义在这里，
与 spec §5 Error Codes 一一对应。
"""
from __future__ import annotations


class CapabilityError(Exception):
    """Capability 异常基类"""

    code: str = "CAP_999"
    http_status: int = 500
    message: str = "Unknown capability error"

    def __init__(self, message: str | None = None, detail: str | None = None):
        self.message = message or self.message
        self.detail = detail
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class CapabilityAuthzDenied(CapabilityError):
    """CAP_001 — Authz 拒绝(角色/身份不够)"""

    code = "CAP_001"
    http_status = 403
    message = "Authorization denied for this capability"


class CapabilityParamsInvalid(CapabilityError):
    """CAP_002 — params 不符 Schema"""

    code = "CAP_002"
    http_status = 400
    message = "Parameters do not match capability schema"


class CapabilitySensitivityBlocked(CapabilityError):
    """CAP_003 — 敏感度门禁拒绝"""

    code = "CAP_003"
    http_status = 403
    message = "Sensitivity check blocked this request"


class CapabilityRateLimited(CapabilityError):
    """CAP_004 — 限流触发"""

    code = "CAP_004"
    http_status = 429
    message = "Rate limit exceeded"
    retry_after: int = 60

    def __init__(self, message: str | None = None, retry_after: int | None = None):
        super().__init__(message)
        if retry_after is not None:
            self.retry_after = retry_after

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["retry_after"] = self.retry_after
        return d


class CapabilityDownstreamError(CapabilityError):
    """CAP_005 — 下游调用失败(Tableau/LLM)"""

    code = "CAP_005"
    http_status = 502
    message = "Downstream service failed"


class CapabilityCircuitOpen(CapabilityError):
    """CAP_006 — 熔断打开"""

    code = "CAP_006"
    http_status = 503
    message = "Circuit breaker is open"


class CapabilityTimeout(CapabilityError):
    """CAP_007 — 超时"""

    code = "CAP_007"
    http_status = 504
    message = "Capability timed out"


class CapabilityNotFound(CapabilityError):
    """CAP_008 — Capability 不存在"""

    code = "CAP_008"
    http_status = 400
    message = "Capability not found"


class CapabilityInternalError(CapabilityError):
    """CAP_009 — Capability 实现内部错误"""

    code = "CAP_009"
    http_status = 500
    message = "Internal capability error"


class CapabilityRegistryError(CapabilityError):
    """CAP_010 — Registry 加载失败(启动时)"""

    code = "CAP_010"
    http_status = 500
    message = "Failed to load capability registry"
