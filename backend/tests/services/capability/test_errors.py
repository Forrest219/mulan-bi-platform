"""
单元测试：services/capability/errors.py
覆盖：CAP_001~CAP_010 异常类的 code / http_status / message
"""
import pytest
from services.capability.errors import (
    CapabilityAuthzDenied,
    CapabilityCircuitOpen,
    CapabilityDownstreamError,
    CapabilityInternalError,
    CapabilityNotFound,
    CapabilityParamsInvalid,
    CapabilityRateLimited,
    CapabilityRegistryError,
    CapabilitySensitivityBlocked,
    CapabilityTimeout,
)


class TestCapabilityErrors:
    """所有 CapabilityError 子类的 code / http_status / message 验证"""

    @pytest.mark.parametrize("exc_cls,expected_code,expected_http", [
        (CapabilityAuthzDenied, "CAP_001", 403),
        (CapabilityParamsInvalid, "CAP_002", 400),
        (CapabilitySensitivityBlocked, "CAP_003", 403),
        (CapabilityRateLimited, "CAP_004", 429),
        (CapabilityDownstreamError, "CAP_005", 502),
        (CapabilityCircuitOpen, "CAP_006", 503),
        (CapabilityTimeout, "CAP_007", 504),
        (CapabilityNotFound, "CAP_008", 400),
        (CapabilityInternalError, "CAP_009", 500),
        (CapabilityRegistryError, "CAP_010", 500),
    ])
    def test_error_codes(self, exc_cls, expected_code, expected_http):
        exc = exc_cls()
        assert exc.code == expected_code
        assert exc.http_status == expected_http

    def test_rate_limited_retry_after(self):
        exc = CapabilityRateLimited(retry_after=120)
        assert exc.retry_after == 120
        d = exc.to_dict()
        assert d["retry_after"] == 120

    def test_error_to_dict(self):
        exc = CapabilityAuthzDenied("custom message", "some detail")
        d = exc.to_dict()
        assert d["code"] == "CAP_001"
        assert d["message"] == "custom message"
        assert d["detail"] == "some detail"
