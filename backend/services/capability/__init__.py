"""Capability Wrapper — Phase 1.5 完整模块

导出公共 API：
- CapabilityWrapper — 统一调用入口
- CapabilityResult — 调用结果
- CapabilityDefinition — 能力定义数据类
- CapabilityError / CAP_xxx — 异常体系
"""
from .circuit_breaker import CircuitBreaker, CircuitState
from .cost_meter import CostMeter, CostRecord
from .errors import (
    CapabilityAuthzDenied,
    CapabilityCircuitOpen,
    CapabilityDownstreamError,
    CapabilityError,
    CapabilityInternalError,
    CapabilityNotFound,
    CapabilityParamsInvalid,
    CapabilityRateLimited,
    CapabilityRegistryError,
    CapabilitySensitivityBlocked,
    CapabilityTimeout,
)
from .rate_limiter import RateLimiter
from .registry import (
    CapabilityDefinition,
    CacheConfig,
    CircuitBreakerConfig,
    GuardsConfig,
    RateLimitConfig,
    get_capability,
    list_all,
    load_registry,
)
from .result_cache import ResultCache
from .sensitivity import check as sensitivity_check
from .wrapper import CapabilityResult, CapabilityWrapper, register_backend

__all__ = [
    # Core
    "CapabilityWrapper",
    "CapabilityResult",
    "CapabilityDefinition",
    "register_backend",
    # Registry
    "RateLimitConfig",
    "CacheConfig",
    "CircuitBreakerConfig",
    "GuardsConfig",
    "get_capability",
    "list_all",
    "load_registry",
    # Rate Limiter
    "RateLimiter",
    # Result Cache
    "ResultCache",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitState",
    # Cost Meter
    "CostMeter",
    "CostRecord",
    # Sensitivity
    "sensitivity_check",
    # Errors
    "CapabilityError",
    "CapabilityAuthzDenied",
    "CapabilityParamsInvalid",
    "CapabilitySensitivityBlocked",
    "CapabilityRateLimited",
    "CapabilityDownstreamError",
    "CapabilityCircuitOpen",
    "CapabilityTimeout",
    "CapabilityNotFound",
    "CapabilityInternalError",
    "CapabilityRegistryError",
]
