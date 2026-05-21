"""Generic LLM provider error classification tests for Data Agent callers."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import MulanError
from services.llm.service import (
    LLM_AUTH_CONFIG_ERROR,
    LLM_PROVIDER_TIMEOUT,
    LLM_THINKING_ONLY_RESPONSE,
    LLMService,
)

pytestmark = pytest.mark.skip_db


def _config() -> MagicMock:
    cfg = MagicMock()
    cfg.provider = "minimax"
    cfg.base_url = "https://api.minimaxi.com/anthropic"
    cfg.model = "MiniMax-M2.7"
    cfg.temperature = 0.1
    cfg.max_tokens = 1024
    cfg.api_key_encrypted = "encrypted-key"
    cfg.is_active = True
    cfg.priority = 10
    return cfg


def _service() -> LLMService:
    return object.__new__(LLMService)


@pytest.mark.asyncio
async def test_complete_classifies_active_config_provider_timeout():
    service = _service()
    service._config_db = MagicMock()
    service._config_db.get_active_configs.return_value = [_config()]
    service._config_db.get_config.return_value = None
    service._anthropic_complete = AsyncMock(side_effect=TimeoutError("Request timed out or interrupted"))

    with patch("services.llm.service._decrypt", return_value="fake-key"):
        with pytest.raises(MulanError) as caught:
            await service.complete(
                "prompt",
                system="system",
                timeout=18,
                purpose="data_agent_mcp_proxy_planner",
            )

    detail = caught.value.error_detail
    assert detail["error_code"] == LLM_PROVIDER_TIMEOUT
    assert detail["attempts"][0]["error_code"] == LLM_PROVIDER_TIMEOUT
    assert detail["attempts"][0]["purpose"] == "data_agent_mcp_proxy_planner"


@pytest.mark.asyncio
async def test_complete_classifies_api_key_decrypt_failure():
    service = _service()
    service._config_db = MagicMock()
    service._config_db.get_active_configs.return_value = [_config()]
    service._config_db.get_config.return_value = None

    with patch("services.llm.service._decrypt", side_effect=RuntimeError("decrypt failed")):
        with pytest.raises(MulanError) as caught:
            await service.complete(
                "prompt",
                system="system",
                timeout=18,
                purpose="data_agent_mcp_proxy_planner",
            )

    detail = caught.value.error_detail
    assert detail["error_code"] == LLM_AUTH_CONFIG_ERROR
    assert detail["attempts"][0]["error_code"] == LLM_AUTH_CONFIG_ERROR


@pytest.mark.asyncio
async def test_minimax_thinking_only_response_is_planning_error(monkeypatch):
    class MockTextBlock:
        def __init__(self, text: str):
            self.text = text

    class MockThinkingBlock:
        def __init__(self, thinking: str):
            self.thinking = thinking

    anthropic_module = types.ModuleType("anthropic")
    anthropic_types = types.ModuleType("anthropic.types")
    anthropic_types.TextBlock = MockTextBlock
    anthropic_module.types = anthropic_types
    monkeypatch.setitem(sys.modules, "anthropic", anthropic_module)
    monkeypatch.setitem(sys.modules, "anthropic.types", anthropic_types)

    service = _service()
    response = MagicMock()
    response.content = [MockThinkingBlock("internal reasoning")]
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    service._get_anthropic_client = MagicMock(return_value=client)

    result = await service._anthropic_complete(
        api_key="fake-key",
        config=_config(),
        prompt="prompt",
        system="system",
        timeout=18,
        purpose="data_agent_mcp_proxy_planner",
    )

    assert result["error_code"] == LLM_THINKING_ONLY_RESPONSE
