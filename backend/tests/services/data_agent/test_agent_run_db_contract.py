"""Database contract tests for Data Agent run observability."""

from __future__ import annotations

from services.auth.models import User
from services.data_agent.models import AgentConversation, AgentConversationMessage, BiAgentRun, BiAgentStep


STANDARD_LONG_ERROR_CODE = "ROUTER_CLARIFY_REQUIRED"


def _column_length(model, field_name: str) -> int | None:
    return model.__table__.columns[field_name].type.length


def test_bi_agent_run_error_code_contract_allows_standard_router_codes() -> None:
    assert len(STANDARD_LONG_ERROR_CODE) > 16
    assert _column_length(BiAgentRun, "error_code") == 128


def test_related_short_observability_fields_remain_scoped() -> None:
    assert _column_length(BiAgentRun, "status") == 16
    assert _column_length(BiAgentRun, "response_type") == 16
    assert _column_length(AgentConversationMessage, "response_type") == 16
    assert _column_length(BiAgentStep, "step_type") == 16


def test_bi_agent_run_persists_standard_long_error_code(db_session) -> None:
    user = db_session.query(User).filter(User.username == "admin").one()
    conversation = AgentConversation(
        user_id=user.id,
        title="DB contract",
        status="active",
    )
    db_session.add(conversation)
    db_session.flush()

    run = BiAgentRun(
        conversation_id=conversation.id,
        user_id=user.id,
        question="What dashboards are available?",
        status="failed",
        error_code=STANDARD_LONG_ERROR_CODE,
        response_type="fallback",
    )
    db_session.add(run)
    db_session.commit()

    db_session.expire_all()
    persisted = db_session.get(BiAgentRun, run.id)

    assert persisted is not None
    assert persisted.error_code == STANDARD_LONG_ERROR_CODE
