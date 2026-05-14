import pytest

from services.auth.models import User
from services.logs.models import OperationLog
from services.skills import service as skill_svc
from services.skills.models import AgentSkill, AgentSkillVersion


TEST_KEYS = ("schema", "query", "metrics", "chart")


@pytest.fixture(autouse=True)
def clear_dispatch_cache():
    skill_svc._dispatch_cache.clear()
    yield
    skill_svc._dispatch_cache.clear()


@pytest.fixture
def admin_user(db_session):
    return db_session.query(User).filter(User.username == "admin").first()


@pytest.fixture
def clean_skills(db_session):
    db_session.query(AgentSkill).filter(AgentSkill.skill_key.in_(TEST_KEYS)).delete(
        synchronize_session=False
    )
    db_session.flush()


def _schema(required_name: str = "question") -> dict:
    return {
        "type": "object",
        "properties": {
            required_name: {"type": "string"},
        },
    }


def _create_skill(db_session, key: str, *, created_by_id: int | None = None):
    return skill_svc.create_skill(
        db_session,
        skill_key=key,
        name=f"{key} tool",
        description=f"{key} admin description",
        category="general",
        initial_version={
            "description": f"{key} v1 prompt",
            "input_schema": _schema(),
            "endpoint_type": "static",
            "change_notes": "test",
        },
        created_by_id=created_by_id,
    )


def test_get_active_skill_version_enabled_disabled_unconfigured_and_no_active(
    db_session, clean_skills
):
    enabled = _create_skill(db_session, "schema")
    disabled = _create_skill(db_session, "query")
    no_active = _create_skill(db_session, "metrics")

    disabled_skill = db_session.query(AgentSkill).filter_by(skill_key="query").one()
    disabled_skill.is_enabled = False

    db_session.query(AgentSkillVersion).filter(
        AgentSkillVersion.skill_id == no_active["id"]
    ).update({"is_active": False}, synchronize_session=False)
    db_session.flush()

    enabled_info = skill_svc.get_active_skill_version(db_session, "schema")
    assert enabled_info == {
        "is_configured": True,
        "is_enabled": True,
        "version_id": enabled["active_version"]["id"],
        "version_number": "v1",
        "description": "schema v1 prompt",
        "input_schema": _schema(),
    }

    disabled_info = skill_svc.get_active_skill_version(db_session, "query")
    assert disabled_info["is_configured"] is True
    assert disabled_info["is_enabled"] is False
    assert disabled_info["version_number"] == "v1"

    unconfigured_info = skill_svc.get_active_skill_version(db_session, "chart")
    assert unconfigured_info["is_configured"] is False
    assert unconfigured_info["version_id"] is None

    no_active_info = skill_svc.get_active_skill_version(db_session, "metrics")
    assert no_active_info == {
        "is_configured": True,
        "is_enabled": True,
        "version_id": None,
        "version_number": None,
        "description": None,
        "input_schema": None,
    }


def test_dispatch_returns_only_enabled_skills_with_active_versions(db_session, clean_skills):
    _create_skill(db_session, "schema")
    _create_skill(db_session, "query")
    no_active = _create_skill(db_session, "metrics")

    disabled_skill = db_session.query(AgentSkill).filter_by(skill_key="query").one()
    disabled_skill.is_enabled = False
    db_session.query(AgentSkillVersion).filter(
        AgentSkillVersion.skill_id == no_active["id"]
    ).update({"is_active": False}, synchronize_session=False)
    db_session.flush()

    result = skill_svc.get_dispatch(db_session)

    assert [tool["skill_key"] for tool in result["tools"]] == ["schema"]
    assert result["total"] == 1


def test_create_rejects_http_endpoint_type(db_session, clean_skills):
    with pytest.raises(ValueError) as exc:
        skill_svc.create_skill(
            db_session,
            skill_key="schema",
            name="Schema",
            description=None,
            category="general",
            initial_version={
                "description": "Schema prompt",
                "input_schema": _schema(),
                "endpoint_type": "http",
            },
        )

    assert str(exc.value).startswith("SKILLS_005:")


def test_create_rejects_non_whitelisted_skill_key(db_session, clean_skills):
    with pytest.raises(ValueError) as exc:
        skill_svc.create_skill(
            db_session,
            skill_key="not_registered",
            name="Not registered",
            description=None,
            category="general",
            initial_version={
                "description": "Prompt",
                "input_schema": _schema(),
                "endpoint_type": "static",
            },
        )

    assert str(exc.value).startswith("SKILLS_006:")


def test_publish_and_rollback_invalidate_dispatch_cache_by_behavior(
    db_session, clean_skills
):
    created = _create_skill(db_session, "query")

    first = skill_svc.get_dispatch(db_session, skill_keys="query")
    assert first["tools"][0]["description"] == "query v1 prompt"

    published = skill_svc.publish_version(
        db_session,
        skill_id=created["id"],
        description="query v2 prompt",
        input_schema=_schema("sql"),
        endpoint_type="static",
        change_notes="publish v2",
    )

    after_publish = skill_svc.get_dispatch(db_session, skill_keys="query")
    assert after_publish["tools"][0]["description"] == "query v2 prompt"
    assert after_publish["tools"][0]["version_id"] == published["id"]

    rollback = skill_svc.rollback_version(
        db_session,
        skill_id=created["id"],
        version_id=created["active_version"]["id"],
    )

    after_rollback = skill_svc.get_dispatch(db_session, skill_keys="query")
    assert rollback["rolled_back_to"] == "v1"
    assert after_rollback["tools"][0]["description"] == "query v1 prompt"
    assert after_rollback["tools"][0]["version_id"] == created["active_version"]["id"]


def test_patch_is_enabled_invalidates_dispatch_cache_by_behavior(db_session, clean_skills):
    created = _create_skill(db_session, "schema")

    before = skill_svc.get_dispatch(db_session, skill_keys="schema")
    assert before["tools"][0]["skill_key"] == "schema"

    skill_svc.patch_skill(db_session, skill_id=created["id"], is_enabled=False)
    after_disable = skill_svc.get_dispatch(db_session, skill_keys="schema")
    assert after_disable["tools"] == []

    skill_svc.patch_skill(db_session, skill_id=created["id"], is_enabled=True)
    after_enable = skill_svc.get_dispatch(db_session, skill_keys="schema")
    assert after_enable["tools"][0]["skill_key"] == "schema"


def test_get_skill_versions_include_created_by_name_without_breaking_created_by(
    db_session, clean_skills, admin_user
):
    created = _create_skill(db_session, "schema", created_by_id=admin_user.id)

    detail = skill_svc.get_skill(db_session, skill_id=created["id"])

    assert detail["versions"][0]["created_by"] == admin_user.id
    assert detail["versions"][0]["created_by_name"] == admin_user.display_name


def test_registered_tools_marks_configured_tool_and_is_read_only(
    db_session, clean_skills
):
    created = _create_skill(db_session, "schema")
    schema_skill_count_before = (
        db_session.query(AgentSkill).filter(AgentSkill.skill_key == "schema").count()
    )
    schema_version_count_before = (
        db_session.query(AgentSkillVersion)
        .filter(AgentSkillVersion.skill_id == created["id"])
        .count()
    )

    result = skill_svc.list_registered_tools(db_session)

    schema_tool = next(tool for tool in result["tools"] if tool["skill_key"] == "schema")
    assert result["total"] == len(skill_svc.STATIC_SKILL_KEYS)
    assert schema_tool["configured"] is True
    assert schema_tool["skill_id"] == created["id"]
    assert schema_tool["active_version_id"] == created["active_version"]["id"]
    assert schema_tool["active_version_number"] == "v1"

    chart_tool = next(tool for tool in result["tools"] if tool["skill_key"] == "chart")
    assert chart_tool["configured"] is False
    assert chart_tool["skill_id"] is None
    assert chart_tool["active_version_id"] is None

    assert (
        db_session.query(AgentSkill).filter(AgentSkill.skill_key == "schema").count()
        == schema_skill_count_before
    )
    assert (
        db_session.query(AgentSkillVersion)
        .filter(AgentSkillVersion.skill_id == created["id"])
        .count()
        == schema_version_count_before
    )


def test_skill_mutations_write_operation_logs(db_session, clean_skills, admin_user):
    created = _create_skill(db_session, "schema", created_by_id=admin_user.id)
    published = skill_svc.publish_version(
        db_session,
        skill_id=created["id"],
        description="schema v2 prompt",
        input_schema=_schema("table_name"),
        endpoint_type="static",
        change_notes="publish v2",
        created_by_id=admin_user.id,
    )
    skill_svc.patch_skill(
        db_session,
        skill_id=created["id"],
        name="Schema updated",
        updated_by_id=admin_user.id,
    )
    skill_svc.rollback_version(
        db_session,
        skill_id=created["id"],
        version_id=created["active_version"]["id"],
        user_id=admin_user.id,
    )

    logs = (
        db_session.query(OperationLog)
        .filter(
            OperationLog.operation_type.in_(
                [
                    "skill_create",
                    "skill_update",
                    "skill_version_publish",
                    "skill_version_rollback",
                ]
            ),
            OperationLog.target.like("skill:schema%"),
        )
        .all()
    )
    by_type = {log.operation_type: log for log in logs}

    assert by_type["skill_create"].target == "skill:schema"
    assert by_type["skill_update"].target == "skill:schema"
    assert by_type["skill_version_publish"].target == "skill:schema:version:v2"
    assert by_type["skill_version_rollback"].target == "skill:schema:version:v1"
    assert by_type["skill_version_publish"].details["to_version"] == published["version_number"]
    assert all(log.operator_id == admin_user.id for log in by_type.values())


def test_emit_skill_event_failure_does_not_touch_caller_session(monkeypatch):
    class CallerSession:
        rollback_called = False
        close_called = False

        def rollback(self):
            self.rollback_called = True

        def close(self):
            self.close_called = True

    class AuditSession:
        rollback_called = False
        close_called = False

        def rollback(self):
            self.rollback_called = True

        def close(self):
            self.close_called = True

    caller_session = CallerSession()
    audit_session = AuditSession()

    from app.core import database as core_database
    from services.events import event_service

    monkeypatch.setattr(core_database, "SessionLocal", lambda: audit_session)

    def fail_emit_event(**kwargs):
        assert kwargs["db"] is audit_session
        raise RuntimeError("bi_events.extra_data missing")

    monkeypatch.setattr(event_service, "emit_event", fail_emit_event)

    skill_svc._emit_skill_event(
        caller_session,
        skill_key="schema",
        from_version="v1",
        to_version="v2",
        action="publish",
        actor_id=1,
    )

    assert caller_session.rollback_called is False
    assert caller_session.close_called is False
    assert audit_session.rollback_called is True
    assert audit_session.close_called is True
