"""Data Agent Runner — observability wrapper around ReActEngine.run()

Iterates engine events, persists BiAgentRun / BiAgentStep records, and
yields raw AgentEvent objects (SSE serialisation is the caller's job).

No web framework dependency: only SQLAlchemy + pure Python.
"""

import logging
import time
import uuid as uuid_lib
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Optional

from sqlalchemy.orm import Session

from .engine import ReActEngine
from .models import BiAgentRun, BiAgentStep
from .response import AgentEvent
from .session import AgentSession, SessionManager
from .tool_base import ToolContext

logger = logging.getLogger(__name__)


async def run_agent(
    engine: ReActEngine,
    context: ToolContext,
    session_mgr: SessionManager,
    session: AgentSession,
    question: str,
    trace_id: str,
    current_user: Dict,
    db: Session,
    connection_id: Optional[int] = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Execute the ReAct engine with full observability.

    Yields:
        AgentEvent objects (metadata, thinking, tool_call, tool_result,
        answer, error).  The caller is responsible for serialising them
        to SSE or any other transport format.
    """
    conversation_id_str = str(session.conversation_id)
    total_start = time.time()
    tools_used: List[str] = []
    steps_count = 0
    last_tool_result: Dict = {}
    run_id: Optional[uuid_lib.UUID] = None

    try:
        # Create bi_agent_runs record
        run = BiAgentRun(
            conversation_id=uuid_lib.UUID(conversation_id_str),
            user_id=current_user["id"],
            question=question,
            connection_id=connection_id,
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        # metadata event
        yield AgentEvent(
            type="metadata",
            content={
                "conversation_id": conversation_id_str,
                "run_id": str(run_id),
            },
        )

        step_number = 0

        async for event in engine.run(query=question, context=context):
            if event.type == "thinking":
                step_number += 1
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="thinking",
                    content=event.content[:500] if event.content else None,
                )
                db.add(step)
                db.commit()
                yield event

            elif event.type == "tool_call":
                tool_name = event.content.get("tool", "")
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                steps_count += 1
                step_number += 1
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="tool_call",
                    tool_name=tool_name,
                    tool_params=event.content.get("params", {}),
                )
                db.add(step)
                db.commit()
                yield event

            elif event.type == "tool_result":
                tool_name = event.content.get("tool", "")
                result_data = event.content.get("result", {})
                summary = result_data.get("data") if isinstance(result_data, dict) else result_data
                summary_str = str(summary)[:500] if summary else ""
                step_number += 1
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="tool_result",
                    tool_name=tool_name,
                    tool_result_summary=summary_str,
                )
                db.add(step)
                db.commit()
                last_tool_result = result_data
                yield event

            elif event.type == "answer":
                answer_text = event.content
                execution_time_ms = int((time.time() - total_start) * 1000)

                response_type = "text"
                response_data = None
                if last_tool_result and isinstance(last_tool_result, dict):
                    data = last_tool_result.get("data")
                    if isinstance(data, dict):
                        if "rows" in data and "fields" in data:
                            response_type = "table"
                            response_data = data
                        elif "value" in data:
                            response_type = "number"
                            response_data = data
                        elif "metrics" in data:
                            response_type = "table"
                            response_data = data

                # Record answer step
                step_number += 1
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="answer",
                    content=answer_text[:500] if answer_text else None,
                    execution_time_ms=execution_time_ms,
                )
                db.add(step)

                # Update run status to completed
                run.status = "completed"
                run.steps_count = steps_count
                run.tools_used = tools_used if tools_used else None
                run.response_type = response_type
                run.execution_time_ms = execution_time_ms
                run.completed_at = datetime.utcnow()
                db.commit()

                # Yield a synthetic "done" event that carries all metadata
                yield AgentEvent(
                    type="done",
                    content={
                        "answer": answer_text,
                        "trace_id": trace_id,
                        "run_id": str(run_id),
                        "tools_used": tools_used,
                        "response_type": response_type,
                        "response_data": response_data,
                        "steps_count": steps_count,
                        "execution_time_ms": execution_time_ms,
                    },
                )

                # Persist assistant message
                session_mgr.persist_message(
                    session=session,
                    role="assistant",
                    content=answer_text,
                    response_type=response_type,
                    response_data=response_data,
                    tools_used=tools_used,
                    trace_id=trace_id,
                    steps_count=steps_count,
                    execution_time_ms=execution_time_ms,
                )

            elif event.type == "error":
                error_content = event.content if isinstance(event.content, dict) else {"message": str(event.content)}
                err_code = error_content.get("error_code", "AGENT_003")

                step_number += 1
                step = BiAgentStep(
                    run_id=run_id,
                    step_number=step_number,
                    step_type="error",
                    content=error_content.get("message", "")[:500],
                )
                db.add(step)
                run.status = "failed"
                run.error_code = err_code
                run.execution_time_ms = int((time.time() - total_start) * 1000)
                run.completed_at = datetime.utcnow()
                db.commit()

                yield AgentEvent(type="error", content=error_content)

    except Exception as e:
        logger.exception("Agent runner exception")
        if run_id:
            try:
                run.status = "failed"
                run.error_code = "AGENT_003"
                run.execution_time_ms = int((time.time() - total_start) * 1000)
                run.completed_at = datetime.utcnow()
                db.commit()
            except Exception:
                logger.warning("Failed to update run status on exception")
        yield AgentEvent(
            type="error",
            content={"error_code": "AGENT_003", "message": "Agent 执行异常"},
        )
