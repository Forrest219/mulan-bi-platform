import pytest

from services.auth.models import User
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
