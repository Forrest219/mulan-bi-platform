"""Help Agent async SSE orchestration service."""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import AsyncGenerator
from collections.abc import AsyncIterator
from collections.abc import Callable
from datetime import datetime
from typing import Any

from services.help_agent.planner import HelpPlanner
from services.help_agent.redaction import redact_text
from services.help_agent.redaction import redact_value
from services.help_agent.renderer import build_prompt
from services.help_agent.renderer import render_fallback_answer
from services.help_agent.schemas import DiagnosticProgressEvent
from services.help_agent.schemas import DiagnosticStatus
from services.help_agent.schemas import EntryPoint
from services.help_agent.schemas import HelpAgentRequest
from services.help_agent.schemas import PlannerDecision
from services.help_agent.schemas import ResponseData
from services.help_agent.schemas import ToolCallPlan
from services.help_agent.schemas import utc_snapshot


class FallbackHelpToolRegistry:
    """Mockable fallback registry used until Task C wires real tools."""

    async def execute(self, tool_name: str, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        snapshot_at = utc_snapshot()
        target = self._target_for(tool_name, params)
        return {
            "tool": tool_name,
            "snapshot_at": snapshot_at,
            "target": target,
            "facts": {"available": False, "reason": "diagnostic tool registry is not configured"},
            "findings": [
                {
                    "severity": "info",
                    "code": "FACTS_UNAVAILABLE",
                    "message": "诊断工具尚未接入，当前只能保留请求上下文。",
                }
            ],
            "recommendations": [{"priority": "P1", "action": "接入 Help Agent diagnostic tool registry 后重试。"}],
            "related_entities": [],
        }

    def _target_for(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "diagnose_agent_run":
            return {"type": "agent_run", "id": str(params.get("run_id"))}
        if tool_name == "diagnose_task_run":
            return {"type": "task_run", "id": str(params.get("task_run_id"))}
        if tool_name == "diagnose_connection":
            return {"type": "connection", "id": str(params.get("connection_id"))}
        if tool_name == "diagnose_skill":
            return {"type": "skill", "id": str(params.get("skill_key"))}
        return {"type": tool_name, "id": "current_user"}


class DeterministicHelpLLM:
    async def stream_answer(self, prompt: str, facts: dict[str, Any]) -> AsyncIterator[str]:
        del prompt
        yield render_fallback_answer(
            question=facts.get("question", ""),
            response_data=facts["response_data"],
            user_message_hint=facts.get("user_message_hint"),
        )


class HelpAgentService:
    """Coordinate planning, tool execution, answer generation, and short-lived persistence."""

    def __init__(
        self,
        *,
        planner: HelpPlanner | None = None,
        tool_registry: Any | None = None,
        llm_adapter: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
        max_tool_calls: int = 4,
        tool_timeout_seconds: float = 5.0,
    ) -> None:
        self.planner = planner or HelpPlanner(max_tool_calls=max_tool_calls)
        self.session_factory = session_factory or self._default_session_factory()
        self.tool_registry = tool_registry or self._default_tool_registry(self.session_factory)
        self.llm_adapter = llm_adapter or DeterministicHelpLLM()
        self.max_tool_calls = max_tool_calls
        self.tool_timeout_seconds = tool_timeout_seconds
        self._step_numbers: dict[str, int] = {}

    async def stream(
        self,
        request: HelpAgentRequest | dict[str, Any],
        *,
        current_user: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        started = time.monotonic()
        snapshot_started_at = utc_snapshot()
        parsed = request if isinstance(request, HelpAgentRequest) else HelpAgentRequest.model_validate(request)
        if parsed.page_context and parsed.page_context.entry_point and "entry_point" not in (request if isinstance(request, dict) else {}):
            parsed.entry_point = parsed.page_context.entry_point
        if not parsed.question and parsed.entry_point != EntryPoint.inline_panel:
            yield self._error("HLP_001", "请输入要诊断的问题。", "Inline Panel 以外的入口需要提供问题。")
            return

        conversation_id = str(parsed.conversation_id or uuid.uuid4())
        run_id = str(uuid.uuid4())
        tools_used: list[str] = []
        seen_entity_keys: set[str] = set()
        diagnostics: list[dict[str, Any]] = []
        failed_diagnostics: list[dict[str, Any]] = []
        total_tool_calls = 0

        try:
            await self._ensure_conversation_and_run(
                conversation_id=conversation_id,
                run_id=run_id,
                request=parsed,
                current_user=current_user or {},
                snapshot_started_at=snapshot_started_at,
            )
            await self._persist_message(conversation_id, "user", parsed.question or "请诊断当前对象。")
            await self._persist_step(run_id, "thinking", {"content": "start"})
            yield {"type": "metadata", "conversation_id": conversation_id, "run_id": run_id}
            yield {"type": "thinking", "content": "正在检查相关诊断信息。", "run_id": run_id}

            decision = self.planner.plan_initial(parsed)
            batch = decision.tool_calls[: self.max_tool_calls]
            for plan in batch:
                seen_entity_keys.add(plan.entity_key)

            depth = 0
            while batch and total_tool_calls < self.max_tool_calls:
                remaining = self.max_tool_calls - total_tool_calls
                batch = batch[:remaining]
                async for event in self._execute_batch(batch, run_id, current_user or {}):
                    if event["type"] == "_tool_success":
                        diagnostics.append(event["result"])
                        tools_used.append(event["tool_name"])
                        total_tool_calls += 1
                    elif event["type"] == "_tool_failed":
                        failed_diagnostics.append(event["result"])
                        tools_used.append(event["tool_name"])
                        total_tool_calls += 1
                    else:
                        yield event

                if total_tool_calls >= self.max_tool_calls:
                    break
                related = self._collect_related(diagnostics)
                batch = self.planner.plan_related(
                    related,
                    seen_entity_keys,
                    self.max_tool_calls - total_tool_calls,
                    depth=depth + 1,
                )
                depth += 1

            response_data = self._build_response_data(
                snapshot_started_at=snapshot_started_at,
                diagnostics=diagnostics,
                failed_diagnostics=failed_diagnostics,
                decision=decision,
            )
            prompt = build_prompt(
                question=parsed.question,
                page_context_hint=decision.page_context_hint,
                diagnostic_facts=response_data,
            )
            answer = ""
            async for token in self.llm_adapter.stream_answer(
                prompt,
                {
                    "question": parsed.question,
                    "response_data": response_data,
                    "user_message_hint": decision.user_message_hint,
                },
            ):
                answer += token
                yield {"type": "token", "content": token, "run_id": run_id}

            if not answer:
                answer = render_fallback_answer(
                    question=parsed.question,
                    response_data=response_data,
                    user_message_hint=decision.user_message_hint,
                )
                yield {"type": "token", "content": answer, "run_id": run_id}

            execution_time_ms = int((time.monotonic() - started) * 1000)
            await self._persist_step(run_id, "answer", {"content": answer, "response_data": response_data})
            await self._complete_run_and_message(
                conversation_id=conversation_id,
                run_id=run_id,
                answer=answer,
                response_data=response_data,
                tools_used=tools_used,
                execution_time_ms=execution_time_ms,
                sources_count=len(diagnostics),
                top_sources=self._top_sources(diagnostics),
            )
            yield {
                "type": "done",
                "answer": answer,
                "trace_id": run_id,
                "run_id": run_id,
                "tools_used": tools_used,
                "response_type": "help",
                "response_data": response_data,
                "steps_count": len(tools_used) + 2,
                "execution_time_ms": execution_time_ms,
                "sources_count": len(diagnostics),
                "top_sources": self._top_sources(diagnostics),
            }
        except Exception as exc:
            await self._mark_run_failed(run_id, exc)
            yield self._error("HLP_500", "Help Agent 诊断过程异常。", str(exc)[:300])

    async def _execute_batch(
        self,
        plans: list[ToolCallPlan],
        run_id: str,
        current_user: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        started_by_key: dict[str, tuple[str, float]] = {}
        for plan in plans:
            yield self._progress(run_id, plan, DiagnosticStatus.pending)
        for plan in plans:
            started_by_key[plan.step_key] = (utc_snapshot(), time.monotonic())
            yield self._progress(run_id, plan, DiagnosticStatus.running, started_at=started_by_key[plan.step_key][0])
            yield {"type": "tool_call", "run_id": run_id, "tool_name": plan.tool_name, "tool_params": redact_value(plan.params), "step_key": plan.step_key}
            await self._persist_step(run_id, "tool_call", {"tool": plan.tool_name, "params": plan.params})

        tasks = [asyncio.wait_for(self._execute_tool(plan, current_user), timeout=self.tool_timeout_seconds) for plan in plans]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for plan, result in zip(plans, results):
            started_at, step_started = started_by_key[plan.step_key]
            finished_at = utc_snapshot()
            execution_time_ms = int((time.monotonic() - step_started) * 1000)
            if isinstance(result, Exception):
                payload = self._failed_tool_payload(plan, result)
                yield self._progress(
                    run_id,
                    plan,
                    DiagnosticStatus.failed,
                    started_at=started_at,
                    finished_at=finished_at,
                    execution_time_ms=execution_time_ms,
                    message=payload["findings"][0]["message"],
                )
                yield {"type": "tool_result", "run_id": run_id, "tool_name": plan.tool_name, "result": redact_value(payload), "step_key": plan.step_key}
                await self._persist_step(run_id, "tool_result", payload)
                yield {"type": "_tool_failed", "tool_name": plan.tool_name, "result": payload}
                continue

            yield self._progress(
                run_id,
                plan,
                DiagnosticStatus.completed,
                started_at=started_at,
                finished_at=finished_at,
                execution_time_ms=execution_time_ms,
            )
            yield {"type": "tool_result", "run_id": run_id, "tool_name": plan.tool_name, "result": redact_value(result), "step_key": plan.step_key}
            await self._persist_step(run_id, "tool_result", result)
            yield {"type": "_tool_success", "tool_name": plan.tool_name, "result": result}

    async def _execute_tool(self, plan: ToolCallPlan, current_user: dict[str, Any]) -> dict[str, Any]:
        context = {"current_user": current_user, "target_type": plan.target_type, "target_id": plan.target_id}
        execute = getattr(self.tool_registry, "execute", None)
        if execute is None:
            tool = self.tool_registry.get(plan.tool_name)
            execute = tool.execute
            result = execute(plan.params, context)
        else:
            result = execute(plan.tool_name, plan.params, context)
        if inspect.isawaitable(result):
            result = await result
        return self._normalize_tool_result(plan, result)

    def _normalize_tool_result(self, plan: ToolCallPlan, result: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(result or {})
        normalized.setdefault("tool", plan.tool_name)
        normalized.setdefault("snapshot_at", utc_snapshot())
        normalized.setdefault("target", {"type": plan.target_type, "id": plan.target_id})
        normalized.setdefault("facts", {})
        normalized.setdefault("findings", [])
        normalized.setdefault("recommendations", [])
        normalized.setdefault("related_entities", [])
        return redact_value(normalized)

    def _failed_tool_payload(self, plan: ToolCallPlan, exc: Exception) -> dict[str, Any]:
        return {
            "tool": plan.tool_name,
            "snapshot_at": utc_snapshot(),
            "target": {"type": plan.target_type, "id": plan.target_id},
            "facts": {},
            "findings": [
                {
                    "severity": "warning",
                    "code": "TOOL_FAILED",
                    "message": f"{plan.label}失败，已保留其它可用诊断事实。",
                }
            ],
            "recommendations": [],
            "related_entities": [],
            "error": {"type": exc.__class__.__name__, "message": redact_text(str(exc)[:300])},
        }

    def _build_response_data(
        self,
        *,
        snapshot_started_at: str,
        diagnostics: list[dict[str, Any]],
        failed_diagnostics: list[dict[str, Any]],
        decision: PlannerDecision,
    ) -> dict[str, Any]:
        all_diagnostics = sorted([*diagnostics, *failed_diagnostics], key=lambda item: str(item.get("snapshot_at", "")))
        response = ResponseData(
            snapshot_started_at=snapshot_started_at,
            snapshot_completed_at=utc_snapshot(),
            diagnostics=all_diagnostics,
            findings=[finding for item in all_diagnostics for finding in item.get("findings", [])],
            recommendations=[rec for item in all_diagnostics for rec in item.get("recommendations", [])],
            related_entities=self._dedupe_related([entity for item in all_diagnostics for entity in item.get("related_entities", [])]),
            trace={"intent": decision.intent, "partial": bool(failed_diagnostics)},
        )
        return response.model_dump()

    def _collect_related(self, diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._dedupe_related([entity for item in diagnostics for entity in item.get("related_entities", [])])

    def _dedupe_related(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for entity in entities:
            key = (str(entity.get("type")), str(entity.get("id")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entity)
        return deduped

    def _top_sources(self, diagnostics: list[dict[str, Any]]) -> list[str]:
        sources: list[str] = []
        for item in diagnostics[:5]:
            target = item.get("target") or {}
            sources.append(f"{target.get('type')}:{target.get('id')}")
        return sources

    def _progress(
        self,
        run_id: str,
        plan: ToolCallPlan,
        status: DiagnosticStatus,
        *,
        started_at: str | None = None,
        finished_at: str | None = None,
        execution_time_ms: int | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        return DiagnosticProgressEvent(
            run_id=run_id,
            step_key=plan.step_key,
            label=plan.label,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            execution_time_ms=execution_time_ms,
            message=message,
        ).model_dump(mode="json")

    async def _persist_step(self, run_id: str, step_type: str, payload: dict[str, Any]) -> None:
        if self.session_factory is None:
            return
        safe_payload = redact_value(payload)
        try:
            session = self.session_factory()
        except Exception:
            return
        try:
            try:
                from services.help_agent.models import HelpAgentStep
            except Exception:
                return
            step_number = self._step_numbers.get(run_id, 0) + 1
            self._step_numbers[run_id] = step_number
            step = HelpAgentStep(
                run_id=run_id,
                step_number=step_number,
                step_type=step_type,
                tool_name=safe_payload.get("tool") or safe_payload.get("tool_name"),
                tool_params=safe_payload.get("params") or safe_payload.get("tool_params"),
                tool_result_summary=self._summary(safe_payload),
                content=safe_payload.get("content"),
                diagnostic_payload=safe_payload,
                related_entities=safe_payload.get("related_entities"),
                snapshot_at=self._parse_datetime(safe_payload.get("snapshot_at")),
                execution_time_ms=safe_payload.get("execution_time_ms"),
            )
            session.add(step)
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def _error(self, error_code: str, message: str, user_hint: str) -> dict[str, Any]:
        return {"type": "error", "error_code": error_code, "message": message, "user_hint": user_hint}

    def _default_session_factory(self) -> Callable[[], Any] | None:
        try:
            from app.core.database import SessionLocal

            return SessionLocal
        except Exception:
            return None

    def _default_tool_registry(self, session_factory: Callable[[], Any] | None) -> Any:
        if session_factory is None:
            return FallbackHelpToolRegistry()
        try:
            from services.help_agent.tools import HelpToolRegistry

            return HelpToolRegistry(session_factory=session_factory)
        except Exception:
            return FallbackHelpToolRegistry()

    async def _ensure_conversation_and_run(
        self,
        *,
        conversation_id: str,
        run_id: str,
        request: HelpAgentRequest,
        current_user: dict[str, Any],
        snapshot_started_at: str,
    ) -> None:
        if self.session_factory is None:
            return
        session = self.session_factory()
        try:
            from services.help_agent.models import HelpAgentConversation, HelpAgentRun

            user_id = int(current_user.get("id") or 0)
            conversation = session.get(HelpAgentConversation, uuid.UUID(conversation_id))
            if conversation is None:
                conversation = HelpAgentConversation(
                    id=uuid.UUID(conversation_id),
                    user_id=user_id,
                    title=redact_text(request.question or "Help Agent 诊断")[:80],
                    last_page_path=request.page_context.path if request.page_context else None,
                )
                session.add(conversation)
            elif conversation.user_id != user_id and current_user.get("role") not in {"admin", "data_admin"}:
                raise PermissionError("无权限访问该 Help Agent 会话。")

            run = HelpAgentRun(
                id=uuid.UUID(run_id),
                conversation_id=uuid.UUID(conversation_id),
                user_id=user_id,
                question=redact_text(request.question or "请诊断当前对象。"),
                page_context=redact_value(request.page_context.model_dump(mode="json")) if request.page_context else None,
                status="running",
                snapshot_started_at=self._parse_datetime(snapshot_started_at) or datetime.now().astimezone(),
            )
            session.add(run)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _persist_message(self, conversation_id: str, role: str, content: str, **metadata: Any) -> None:
        if self.session_factory is None:
            return
        session = self.session_factory()
        try:
            from services.help_agent.models import HelpAgentMessage

            session.add(
                HelpAgentMessage(
                    conversation_id=uuid.UUID(conversation_id),
                    role=role,
                    content=redact_text(content),
                    response_type=metadata.get("response_type"),
                    response_data=redact_value(metadata.get("response_data")),
                    tools_used=metadata.get("tools_used"),
                    trace_id=uuid.UUID(metadata["trace_id"]) if metadata.get("trace_id") else None,
                    steps_count=metadata.get("steps_count"),
                    execution_time_ms=metadata.get("execution_time_ms"),
                    sources_count=metadata.get("sources_count"),
                    top_sources=metadata.get("top_sources"),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    async def _complete_run_and_message(
        self,
        *,
        conversation_id: str,
        run_id: str,
        answer: str,
        response_data: dict[str, Any],
        tools_used: list[str],
        execution_time_ms: int,
        sources_count: int,
        top_sources: list[str],
    ) -> None:
        if self.session_factory is None:
            return
        session = self.session_factory()
        try:
            from services.help_agent.models import HelpAgentConversation, HelpAgentRun

            run = session.get(HelpAgentRun, uuid.UUID(run_id))
            if run is not None:
                run.status = "completed"
                run.response_type = "help"
                run.tools_used = tools_used
                run.steps_count = self._step_numbers.get(run_id, 0)
                run.execution_time_ms = execution_time_ms
                run.snapshot_completed_at = self._parse_datetime(response_data.get("snapshot_completed_at"))
                run.completed_at = datetime.now().astimezone()
            conversation = session.get(HelpAgentConversation, uuid.UUID(conversation_id))
            if conversation is not None:
                conversation.updated_at = datetime.now().astimezone()
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

        await self._persist_message(
            conversation_id,
            "assistant",
            answer,
            response_type="help",
            response_data=response_data,
            tools_used=tools_used,
            trace_id=run_id,
            steps_count=self._step_numbers.get(run_id, 0),
            execution_time_ms=execution_time_ms,
            sources_count=sources_count,
            top_sources=top_sources,
        )

    async def _mark_run_failed(self, run_id: str, exc: Exception) -> None:
        if self.session_factory is None:
            return
        session = self.session_factory()
        try:
            from services.agent_observability import StructuredBIError
            from services.help_agent.models import HelpAgentRun

            run = session.get(HelpAgentRun, uuid.UUID(run_id))
            if run is not None:
                run.status = "failed"
                run.error_code = "HLP_004"
                run.structured_error = StructuredBIError.from_exception(exc, error_code="HLP_004").to_dict()
                run.completed_at = datetime.now().astimezone()
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def _summary(self, payload: dict[str, Any]) -> str | None:
        if "tool_result_summary" in payload:
            return str(payload["tool_result_summary"])[:500]
        findings = payload.get("findings") or []
        if findings:
            return "; ".join(str(item.get("message", "")) for item in findings[:3])[:500]
        if payload.get("content"):
            return str(payload["content"])[:500]
        return None

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
