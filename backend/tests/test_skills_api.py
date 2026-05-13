from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.core.dependencies as auth_deps
from app.api import skills as skills_api
from app.core.database import get_db
from services.skills import service as skill_svc
from services.skills.models import AgentSkill, AgentSkillVersion


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
        },
    }


def test_registered_tools_api_marks_configured_and_does_not_mutate(
    db_session, monkeypatch
):
    db_session.query(AgentSkill).filter(AgentSkill.skill_key == "schema").delete(
        synchronize_session=False
    )
    created = skill_svc.create_skill(
        db_session,
        skill_key="schema",
        name="Schema API test",
        description="admin description",
        category="query",
        initial_version={
            "description": "schema v1 prompt",
            "input_schema": _schema(),
            "endpoint_type": "static",
            "change_notes": "test",
        },
        created_by_id=1,
    )
    db_session.flush()

    skill_count_before = db_session.query(AgentSkill).count()
    version_count_before = db_session.query(AgentSkillVersion).count()

    app = FastAPI()
    app.include_router(skills_api.router)

    def _db_override():
        yield db_session

    def _admin_override(*_args, **_kwargs):
        return {"id": 1, "username": "admin", "role": "admin"}

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[skills_api.get_db] = _db_override
    app.dependency_overrides[auth_deps.get_db] = _db_override
    monkeypatch.setattr(auth_deps, "get_current_user", _admin_override)

    with TestClient(app) as client:
        resp = client.get("/api/skills/registered-tools")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    schema_tool = next(tool for tool in data["tools"] if tool["skill_key"] == "schema")

    assert data["total"] == len(skill_svc.STATIC_SKILL_KEYS)
    assert schema_tool["configured"] is True
    assert schema_tool["skill_id"] == created["id"]
    assert schema_tool["active_version_id"] == created["active_version"]["id"]
    assert schema_tool["active_version_number"] == "v1"
    assert db_session.query(AgentSkill).count() == skill_count_before
    assert db_session.query(AgentSkillVersion).count() == version_count_before
