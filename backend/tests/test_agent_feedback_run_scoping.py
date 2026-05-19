import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.api.agent import get_agent_feedback, submit_agent_feedback_v2
from services.data_agent.models import (
    AgentConversation,
    AgentConversationMessage,
    BiAgentFeedback,
    BiAgentRun,
)


def _current_user():
    return {"id": 1001, "username": "analyst", "role": "analyst", "tenant_id": None}


def _ensure_message_feedback_table(db_session):
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS message_feedback (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username VARCHAR(128),
                conversation_id VARCHAR(64),
                message_index INTEGER,
                question TEXT,
                answer_summary TEXT,
                rating VARCHAR(16) NOT NULL,
                created_at TIMESTAMP
            )
            """
        )
    )
    db_session.commit()


def _seed_two_run_conversation(db_session):
    base_time = datetime(2026, 5, 18, 12, 0, 0)
    conversation_id = uuid.uuid4()
    first_run_id = uuid.uuid4()
    second_run_id = uuid.uuid4()

    db_session.add(
        AgentConversation(
            id=conversation_id,
            user_id=1001,
            title="反馈隔离",
            connection_id=4,
            status="active",
            created_at=base_time,
            updated_at=base_time,
        )
    )
    db_session.add_all(
        [
            AgentConversationMessage(
                conversation_id=conversation_id,
                role="user",
                content="你有哪些数据源？",
                created_at=base_time,
            ),
            AgentConversationMessage(
                conversation_id=conversation_id,
                role="assistant",
                content="default（1）",
                response_type="schema_inventory",
                created_at=base_time + timedelta(seconds=1),
            ),
            AgentConversationMessage(
                conversation_id=conversation_id,
                role="user",
                content="介绍订单数据源",
                created_at=base_time + timedelta(seconds=2),
            ),
            AgentConversationMessage(
                conversation_id=conversation_id,
                role="assistant",
                content="Samples（1）",
                response_type="schema_inventory",
                created_at=base_time + timedelta(seconds=3),
            ),
        ]
    )
    db_session.add_all(
        [
            BiAgentRun(
                id=first_run_id,
                conversation_id=conversation_id,
                user_id=1001,
                question="你有哪些数据源？",
                connection_id=4,
                status="completed",
                response_type="schema_inventory",
                created_at=base_time + timedelta(milliseconds=500),
                completed_at=base_time + timedelta(seconds=1),
            ),
            BiAgentRun(
                id=second_run_id,
                conversation_id=conversation_id,
                user_id=1001,
                question="介绍订单数据源",
                connection_id=4,
                status="completed",
                response_type="schema_inventory",
                created_at=base_time + timedelta(seconds=2, milliseconds=500),
                completed_at=base_time + timedelta(seconds=3),
            ),
        ]
    )
    db_session.commit()
    return conversation_id, first_run_id, second_run_id


def test_get_feedback_ignores_legacy_message_index_when_run_id_is_present(db_session):
    conversation_id, first_run_id, second_run_id = _seed_two_run_conversation(db_session)
    _ensure_message_feedback_table(db_session)
    db_session.execute(
        text(
            "INSERT INTO message_feedback "
            "(user_id, username, conversation_id, message_index, question, answer_summary, rating, created_at) "
            "VALUES (:user_id, :username, :conversation_id, :message_index, :question, :answer_summary, :rating, :created_at)"
        ),
        {
            "user_id": 1001,
            "username": "analyst",
            "conversation_id": str(conversation_id),
            "message_index": 1,
            "question": "你有哪些数据源？",
            "answer_summary": None,
            "rating": "up",
            "created_at": datetime(2026, 5, 18, 12, 1, 0),
        },
    )
    db_session.commit()

    first_response = get_agent_feedback(
        run_id=str(first_run_id),
        current_user=_current_user(),
        db=db_session,
    )
    second_response = get_agent_feedback(
        run_id=str(second_run_id),
        current_user=_current_user(),
        db=db_session,
    )

    assert first_response == {"rating": None}
    assert second_response == {"rating": None}


@pytest.mark.asyncio
async def test_feedback_v2_with_run_id_writes_only_run_scope(db_session):

    conversation_id, _first_run_id, second_run_id = _seed_two_run_conversation(db_session)
    _ensure_message_feedback_table(db_session)

    response = await submit_agent_feedback_v2(
        run_id=str(second_run_id),
        rating="down",
        conversation_id=str(conversation_id),
        message_index=1,
        question="介绍订单数据源",
        current_user=_current_user(),
        db=db_session,
    )
    get_response = get_agent_feedback(
        run_id=str(second_run_id),
        current_user=_current_user(),
        db=db_session,
    )

    assert response["status"] == "created"
    assert get_response == {"rating": "down"}

    run_feedback = (
        db_session.query(BiAgentFeedback)
        .filter(BiAgentFeedback.run_id == second_run_id, BiAgentFeedback.user_id == 1001)
        .one()
    )
    assert run_feedback.rating == "down"

    legacy_count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM message_feedback "
            "WHERE user_id = :user_id AND conversation_id = :conversation_id AND rating = :rating "
        ),
        {"user_id": 1001, "conversation_id": str(conversation_id), "rating": "down"},
    ).scalar()
    assert legacy_count == 0
