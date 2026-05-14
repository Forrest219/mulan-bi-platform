"""Chain mode selection for controlled Data Agent paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


CHAIN_MODE_LEGACY_QUERYSPEC = "legacy_queryspec"
CHAIN_MODE_MCP_PROXY = "mcp_proxy"
ENV_CHAIN_MODE = "DATA_AGENT_CHAIN_MODE"
ENV_MCP_PROXY_ENABLED = "DATA_AGENT_MCP_PROXY_ENABLED"


@dataclass(frozen=True)
class ChainSelection:
    requested_mode: str
    selected_mode: str
    mcp_proxy_enabled: bool
    fallback_reason: Optional[str] = None

    @property
    def is_mcp_proxy(self) -> bool:
        return self.selected_mode == CHAIN_MODE_MCP_PROXY

    @property
    def is_fallback(self) -> bool:
        return self.fallback_reason is not None

    def fallback_message(self) -> Optional[str]:
        if self.fallback_reason == "mcp_proxy_disabled":
            return "已请求 MCP Proxy 链路，但 DATA_AGENT_MCP_PROXY_ENABLED 未开启，本次回退到 legacy QuerySpec 链路。"
        if self.fallback_reason == "invalid_chain_mode":
            return (
                f"DATA_AGENT_CHAIN_MODE={self.requested_mode} 不受支持，"
                "本次回退到 legacy QuerySpec 链路。"
            )
        return None

    def trace_detail(self) -> dict:
        return {
            "requested_chain_mode": self.requested_mode,
            "selected_chain_mode": self.selected_mode,
            "mcp_proxy_enabled": self.mcp_proxy_enabled,
            "fallback_reason": self.fallback_reason,
        }


def select_data_agent_chain(env: Optional[Mapping[str, str]] = None) -> ChainSelection:
    """Select the controlled Data Agent chain from feature flags.

    P0 only allows MCP Proxy when both conditions are true:
    DATA_AGENT_CHAIN_MODE=mcp_proxy and DATA_AGENT_MCP_PROXY_ENABLED=true.
    Every other configuration falls back to the legacy QuerySpec chain.
    """

    env_map = env if env is not None else os.environ
    requested_mode = str(env_map.get(ENV_CHAIN_MODE, CHAIN_MODE_LEGACY_QUERYSPEC)).strip().lower()
    mcp_enabled = _env_bool(env_map.get(ENV_MCP_PROXY_ENABLED, "false"))

    if requested_mode == CHAIN_MODE_LEGACY_QUERYSPEC:
        return ChainSelection(
            requested_mode=requested_mode,
            selected_mode=CHAIN_MODE_LEGACY_QUERYSPEC,
            mcp_proxy_enabled=mcp_enabled,
        )

    if requested_mode == CHAIN_MODE_MCP_PROXY:
        if mcp_enabled:
            return ChainSelection(
                requested_mode=requested_mode,
                selected_mode=CHAIN_MODE_MCP_PROXY,
                mcp_proxy_enabled=True,
            )
        return ChainSelection(
            requested_mode=requested_mode,
            selected_mode=CHAIN_MODE_LEGACY_QUERYSPEC,
            mcp_proxy_enabled=False,
            fallback_reason="mcp_proxy_disabled",
        )

    return ChainSelection(
        requested_mode=requested_mode or CHAIN_MODE_LEGACY_QUERYSPEC,
        selected_mode=CHAIN_MODE_LEGACY_QUERYSPEC,
        mcp_proxy_enabled=mcp_enabled,
        fallback_reason="invalid_chain_mode",
    )


def _env_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
