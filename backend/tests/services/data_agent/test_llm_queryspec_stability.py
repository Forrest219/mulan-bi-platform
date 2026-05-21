"""Stability tests for LLM QuerySpec planning failure classification."""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.skip(
    "TDE-06/TDE-09: legacy LLM QuerySpec parsing/repair and mcp_first_main stability tests "
    "are decommissioned; deletion target is QuerySpec fallback and mcp_first_main production removal "
    "under TDE-24/TDE-26/TDE-30. Generic LLM provider error classification moved to "
    "test_llm_service_error_classification.py.",
    allow_module_level=True,
)

from app.core.errors import MulanError
from services.data_agent import mcp_first_main
from services.data_agent.intent_classifier import IntentClassification
from services.data_agent.mcp_first_main import _call_llm_json
from services.data_agent.tool_base import ToolContext
from services.llm.service import (
    LLM_AUTH_CONFIG_ERROR,
    LLM_PROVIDER_TIMEOUT,
    LLM_THINKING_ONLY_RESPONSE,
    LLMService,
)

pytestmark = pytest.mark.skip_db


def _messages() -> list[dict[str, str]]:
    return [{"role": "system", "content": "system"}, {"role": "user", "content": "user"}]


def _valid_queryspec(metric: str = "指标Y") -> dict:
    return {
        "intent": "aggregate",
        "operator": "aggregate",
        "datasource": {"name": "测试数据源", "luid": "ds-1"},
        "metrics": [{"field": metric, "aggregation": "SUM"}],
        "dimensions": [],
        "filters": [],
        "time": None,
        "sort": [],
        "limit": 100,
    }


def _selected_context(trace_id: str) -> ToolContext:
    return ToolContext(
        session_id="s1",
        user_id=1,
        connection_id=2,
        trace_id=trace_id,
        selected_datasource_luid="ds-1",
        datasource_name="测试数据源",
    )


class _FakeHostCatalog:
    async def load_catalog(self, **kwargs):
        return {
            "tools": [
                {
                    "name": "get-datasource-metadata",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"datasourceLuid": {"type": "string"}},
                        "required": ["datasourceLuid"],
                    },
                },
                {
                    "name": "query-datasource",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "datasourceLuid": {"type": "string"},
                            "query": {"type": "object"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["datasourceLuid", "query"],
                    },
                },
            ]
        }


class _FakeHostExecutor:
    async def execute_tool(self, tool_name, arguments, context):
        if tool_name == "get-datasource-metadata":
            return {"fields": [{"name": "指标Y", "dataType": "REAL"}]}
        return {"fields": ["SUM(指标Y)"], "rows": [[100]]}


class _FakeHostPlanner:
    def __init__(self):
        self.actions = [
            {
                "action": "tool_call",
                "tool_call": {
                    "tool": "query-datasource",
                    "arguments": {
                        "datasourceLuid": "ds-1",
                        "query": {"fields": [{"fieldCaption": "指标Y", "function": "SUM"}]},
                        "limit": 20,
                    },
                },
            },
            {"action": "final"},
        ]

    async def plan(self, **kwargs):
        return self.actions.pop(0)


def _patch_host(monkeypatch) -> None:
    async def _load_components(**kwargs):
        return mcp_first_main._McpHostComponents(
            catalog=_FakeHostCatalog(),
            executor=_FakeHostExecutor(),
            planner=_FakeHostPlanner(),
        )

    monkeypatch.setattr(mcp_first_main, "_load_mcp_host_components", _load_components)


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


class _ContentLLM:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        self.calls.append({"timeout": timeout, "purpose": purpose})
        return {"content": self.content}


@pytest.mark.asyncio
async def test_complete_classifies_active_config_provider_timeout():
    service = _service()
    service._config_db = MagicMock()
    service._config_db.get_active_configs.return_value = [_config()]
    service._config_db.get_config.return_value = None
    service._anthropic_complete = AsyncMock(side_effect=TimeoutError("Request timed out or interrupted"))

    with patch("services.llm.service._decrypt", return_value="fake-key"):
        with pytest.raises(MulanError) as caught:
            await service.complete("prompt", system="system", timeout=18, purpose="data_agent_queryspec")

    detail = caught.value.error_detail
    assert detail["error_code"] == LLM_PROVIDER_TIMEOUT
    assert detail["attempts"][0]["error_code"] == LLM_PROVIDER_TIMEOUT
    assert detail["attempts"][0]["purpose"] == "data_agent_queryspec"


@pytest.mark.asyncio
async def test_complete_classifies_api_key_decrypt_failure():
    service = _service()
    service._config_db = MagicMock()
    service._config_db.get_active_configs.return_value = [_config()]
    service._config_db.get_config.return_value = None

    with patch("services.llm.service._decrypt", side_effect=RuntimeError("decrypt failed")):
        with pytest.raises(MulanError) as caught:
            await service.complete("prompt", system="system", timeout=18, purpose="data_agent_queryspec")

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
        purpose="data_agent_queryspec",
    )

    assert result["error_code"] == LLM_THINKING_ONLY_RESPONSE


@pytest.mark.asyncio
async def test_call_llm_json_rejects_partial_metric_object():
    result = await _call_llm_json(
        _ContentLLM('{"field":"指标Y","aggregation":"SUM"}'),
        _messages(),
        purpose="data_agent_queryspec",
    )

    assert result["ok"] is False
    assert result["error_code"] == "QS_JSON_NOT_FOUND"


@pytest.mark.asyncio
async def test_call_llm_json_selects_complete_queryspec_from_multiple_objects():
    content = "\n".join(
        [
            '{"field":"指标Y","aggregation":"SUM"}',
            json.dumps(_valid_queryspec(), ensure_ascii=False),
        ]
    )

    result = await _call_llm_json(_ContentLLM(content), _messages(), purpose="data_agent_queryspec")

    assert result["ok"] is True
    assert result["json"]["intent"] == "aggregate"
    assert result["json"]["metrics"][0]["field"] == "指标Y"


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Q1", "Q8"])
async def test_q1_q8_queryspec_canary_accepts_complete_contract(label):
    spec = _valid_queryspec(metric=f"{label}_指标")
    result = await _call_llm_json(
        _ContentLLM(json.dumps(spec, ensure_ascii=False)),
        _messages(),
        purpose="data_agent_queryspec",
    )

    assert result["ok"] is True
    assert result["json"]["metrics"][0]["field"] == f"{label}_指标"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,content",
    [
        ("Q5", '{"field":"指标Y","aggregation":"SUM"}'),
        ("Q6", '{"type":"all"}'),
        ("Q10", '{"field":"维度X","op":"IN","values":["A"]}'),
    ],
)
async def test_q5_q6_q10_partial_json_is_not_queryspec_success(label, content):
    result = await _call_llm_json(_ContentLLM(content), _messages(), purpose="data_agent_queryspec")

    assert result["ok"] is False, label
    assert result["error_code"] in {"QS_JSON_NOT_FOUND", "QS_JSON_INVALID"}


class _ModelInvalidThenRepairLLM:
    def __init__(self):
        self.queryspec_calls = 0

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            self.queryspec_calls += 1
            if self.queryspec_calls == 1:
                return {
                    "content": json.dumps(
                        {
                            "intent": "aggregate",
                            "operator": "aggregate",
                            "datasource": {"name": "测试数据源", "luid": "ds-1"},
                            "metrics": [{}],
                            "dimensions": [],
                            "filters": [],
                        },
                        ensure_ascii=False,
                    )
                }
            return {"content": json.dumps(_valid_queryspec(), ensure_ascii=False)}
        if purpose == "data_agent_answer":
            return {"content": "指标Y 为 100。"}
        raise AssertionError(f"unexpected purpose: {purpose}")


class _ProviderTimeoutLLM:
    def __init__(self):
        self.queryspec_calls = 0

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            self.queryspec_calls += 1
            return {"error": "LLM provider 调用超时", "error_code": LLM_PROVIDER_TIMEOUT}
        raise AssertionError(f"unexpected purpose: {purpose}")


class _ProviderTimeoutThenMcpArgsLLM:
    def __init__(self):
        self.queryspec_calls = 0

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        if purpose == "data_agent_queryspec":
            self.queryspec_calls += 1
            return {"error": "LLM provider 调用超时", "error_code": LLM_PROVIDER_TIMEOUT}
        if purpose == "data_agent_mcp_proxy_args":
            return {
                "content": json.dumps(
                    {
                        "datasourceLuid": "ds-1",
                        "query": {"fields": [{"fieldCaption": "指标Y", "function": "SUM"}]},
                        "limit": 20,
                    },
                    ensure_ascii=False,
                )
            }
        if purpose == "data_agent_answer":
            return {"content": ""}
        raise AssertionError(f"unexpected purpose: {purpose}")


@pytest.mark.asyncio
async def test_queryspec_model_invalid_triggers_one_repair(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    _patch_host(monkeypatch)
    llm = _ModelInvalidThenRepairLLM()

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="指标Y 总量是多少？",
            context=_selected_context("trace-repair"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="test"),
            llm_service=llm,
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert llm.queryspec_calls == 0
    assert "llm_queryspec" not in tool_names
    assert "llm_queryspec_repair" not in tool_names
    assert "mcp_host_planner" in tool_names
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_provider_timeout_does_not_trigger_queryspec_repair(monkeypatch):
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.setenv("DATA_AGENT_QUERYSPEC_MCP_FALLBACK_ENABLED", "false")
    _patch_host(monkeypatch)
    llm = _ProviderTimeoutLLM()

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="指标Y 总量是多少？",
            context=_selected_context("trace-timeout"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="test"),
            llm_service=llm,
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert llm.queryspec_calls == 0
    assert "llm_queryspec_repair" not in tool_names
    assert "llm_queryspec" not in tool_names
    assert "mcp_host_planner" in tool_names
    assert events[-1].type == "answer"


@pytest.mark.asyncio
async def test_mcp_main_route_uses_guarded_mcp_without_queryspec(monkeypatch):
    from services.data_agent import mcp_proxy_main

    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_FALLBACK_ENABLED", raising=False)
    monkeypatch.delenv("DATA_AGENT_QUERYSPEC_MCP_FALLBACK_ENABLED", raising=False)
    _patch_host(monkeypatch)
    llm = _ProviderTimeoutThenMcpArgsLLM()

    events = [
        event
        async for event in mcp_first_main.run_mcp_first_main_path(
            question="指标Y 总量是多少？",
            context=_selected_context("trace-timeout-mcp"),
            intent_result=IntentClassification(intent="aggregate", confidence=0.9, route_reason="test"),
            llm_service=llm,
        )
    ]

    tool_names = [
        event.content["tool"]
        for event in events
        if event.type in {"tool_call", "tool_result"} and isinstance(event.content, dict)
    ]
    assert llm.queryspec_calls == 0
    assert "llm_queryspec" not in tool_names
    assert "llm_queryspec_repair" not in tool_names
    assert "mcp_args_guardrail" not in tool_names
    assert "mcp_host_planner" in tool_names
    assert "tableau_mcp" in tool_names
    assert "queryspec_mcp_fallback" not in tool_names
    assert events[-1].type == "answer"
