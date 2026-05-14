import asyncio
import time

import pytest

from services.help_agent.schemas import HelpAgentRequest
from services.help_agent.service import HelpAgentService

pytestmark = pytest.mark.skip_db


class FakeRegistry:
    def __init__(self):
        self.started_at = {}

    async def execute(self, tool_name, params, context):
        del context
        self.started_at[tool_name] = time.monotonic()
        await asyncio.sleep(0.01)
        if tool_name == "diagnose_agent_run":
            return {
                "tool": tool_name,
                "snapshot_at": "2026-05-13T18:30:01+08:00",
                "target": {"type": "agent_run", "id": params["run_id"]},
                "facts": {"status": "failed"},
                "findings": [{"severity": "warning", "code": "RUN_FAILED", "message": "run 执行失败。"}],
                "recommendations": [],
                "related_entities": [
                    {"type": "connection", "id": 1, "reason": "run.connection_id"},
                    {"type": "skill", "id": "schema", "reason": "run.tools_used 包含 schema"},
                ],
            }
        if tool_name == "diagnose_connection":
            await asyncio.sleep(0.05)
            return {
                "tool": tool_name,
                "snapshot_at": "2026-05-13T18:30:02+08:00",
                "target": {"type": "connection", "id": params["connection_id"]},
                "facts": {"active": False},
                "findings": [{"severity": "error", "code": "AUTH_ERROR", "message": "连接认证失败。"}],
                "recommendations": [{"priority": "P0", "action": "检查连接凭据是否过期。"}],
                "related_entities": [],
            }
        if tool_name == "diagnose_skill":
            await asyncio.sleep(0.05)
            raise RuntimeError("skill service unavailable")
        raise AssertionError(tool_name)


class TimeoutRegistry:
    async def execute(self, tool_name, params, context):
        del context
        if tool_name == "diagnose_agent_run":
            return {
                "tool": tool_name,
                "snapshot_at": "2026-05-13T18:30:01+08:00",
                "target": {"type": "agent_run", "id": params["run_id"]},
                "facts": {"status": "failed"},
                "findings": [{"severity": "warning", "code": "RUN_FAILED", "message": "run 执行失败。"}],
                "recommendations": [],
                "related_entities": [
                    {"type": "connection", "id": 1, "reason": "run.connection_id"},
                    {"type": "skill", "id": "schema", "reason": "run.tools_used 包含 schema"},
                    {"type": "task_run", "id": 9, "reason": "run.related_task"},
                ],
            }
        if tool_name == "diagnose_connection":
            await asyncio.sleep(0.01)
            return {
                "tool": tool_name,
                "snapshot_at": "2026-05-13T18:30:02+08:00",
                "target": {"type": "connection", "id": params["connection_id"]},
                "facts": {},
                "findings": [],
                "recommendations": [],
                "related_entities": [],
            }
        if tool_name == "diagnose_skill":
            await asyncio.sleep(0.12)
            return {
                "tool": tool_name,
                "snapshot_at": "2026-05-13T18:30:03+08:00",
                "target": {"type": "skill", "id": params["skill_key"]},
                "facts": {},
                "findings": [],
                "recommendations": [],
                "related_entities": [],
            }
        if tool_name == "diagnose_task_run":
            await asyncio.sleep(1)
            return {
                "tool": tool_name,
                "snapshot_at": "2026-05-13T18:30:04+08:00",
                "target": {"type": "task_run", "id": params["task_run_id"]},
                "facts": {},
                "findings": [],
                "recommendations": [],
                "related_entities": [],
            }
        raise AssertionError(tool_name)


class SkillInventoryRegistry:
    async def execute(self, tool_name, params, context):
        del params, context
        if tool_name == "list_enabled_skills":
            return {
                "tool": tool_name,
                "snapshot_at": "2026-05-14T19:36:37+08:00",
                "target": {"type": "skill_inventory", "id": "enabled"},
                "facts": {
                    "total": 2,
                    "skills": [
                        {
                            "skill_key": "schema",
                            "name": "Schema",
                            "category": "data",
                            "active_version": {"version_number": "v2"},
                        },
                        {
                            "skill_key": "query",
                            "name": "Query",
                            "category": "query",
                            "active_version": {"version_number": "v1"},
                        },
                    ],
                },
                "findings": [],
                "recommendations": [],
                "related_entities": [],
            }
        raise AssertionError(tool_name)


async def _collect(service, request):
    return [event async for event in service.stream(request, current_user={"id": 1, "role": "admin"})]


async def test_stream_keeps_partial_facts_when_parallel_related_tool_fails():
    registry = FakeRegistry()
    service = HelpAgentService(tool_registry=registry)
    request = HelpAgentRequest.model_validate(
        {
            "question": "这个为什么失败？",
            "entry_point": "inline_panel",
            "page_context": {"selection": {"run_id": "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"}},
        }
    )

    events = await _collect(service, request)

    assert [event["type"] for event in events if not event["type"].startswith("_")][0:2] == ["metadata", "thinking"]
    assert any(event["type"] == "tool_result" and event["tool_name"] == "diagnose_connection" for event in events)
    assert any(
        event["type"] == "diagnostic_progress"
        and str(event["status"]) == "failed"
        and event["step_key"] == "diagnose_skill:schema"
        for event in events
    )
    done = next(event for event in events if event["type"] == "done")
    assert done["response_data"]["trace"]["partial"] is True
    assert any(item["target"]["type"] == "connection" for item in done["response_data"]["diagnostics"])
    assert len([event for event in events if event["type"] == "tool_call"]) == 3
    assert abs(registry.started_at["diagnose_connection"] - registry.started_at["diagnose_skill"]) < 0.03


async def test_stream_does_not_route_global_unrelated_selection():
    service = HelpAgentService(tool_registry=FakeRegistry())
    events = await _collect(
        service,
        {
            "question": "怎么连接 Tableau？",
            "entry_point": "global_drawer",
            "page_context": {"selection": {"run_id": "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"}},
        },
    )

    assert not [event for event in events if event["type"] == "tool_call"]
    done = next(event for event in events if event["type"] == "done")
    assert "缺少可读取的诊断对象" in done["answer"]


async def test_stream_lists_enabled_skills_for_skill_inventory_question():
    service = HelpAgentService(tool_registry=SkillInventoryRegistry())
    events = await _collect(
        service,
        {
            "question": "哪些 skill 当前已启用？",
            "entry_point": "global_drawer",
            "page_context": {"path": "/agents/skills"},
        },
    )

    assert any(event["type"] == "tool_call" and event["tool_name"] == "list_enabled_skills" for event in events)
    done = next(event for event in events if event["type"] == "done")
    assert "当前已启用 2 个 skill" in done["answer"]
    assert "`schema`" in done["answer"]
    assert done["response_data"]["trace"]["intent"] == "skill_inventory"


async def test_parallel_tool_timeout_preserves_completed_results():
    service = HelpAgentService(tool_registry=TimeoutRegistry(), tool_timeout_seconds=0.2)
    events = await _collect(
        service,
        {
            "question": "为什么失败？",
            "entry_point": "inline_panel",
            "page_context": {"selection": {"run_id": "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"}},
        },
    )

    progress = [
        (event["step_key"], str(event["status"]))
        for event in events
        if event["type"] == "diagnostic_progress" and str(event["status"]) in {"completed", "failed"}
    ]
    assert ("diagnose_connection:1", "completed") in progress
    assert ("diagnose_skill:schema", "completed") in progress
    assert ("diagnose_task_run:9", "failed") in progress
    done = next(event for event in events if event["type"] == "done")
    targets = {item["target"]["type"] for item in done["response_data"]["diagnostics"]}
    assert {"agent_run", "connection", "skill", "task_run"}.issubset(targets)
    task_diag = next(item for item in done["response_data"]["diagnostics"] if item["target"]["type"] == "task_run")
    assert task_diag["findings"][0]["code"] == "TOOL_FAILED"


async def test_prompt_redacts_question_and_page_context_secret():
    class CapturingLLM:
        def __init__(self):
            self.prompt = ""

        async def stream_answer(self, prompt, facts):
            del facts
            self.prompt = prompt
            yield "ok"

    llm = CapturingLLM()
    service = HelpAgentService(tool_registry=FakeRegistry(), llm_adapter=llm)
    events = await _collect(
        service,
        {
            "question": "请诊断 token=abcd1234secret5678",
            "entry_point": "inline_panel",
            "page_context": {
                "selection": {"run_id": "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"},
                "visible_state": {"password": "plain-secret"},
            },
        },
    )

    assert "abcd1234secret5678" not in llm.prompt
    assert "plain-secret" not in llm.prompt
    assert "plain-secret" not in str(events)
