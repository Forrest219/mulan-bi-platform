import pytest

from services.help_agent.planner import HelpPlanner
from services.help_agent.schemas import EntryPoint
from services.help_agent.schemas import HelpAgentRequest

pytestmark = pytest.mark.skip_db


def test_global_drawer_does_not_route_unrelated_question_from_page_context():
    planner = HelpPlanner()
    request = HelpAgentRequest.model_validate(
        {
            "question": "怎么连接 Tableau？",
            "entry_point": "global_drawer",
            "page_context": {
                "path": "/agents/agent-monitor",
                "selection": {"run_id": "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"},
            },
        }
    )

    decision = planner.plan_initial(request)

    assert decision.intent == "general_help"
    assert decision.tool_calls == []


def test_global_drawer_uses_selection_only_for_related_question():
    planner = HelpPlanner()
    request = HelpAgentRequest.model_validate(
        {
            "question": "这个为什么失败？",
            "entry_point": "global_drawer",
            "page_context": {"selection": {"run_id": "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"}},
        }
    )

    decision = planner.plan_initial(request)

    assert decision.intent == "agent_run_diagnosis"
    assert decision.tool_calls[0].tool_name == "diagnose_agent_run"
    assert decision.tool_calls[0].params["run_id"] == "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"


def test_inline_panel_empty_question_defaults_to_selection():
    planner = HelpPlanner()
    request = HelpAgentRequest.model_validate(
        {
            "question": "",
            "entry_point": EntryPoint.inline_panel,
            "page_context": {"selection": {"run_id": "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"}},
        }
    )

    decision = planner.plan_initial(request)

    assert decision.intent == "agent_run_diagnosis"
    assert decision.tool_calls[0].tool_name == "diagnose_agent_run"


def test_inline_panel_unrelated_question_does_not_force_selection():
    planner = HelpPlanner()
    request = HelpAgentRequest.model_validate(
        {
            "question": "怎么连接 Tableau？",
            "entry_point": "inline_panel",
            "page_context": {"selection": {"run_id": "a64eecc6-9e32-4b97-b9ee-f8f6e5270c17"}},
        }
    )

    decision = planner.plan_initial(request)

    assert decision.intent == "general_help"
    assert decision.tool_calls == []
    assert decision.conflict_with_selection is True
    assert "当前选中" in decision.user_message_hint


def test_skill_inventory_question_routes_to_enabled_skill_list():
    planner = HelpPlanner()
    request = HelpAgentRequest.model_validate(
        {
            "question": "哪些 skill 当前已启用？",
            "entry_point": "global_drawer",
            "page_context": {"path": "/agents/skills"},
        }
    )

    decision = planner.plan_initial(request)

    assert decision.intent == "skill_inventory"
    assert decision.tool_calls[0].tool_name == "list_enabled_skills"
    assert decision.tool_calls[0].params["limit"] == 100


def test_related_entities_are_deduped_and_limited():
    planner = HelpPlanner(max_tool_calls=4)
    seen = {"diagnose_agent_run:agent_run:run-1"}
    related = [
        {"type": "connection", "id": 1, "reason": "run.connection_id"},
        {"type": "connection", "id": 1, "reason": "duplicate"},
        {"type": "skill", "id": "schema", "reason": "tools_used"},
        {"type": "skill", "id": "query", "reason": "tools_used"},
    ]

    plans = planner.plan_related(related, seen, remaining_slots=2, depth=1)

    assert [plan.tool_name for plan in plans] == ["diagnose_connection", "diagnose_skill"]
    assert [plan.target_id for plan in plans] == ["1", "schema"]
