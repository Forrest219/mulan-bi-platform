"""Capability Registry — YAML 驱动能力定义注册表

对应 spec §5.1 — 加载 config/capabilities.yaml，
按 name 查找能力定义，并验证 schema。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import CapabilityNotFound, CapabilityRegistryError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 能力定义数据类
# ---------------------------------------------------------------------------

@dataclass
class RateLimitConfig:
    """rate_limit 解析结果"""
    rate: int          # 请求数
    window: int        # 时间窗口（秒）
    scope: str         # user | global


@dataclass
class CacheConfig:
    """缓存配置"""
    ttl_seconds: int = 300
    key_fields: list[str] = field(default_factory=list)


@dataclass
class CircuitBreakerConfig:
    """熔断配置"""
    failure_threshold: int = 5
    recovery_seconds: int = 60


@dataclass
class GuardsConfig:
    """Guards 配置"""
    sensitivity_block: list[str] = field(default_factory=list)
    max_rows: int = 10000
    forbid_raw_pii: bool = False


@dataclass
class CapabilityDefinition:
    """单个能力定义"""
    name: str
    description: str
    roles: list[str]
    params_schema: dict[str, Any]
    guards: GuardsConfig
    rate_limit: RateLimitConfig
    timeout_seconds: int = 30
    cache: CacheConfig = field(default_factory=CacheConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    audit: str = "always"
    backend: str = "tableau_mcp"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_CAPABILITY_REGISTRY: list[CapabilityDefinition] = []
_REGISTRY_LOADED: bool = False


def _parse_rate_limit(raw: str) -> RateLimitConfig:
    """解析 rate_limit 字符串，如 '30/min/user' → RateLimitConfig(rate=30, window=60, scope='user')"""
    parts = raw.strip().split("/")
    if len(parts) != 3:
        raise CapabilityRegistryError(f"Invalid rate_limit format: {raw!r} (expected '{{rate}}/{{window}}/{{scope}}')")

    rate = int(parts[0])
    window_raw = parts[1]
    scope = parts[2]

    # window 支持 s, m, h 后缀
    if window_raw.endswith("s"):
        window = int(window_raw[:-1])
    elif window_raw.endswith("m"):
        window = int(window_raw[:-1]) * 60
    elif window_raw.endswith("h"):
        window = int(window_raw[:-1]) * 3600
    else:
        window = int(window_raw)

    return RateLimitConfig(rate=rate, window=window, scope=scope)


def _load_yaml_config() -> list[CapabilityDefinition]:
    """从 config/capabilities.yaml 加载所有能力定义"""
    # 向上查找 config 目录
    backend_dir = Path(__file__).parent.parent.parent
    config_path = backend_dir / "config" / "capabilities.yaml"

    # 也支持项目根目录
    if not config_path.exists():
        project_root = backend_dir.parent.parent
        config_path = project_root / "config" / "capabilities.yaml"

    if not config_path.exists():
        raise CapabilityRegistryError(f"Capability config not found at {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise CapabilityRegistryError(f"Failed to parse YAML: {e}") from e

    version = data.get("version")
    if version != 1:
        logger.warning("Unknown capabilities.yaml version: %s (expected 1)", version)

    capabilities = []
    for raw_cap in data.get("capabilities", []):
        try:
            guards_raw = raw_cap.get("guards", {})
            guards = GuardsConfig(
                sensitivity_block=guards_raw.get("sensitivity_block", []),
                max_rows=guards_raw.get("max_rows", 10000),
                forbid_raw_pii=guards_raw.get("forbid_raw_pii", False),
            )

            rl_raw = raw_cap.get("rate_limit", "100/min/user")
            rate_limit = _parse_rate_limit(rl_raw)

            cache_raw = raw_cap.get("cache", {})
            cache = CacheConfig(
                ttl_seconds=cache_raw.get("ttl_seconds", 300),
                key_fields=cache_raw.get("key_fields", []),
            )

            cb_raw = raw_cap.get("circuit_breaker", {})
            cb = CircuitBreakerConfig(
                failure_threshold=cb_raw.get("failure_threshold", 5),
                recovery_seconds=cb_raw.get("recovery_seconds", 60),
            )

            cap = CapabilityDefinition(
                name=raw_cap["name"],
                description=raw_cap.get("description", ""),
                roles=raw_cap.get("roles", []),
                params_schema=raw_cap.get("params_schema", {}),
                guards=guards,
                rate_limit=rate_limit,
                timeout_seconds=raw_cap.get("timeout_seconds", 30),
                cache=cache,
                circuit_breaker=cb,
                audit=raw_cap.get("audit", "always"),
                backend=raw_cap.get("backend", "tableau_mcp"),
            )
            capabilities.append(cap)
        except Exception as e:
            raise CapabilityRegistryError(f"Failed to parse capability definition: {e}") from e

    return capabilities


def load_registry() -> None:
    """加载/重载 Registry（在应用启动时调用）"""
    global _CAPABILITY_REGISTRY, _REGISTRY_LOADED
    _CAPABILITY_REGISTRY = _load_yaml_config()
    _REGISTRY_LOADED = True
    logger.info("Capability registry loaded: %d capabilities", len(_CAPABILITY_REGISTRY))


def get_registry() -> list[CapabilityDefinition]:
    """获取已加载的所有能力定义"""
    if not _REGISTRY_LOADED:
        load_registry()
    return _CAPABILITY_REGISTRY


def get_capability(name: str) -> CapabilityDefinition:
    """根据 name 查找单个能力定义"""
    if not _REGISTRY_LOADED:
        load_registry()
    for cap in _CAPABILITY_REGISTRY:
        if cap.name == name:
            return cap
    raise CapabilityNotFound(f"Capability '{name}' not found in registry")


def list_all() -> list[CapabilityDefinition]:
    """列出所有已注册的能力"""
    return get_registry()
