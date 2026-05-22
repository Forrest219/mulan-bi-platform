import json

import pytest

from services.data_agent.tableau_mcp_planner import (
    TableauMcpLlmPlanner,
    TableauMcpPlannerError,
    TableauMcpPlannerRequest,
    parse_tableau_mcp_planner_output,
)
from services.data_agent.tool_base import ToolContext

pytestmark = pytest.mark.skip_db


class _FakeLLM:
    def __init__(self, payload=None, *, result=None, exc=None):
        self.payload = payload
        self.result = result
        self.exc = exc
        self.calls = []

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        self.calls.append({"prompt": prompt, "system": system, "timeout": timeout, "purpose": purpose})
        if self.exc:
            raise self.exc
        if self.result is not None:
            return self.result
        return {"content": json.dumps(self.payload, ensure_ascii=False)}


class _FakeLLMSequence:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def complete(self, *, prompt, system=None, timeout=None, purpose=None):
        self.calls.append({"prompt": prompt, "system": system, "timeout": timeout, "purpose": purpose})
        if not self.payloads:
            raise AssertionError("unexpected extra planner retry")
        payload = self.payloads.pop(0)
        return {"content": json.dumps(payload, ensure_ascii=False)}


def _request() -> TableauMcpPlannerRequest:
    context = ToolContext(session_id="s1", user_id=42, connection_id=7, trace_id="trace-planner")
    context.datasource_luid = "ds-1"
    context.datasource_name = "Sales"
    return TableauMcpPlannerRequest(
        question="show Sales by Region where Category is Furniture",
        datasource={"luid": "ds-1", "name": "Sales", "connection_id": 7},
        metadata_fields=[
            {"caption": "Sales", "role": "MEASURE", "dataType": "REAL"},
            {"caption": "Region", "role": "DIMENSION", "dataType": "STRING"},
            {"caption": "Category", "role": "DIMENSION", "dataType": "STRING"},
        ],
        queryable_fields=["Sales", "Region", "Category"],
        context=context,
        compiler_reason="unsupported_complex_filters",
    )


def _query_plan_payload(**overrides):
    payload = {
        "tool_name": "query-datasource",
        "args": {
            "datasourceLuid": "ds-1",
            "query": {
                "fields": [{"fieldCaption": "Region"}, {"fieldCaption": "Sales", "function": "SUM"}],
                "filters": [
                    {"field": {"fieldCaption": "Category"}, "filterType": "SET", "values": ["Furniture"]}
                ],
            },
            "limit": 100,
        },
        "reason": "The user asks for a filtered grouped aggregate.",
        "confidence": 0.88,
        "needs_clarification": False,
        "clarification": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_planner_returns_successful_mcp_tool_plan_contract():
    llm = _FakeLLM(_query_plan_payload())
    planner = TableauMcpLlmPlanner(llm_service=llm, timeout_seconds=3)

    plan = await planner.plan(_request())

    assert plan.status == "planned"
    assert plan.is_executable is True
    assert plan.tool_name == "query-datasource"
    assert plan.args["datasourceLuid"] == "ds-1"
    assert plan.args["query"]["fields"][1] == {"fieldCaption": "Sales", "function": "SUM"}
    assert plan.reason
    assert plan.confidence == 0.88
    assert plan.needs_clarification is False
    assert plan.clarification is None
    assert llm.calls[0]["purpose"] == "data_agent_mcp_proxy_args"


def test_parse_allows_missing_optional_clarification_when_not_needed():
    payload = _query_plan_payload()
    payload.pop("clarification")

    plan = parse_tableau_mcp_planner_output(json.dumps(payload, ensure_ascii=False))

    assert plan.status == "planned"
    assert plan.is_executable is True
    assert plan.needs_clarification is False
    assert plan.clarification is None
    assert plan.raw["_planner_contract"]["missing_optional"] == ["clarification"]


@pytest.mark.asyncio
async def test_planner_returns_model_clarification_without_executable_args():
    payload = _query_plan_payload(
        tool_name=None,
        args={},
        reason="The metric is ambiguous.",
        confidence=0.72,
        needs_clarification=True,
        clarification={"message": "请选择 Sales 还是 Profit。", "candidates": ["Sales", "Profit"]},
    )
    planner = TableauMcpLlmPlanner(llm_service=_FakeLLM(payload))

    plan = await planner.plan(_request())

    assert plan.status == "clarification"
    assert plan.is_executable is False
    assert plan.tool_name is None
    assert plan.args == {}
    assert plan.needs_clarification is True
    assert plan.clarification["message"] == "请选择 Sales 还是 Profit。"
    assert plan.clarification["candidates"] == ["Sales", "Profit"]


@pytest.mark.asyncio
async def test_planner_rejects_missing_clarification_when_needed():
    payload = _query_plan_payload(
        tool_name=None,
        args={},
        reason="The metric is ambiguous.",
        confidence=0.72,
        needs_clarification=True,
    )
    payload.pop("clarification")
    planner = TableauMcpLlmPlanner(llm_service=_FakeLLM(payload))

    plan = await planner.plan(_request())

    assert plan.status == "invalid_output"
    assert plan.error_code == "PLANNER_CONTRACT_FAILURE"
    assert plan.raw["detail"]["first_error_code"] == "TABLEAU_MCP_PLANNER_CLARIFICATION_REQUIRED"
    assert plan.raw["detail"]["planner_retry_attempted"] is True
    assert plan.raw["detail"]["planner_retry_success"] is False
    assert len(planner._llm_service.calls) == 2


@pytest.mark.asyncio
async def test_planner_retries_missing_clarification_and_accepts_valid_retry():
    invalid = _query_plan_payload(
        tool_name=None,
        args={},
        reason="The asset request needs clarification.",
        confidence=0.72,
        needs_clarification=True,
    )
    invalid.pop("clarification")
    valid = _query_plan_payload(
        tool_name=None,
        args={},
        reason="The asset request needs clarification.",
        confidence=0.72,
        needs_clarification=True,
        clarification={"message": "请选择 Tableau 连接。"},
    )
    llm = _FakeLLMSequence([invalid, valid])
    planner = TableauMcpLlmPlanner(llm_service=llm)

    plan = await planner.plan(_request())

    assert plan.status == "clarification"
    assert plan.clarification["message"] == "请选择 Tableau 连接。"
    assert plan.raw["_planner_retry"]["attempted"] is True
    assert plan.raw["_planner_retry"]["success"] is True
    assert "validation error" in llm.calls[1]["prompt"].lower()


@pytest.mark.parametrize("clarification", [None, "", "   ", {}, {"message": ""}, []])
def test_parse_rejects_empty_clarification_when_needed(clarification):
    payload = _query_plan_payload(
        tool_name=None,
        args={},
        reason="The metric is ambiguous.",
        confidence=0.72,
        needs_clarification=True,
        clarification=clarification,
    )

    with pytest.raises(TableauMcpPlannerError) as exc_info:
        parse_tableau_mcp_planner_output(json.dumps(payload, ensure_ascii=False))

    assert exc_info.value.code == "TABLEAU_MCP_PLANNER_CLARIFICATION_REQUIRED"


@pytest.mark.asyncio
async def test_planner_low_confidence_becomes_clarification_not_queryspec():
    planner = TableauMcpLlmPlanner(llm_service=_FakeLLM(_query_plan_payload(confidence=0.41)), min_confidence=0.65)

    plan = await planner.plan(_request())

    assert plan.status == "clarification"
    assert plan.error_code == "TABLEAU_MCP_PLANNER_LOW_CONFIDENCE"
    assert plan.tool_name is None
    assert plan.args == {}
    assert plan.needs_clarification is True
    assert "QuerySpec" not in json.dumps(plan.to_dict(), ensure_ascii=False)


@pytest.mark.asyncio
async def test_planner_timeout_returns_structured_failure():
    planner = TableauMcpLlmPlanner(llm_service=_FakeLLM(exc=TimeoutError("provider timed out")), timeout_seconds=3)

    plan = await planner.plan(_request())

    assert plan.status == "planner_timeout"
    assert plan.error_code == "TABLEAU_MCP_PLANNER_TIMEOUT"
    assert plan.is_executable is False
    assert plan.tool_name is None
    assert plan.args == {}


@pytest.mark.asyncio
async def test_planner_llm_error_returns_structured_failure():
    planner = TableauMcpLlmPlanner(
        llm_service=_FakeLLM(result={"error": "LLM unavailable", "error_code": "LLM_PROVIDER_ERROR"})
    )

    plan = await planner.plan(_request())

    assert plan.status == "planner_failed"
    assert plan.error_code == "TABLEAU_MCP_PLANNER_FAILED"
    assert plan.reason == "LLM unavailable"
    assert plan.is_executable is False


@pytest.mark.asyncio
async def test_planner_rejects_non_allowlist_tool():
    planner = TableauMcpLlmPlanner(llm_service=_FakeLLM(_query_plan_payload(tool_name="delete-datasource")))

    plan = await planner.plan(_request())

    assert plan.status == "invalid_output"
    assert plan.error_code == "TABLEAU_MCP_PLANNER_TOOL_FORBIDDEN"
    assert plan.is_executable is False
    assert plan.raw["detail"]["tool_name"] == "delete-datasource"


@pytest.mark.asyncio
async def test_planner_rejects_invalid_output_contract():
    payload = _query_plan_payload()
    payload.pop("needs_clarification")
    planner = TableauMcpLlmPlanner(llm_service=_FakeLLM(payload))

    plan = await planner.plan(_request())

    assert plan.status == "invalid_output"
    assert plan.error_code == "TABLEAU_MCP_PLANNER_CONTRACT_MISSING"
    assert plan.raw["detail"]["missing"] == ["needs_clarification"]


@pytest.mark.parametrize(
    ("missing_part", "expected_code", "expected_missing"),
    [
        ("tool_name", "TABLEAU_MCP_PLANNER_CONTRACT_MISSING", ["tool_name"]),
        ("args", "TABLEAU_MCP_PLANNER_CONTRACT_MISSING", ["args"]),
        ("args.datasourceLuid", "TABLEAU_MCP_PLANNER_EXECUTABLE_ARGS_MISSING", ["args.datasourceLuid"]),
        ("args.query.fields", "TABLEAU_MCP_PLANNER_EXECUTABLE_ARGS_MISSING", ["args.query.fields"]),
    ],
)
def test_parse_rejects_missing_core_executable_fields(missing_part, expected_code, expected_missing):
    payload = _query_plan_payload()
    if missing_part == "tool_name":
        payload.pop("tool_name")
    elif missing_part == "args":
        payload.pop("args")
    elif missing_part == "args.datasourceLuid":
        payload["args"].pop("datasourceLuid")
    elif missing_part == "args.query.fields":
        payload["args"]["query"].pop("fields")

    with pytest.raises(TableauMcpPlannerError) as exc_info:
        parse_tableau_mcp_planner_output(json.dumps(payload, ensure_ascii=False))

    assert exc_info.value.code == expected_code
    assert exc_info.value.detail["missing"] == expected_missing


def test_parse_rejects_queryspec_shaped_output():
    content = json.dumps(
        {
            "tool_name": "query-datasource",
            "args": {},
            "reason": "legacy shape",
            "confidence": 0.9,
            "needs_clarification": False,
            "clarification": None,
            "queryspec": {"intent": "aggregate", "operator": "group_by"},
        }
    )

    with pytest.raises(Exception) as exc_info:
        parse_tableau_mcp_planner_output(content)

    assert getattr(exc_info.value, "code", None) == "TABLEAU_MCP_PLANNER_QUERYSPEC_FORBIDDEN"
