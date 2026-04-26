"""
单元测试：services/capability/registry.py
覆盖：
- load_registry / get_capability / list_all
- rate_limit 字符串解析
- CapabilityNotFound
- CapabilityRegistryError（无效 YAML）
"""
import pytest
from services.capability.errors import CapabilityNotFound, CapabilityRegistryError
from services.capability.registry import (
    RateLimitConfig,
    _parse_rate_limit,
    get_capability,
    list_all,
    load_registry,
)


class TestRateLimitParsing:
    """rate_limit 字符串解析"""

    def test_parse_30_per_min_user(self):
        rl = _parse_rate_limit("30/min/user")
        assert rl.rate == 30
        assert rl.window == 60
        assert rl.scope == "user"

    def test_parse_100_per_hour_global(self):
        rl = _parse_rate_limit("100/h/global")
        assert rl.rate == 100
        assert rl.window == 3600
        assert rl.scope == "global"

    def test_parse_5_per_second(self):
        rl = _parse_rate_limit("5/s/user")
        assert rl.rate == 5
        assert rl.window == 5
        assert rl.scope == "user"

    def test_parse_invalid_format(self):
        with pytest.raises(CapabilityRegistryError):
            _parse_rate_limit("30permin")


class TestRegistryLoad:
    """Registry 加载"""

    def test_load_registry_returns_capabilities(self):
        caps = list_all()
        assert len(caps) > 0

    def test_get_capability_query_metric(self):
        cap = get_capability("query_metric")
        assert cap.name == "query_metric"
        assert "analyst" in cap.roles
        assert cap.timeout_seconds == 30

    def test_get_capability_not_found(self):
        with pytest.raises(CapabilityNotFound):
            get_capability("nonexistent_capability")

    def test_query_metric_has_cache_config(self):
        cap = get_capability("query_metric")
        assert cap.cache.ttl_seconds == 300
        assert "principal_role" in cap.cache.key_fields

    def test_query_metric_has_circuit_breaker_config(self):
        cap = get_capability("query_metric")
        assert cap.circuit_breaker.failure_threshold == 5
        assert cap.circuit_breaker.recovery_seconds == 60

    def test_query_metric_rate_limit(self):
        cap = get_capability("query_metric")
        assert cap.rate_limit.rate == 30
        assert cap.rate_limit.window == 60
        assert cap.rate_limit.scope == "user"
