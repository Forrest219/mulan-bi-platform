from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from services.help_agent.tools.agent_run import diagnose_agent_run
from services.help_agent.tools.connection import diagnose_connection
from services.help_agent.tools.page_context import get_page_context_hint
from services.help_agent.tools.skill import diagnose_skill, list_enabled_skills
from services.help_agent.tools.task import diagnose_task_run
from services.data_agent.models import BiAgentRun, BiAgentStep
from services.skills.models import AgentSkill, AgentSkillVersion
from services.tableau.models import TableauConnection, TableauSyncLog
from services.tasks.models import BiTaskRun


class QueryMock:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class DBMock:
    def __init__(self, rows_by_model):
        self.rows_by_model = rows_by_model

    def query(self, model):
        return QueryMock(self.rows_by_model.get(model, []))


def test_diagnose_agent_run_reports_slow_thinking_and_related_entities():
    run_id = uuid.uuid4()
    started = datetime(2026, 5, 13, 10, 0, 0)
    run = SimpleNamespace(
        id=run_id,
        conversation_id=uuid.uuid4(),
        user_id=7,
        question="why slow",
        connection_id=12,
        status="completed",
        error_code=None,
        tools_used=["schema_tool"],
        response_type="text",
        execution_time_ms=100_000,
        created_at=started,
        completed_at=started + timedelta(seconds=100),
    )
    steps = [
        SimpleNamespace(
            id=1,
            run_id=run_id,
            step_number=1,
            step_type="thinking",
            tool_name=None,
            tool_result_summary=None,
            content="thinking",
            execution_time_ms=70_000,
            created_at=started,
        ),
        SimpleNamespace(
            id=2,
            run_id=run_id,
            step_number=2,
            step_type="tool_result",
            tool_name="schema_tool",
            tool_result_summary="ok",
            content=None,
            execution_time_ms=1_000,
            created_at=started + timedelta(seconds=70),
        ),
    ]
    result = diagnose_agent_run(DBMock({BiAgentRun: [run], BiAgentStep: steps}), {"id": 7, "role": "user"}, str(run_id))

    assert result["snapshot_at"]
    codes = {item["code"] for item in result["findings"]}
    assert "SLOW_STEP" in codes
    assert "LONG_THINKING" in codes
    assert {"type": "connection", "id": 12, "reason": "run.connection_id"} in result["related_entities"]
    assert any(entity["type"] == "skill" and entity["id"] == "schema" for entity in result["related_entities"])


def test_diagnose_agent_run_denies_non_owner():
    run = SimpleNamespace(id=uuid.uuid4(), user_id=9)
    result = diagnose_agent_run(DBMock({BiAgentRun: [run]}), {"id": 7, "role": "user"}, str(run.id))
    assert result["findings"][0]["code"] == "HLP_003"
    assert result["snapshot_at"]


def test_diagnose_task_run_prefers_structured_error():
    run = SimpleNamespace(
        id=5,
        task_name="sync",
        task_label="Sync",
        trigger_type="manual",
        status="failed",
        started_at=None,
        finished_at=None,
        duration_ms=301_000,
        retry_count=1,
        parent_run_id=None,
        triggered_by=1,
        result_summary={"password": "plain"},
        error_message="legacy should not win",
        structured_error={"code": "TASK_TIMEOUT", "message": "timeout"},
    )
    result = diagnose_task_run(DBMock({BiTaskRun: [run]}), {"id": 1, "role": "data_admin"}, 5)
    assert result["facts"]["task_run"]["error"]["source"] == "structured_error"
    assert result["facts"]["task_run"]["result_summary"]["password"] == "******"
    assert {"TASK_FAILED", "TASK_RETRIED", "TASK_SLOW"} <= {item["code"] for item in result["findings"]}


def test_diagnose_task_run_requires_admin_role():
    result = diagnose_task_run(DBMock({}), {"id": 1, "role": "analyst"}, 5)
    assert result["findings"][0]["code"] == "HLP_003"


def test_diagnose_connection_redacts_secret_fields():
    conn = SimpleNamespace(
        id=3,
        name="prod",
        server_url="https://tableau.example",
        site="main",
        api_version="3.21",
        connection_type="mcp",
        token_name="pat-name",
        token_encrypted="must-not-return",
        owner_id=9,
        is_active=True,
        auto_sync_enabled=True,
        schedule_id=4,
        last_test_at=None,
        last_test_success=False,
        last_test_message="token=abcdef123456",
        last_sync_at=None,
        last_sync_duration_sec=None,
        sync_status="failed",
        mcp_direct_enabled=False,
        mcp_server_url=None,
        created_at=None,
        updated_at=None,
    )
    sync = SimpleNamespace(
        id=2,
        trigger_type="manual",
        started_at=None,
        finished_at=None,
        status="failed",
        workbooks_synced=0,
        views_synced=0,
        dashboards_synced=0,
        datasources_synced=0,
        assets_deleted=0,
        error_message="password=secret",
    )
    result = diagnose_connection(
        DBMock({TableauConnection: [conn], TableauSyncLog: [sync]}),
        {"id": 1, "role": "admin"},
        connection_id=3,
    )
    assert "token_encrypted" not in result["facts"]["connection"]
    assert result["facts"]["connection"]["last_test_message"] == "token=abcd******3456"
    assert result["facts"]["latest_sync"]["error_message"] == "password=******"


def test_diagnose_skill_requires_data_admin_and_reports_active_version():
    skill_id = uuid.uuid4()
    skill = SimpleNamespace(
        id=skill_id,
        skill_key="schema",
        name="Schema",
        description="Schema inventory",
        category="data",
        is_enabled=True,
        created_by=1,
        created_at=None,
        updated_at=None,
    )
    version = SimpleNamespace(
        id=uuid.uuid4(),
        skill_id=skill_id,
        version_number="v1",
        endpoint_type="static",
        code_ref="SchemaTool",
        is_active=True,
        created_at=None,
    )
    denied = diagnose_skill(DBMock({}), {"id": 2, "role": "user"}, "schema")
    allowed = diagnose_skill(DBMock({AgentSkill: [skill], AgentSkillVersion: [version]}), {"id": 1, "role": "admin"}, "schema")
    assert denied["findings"][0]["code"] == "HLP_003"
    assert allowed["facts"]["active_version"]["version_number"] == "v1"
    assert allowed["snapshot_at"]


def test_list_enabled_skills_reports_active_versions():
    schema_id = uuid.uuid4()
    query_id = uuid.uuid4()
    skills = [
        SimpleNamespace(
            id=schema_id,
            skill_key="schema",
            name="Schema",
            description="Schema inventory",
            category="data",
            is_enabled=True,
            updated_at=None,
        ),
        SimpleNamespace(
            id=query_id,
            skill_key="query",
            name="Query",
            description="Query executor",
            category="query",
            is_enabled=True,
            updated_at=None,
        ),
    ]
    versions = [
        SimpleNamespace(
            id=uuid.uuid4(),
            skill_id=schema_id,
            version_number="v2",
            endpoint_type="static",
            code_ref="SchemaTool",
            is_active=True,
            created_at=None,
        )
    ]

    result = list_enabled_skills(
        DBMock({AgentSkill: skills, AgentSkillVersion: versions}),
        {"id": 1, "role": "data_admin"},
    )

    assert result["tool"] == "list_enabled_skills"
    assert result["facts"]["total"] == 2
    assert result["facts"]["skills"][0]["skill_key"] == "schema"
    assert result["facts"]["skills"][0]["active_version"]["version_number"] == "v2"


def test_get_page_context_hint_returns_weak_or_strong_candidates():
    result = get_page_context_hint(
        "/admin/agent-monitor",
        {"entry_point": "inline_panel", "run_id": "run-1"},
    )
    assert result["facts"]["title"] == "Agent Monitor"
    assert result["facts"]["hint_strength"] == "strong"
    assert result["related_entities"] == [{"type": "agent_run", "id": "run-1", "reason": "page_context.run_id"}]
