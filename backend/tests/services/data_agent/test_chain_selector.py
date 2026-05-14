from services.data_agent.chain_selector import (
    CHAIN_MODE_LEGACY_QUERYSPEC,
    CHAIN_MODE_MCP_PROXY,
    select_data_agent_chain,
)


def test_chain_selector_defaults_to_legacy_queryspec():
    selection = select_data_agent_chain({})

    assert selection.selected_mode == CHAIN_MODE_LEGACY_QUERYSPEC
    assert selection.requested_mode == CHAIN_MODE_LEGACY_QUERYSPEC
    assert selection.mcp_proxy_enabled is False
    assert selection.fallback_reason is None


def test_chain_selector_requires_mode_and_flag_for_mcp_proxy():
    selection = select_data_agent_chain(
        {
            "DATA_AGENT_CHAIN_MODE": "mcp_proxy",
            "DATA_AGENT_MCP_PROXY_ENABLED": "true",
        }
    )

    assert selection.selected_mode == CHAIN_MODE_MCP_PROXY
    assert selection.is_mcp_proxy is True
    assert selection.fallback_reason is None


def test_chain_selector_falls_back_when_mcp_proxy_flag_is_off():
    selection = select_data_agent_chain(
        {
            "DATA_AGENT_CHAIN_MODE": "mcp_proxy",
            "DATA_AGENT_MCP_PROXY_ENABLED": "false",
        }
    )

    assert selection.selected_mode == CHAIN_MODE_LEGACY_QUERYSPEC
    assert selection.is_mcp_proxy is False
    assert selection.fallback_reason == "mcp_proxy_disabled"
    assert "DATA_AGENT_MCP_PROXY_ENABLED" in (selection.fallback_message() or "")


def test_chain_selector_invalid_mode_falls_back_with_reason():
    selection = select_data_agent_chain(
        {
            "DATA_AGENT_CHAIN_MODE": "experimental",
            "DATA_AGENT_MCP_PROXY_ENABLED": "true",
        }
    )

    assert selection.selected_mode == CHAIN_MODE_LEGACY_QUERYSPEC
    assert selection.requested_mode == "experimental"
    assert selection.mcp_proxy_enabled is True
    assert selection.fallback_reason == "invalid_chain_mode"
