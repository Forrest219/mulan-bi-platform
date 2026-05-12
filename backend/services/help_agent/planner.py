"""Entry-point aware Help Agent planner."""

from __future__ import annotations

import re
from typing import Any

from services.help_agent.schemas import EntryPoint
from services.help_agent.schemas import HelpAgentRequest
from services.help_agent.schemas import PageSelection
from services.help_agent.schemas import PlannerDecision
from services.help_agent.schemas import ToolCallPlan
from services.help_agent.redaction import redact_value

_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b")
_TASK_RE = re.compile(r"\btask[_ -]?run[_ -]?id\s*[:=#]?\s*(\d+)\b", re.I)
_CONN_RE = re.compile(r"\b(?:connection|conn|tableau_connection)[_ -]?id\s*[:=#]?\s*(\d+)\b", re.I)
_SKILL_RE = re.compile(r"\bskill[_ -]?(?:key|id)?\s*[:=#]?\s*([a-zA-Z][\w-]{1,63})\b", re.I)

_WEAK_REFERENCE_TERMS = ("为什么", "怎么回事", "继续", "帮我看看", "这个", "这次", "失败", "慢", "报错", "原因", "诊断")
_PAGE_HELP_TERMS = ("怎么用", "如何使用", "什么意思", "页面说明", "使用说明")
_CONNECTION_SETUP_TERMS = ("怎么连接", "如何连接", "配置 tableau", "连接 tableau", "新增连接", "创建连接")

_TOOL_LABELS = {
    "diagnose_agent_run": "检查问答运行",
    "diagnose_recent_agent_failure": "检查最近失败问答",
    "diagnose_task_run": "检查任务运行",
    "diagnose_connection": "检查连接状态",
    "diagnose_skill": "检查技能状态",
}


class HelpPlanner:
    """Build bounded, de-duplicated diagnostic plans from request context."""

    def __init__(self, max_tool_calls: int = 4) -> None:
        self.max_tool_calls = max_tool_calls

    def plan_initial(self, request: HelpAgentRequest) -> PlannerDecision:
        entry_point = request.entry_point
        question = request.question.strip()
        lowered = question.lower()
        selection = request.page_context.selection if request.page_context else None
        page_hint = self._page_hint(request)

        explicit = self._explicit_plan(question)
        if explicit:
            return PlannerDecision(intent=self._intent_for_tool(explicit.tool_name), tool_calls=[explicit], page_context_hint=page_hint)

        if self._is_page_help(question):
            return PlannerDecision(
                intent="page_help",
                page_context_hint=page_hint,
                conflict_with_selection=bool(selection and self._has_selection(selection)),
                user_message_hint=self._selection_hint(selection) if selection else None,
            )

        if "schema" in lowered and ("工具" in question or "skill" in lowered or "技能" in question):
            return PlannerDecision(
                intent="skill_diagnosis",
                tool_calls=[self._plan("diagnose_skill", {"skill_key": "schema"}, "skill", "schema", "用户问题提到 schema 工具")],
                page_context_hint=page_hint,
            )

        if self._is_recent_failure(question):
            return PlannerDecision(
                intent="recent_failure_diagnosis",
                tool_calls=[self._plan("diagnose_recent_agent_failure", {"limit": 5}, "recent_agent_failure", "current_user", "用户询问最近失败")],
                page_context_hint=page_hint,
            )

        selection_plan = self._plan_from_selection(selection)
        if selection_plan and self._should_consume_selection(entry_point, question):
            return PlannerDecision(
                intent=self._intent_for_tool(selection_plan.tool_name),
                tool_calls=[selection_plan],
                page_context_hint=page_hint,
            )

        if selection_plan and entry_point == EntryPoint.inline_panel and self._is_unrelated_to_selection(question):
            return PlannerDecision(
                intent="general_help",
                page_context_hint=page_hint,
                conflict_with_selection=True,
                user_message_hint=self._selection_hint(selection),
            )

        return PlannerDecision(intent="general_help", page_context_hint=page_hint)

    def plan_related(
        self,
        related_entities: list[dict[str, Any]],
        seen_entity_keys: set[str],
        remaining_slots: int,
        depth: int,
    ) -> list[ToolCallPlan]:
        plans: list[ToolCallPlan] = []
        for entity in related_entities:
            if len(plans) >= remaining_slots:
                break
            plan = self._plan_from_related_entity(entity, depth=depth)
            if plan is None or plan.entity_key in seen_entity_keys:
                continue
            seen_entity_keys.add(plan.entity_key)
            plans.append(plan)
        return plans

    def _explicit_plan(self, question: str) -> ToolCallPlan | None:
        if match := _TASK_RE.search(question):
            return self._plan("diagnose_task_run", {"task_run_id": int(match.group(1))}, "task_run", match.group(1), "用户问题显式包含 task_run_id")
        if match := _CONN_RE.search(question):
            return self._plan("diagnose_connection", {"connection_id": int(match.group(1))}, "connection", match.group(1), "用户问题显式包含 connection_id")
        if match := _SKILL_RE.search(question):
            skill_key = match.group(1)
            if skill_key.lower() not in {"run", "task", "connection"}:
                return self._plan("diagnose_skill", {"skill_key": skill_key}, "skill", skill_key, "用户问题显式包含 skill_key")
        if match := _UUID_RE.search(question):
            run_id = match.group(0)
            return self._plan("diagnose_agent_run", {"run_id": run_id}, "agent_run", run_id, "用户问题显式包含 run_id")
        return None

    def _plan_from_selection(self, selection: PageSelection | None) -> ToolCallPlan | None:
        if selection is None:
            return None
        if selection.run_id:
            return self._plan("diagnose_agent_run", {"run_id": selection.run_id}, "agent_run", str(selection.run_id), "入口 selection.run_id")
        if selection.task_run_id:
            return self._plan("diagnose_task_run", {"task_run_id": int(selection.task_run_id)}, "task_run", str(selection.task_run_id), "入口 selection.task_run_id")
        if selection.connection_id or selection.tableau_connection_id:
            connection_id = selection.connection_id or selection.tableau_connection_id
            return self._plan("diagnose_connection", {"connection_id": int(connection_id)}, "connection", str(connection_id), "入口 selection.connection_id")
        if selection.skill_key:
            return self._plan("diagnose_skill", {"skill_key": selection.skill_key}, "skill", selection.skill_key, "入口 selection.skill_key")
        return None

    def _plan_from_related_entity(self, entity: dict[str, Any], depth: int) -> ToolCallPlan | None:
        entity_type = str(entity.get("type") or "").strip()
        entity_id = entity.get("id")
        reason = str(entity.get("reason") or "related_entities")
        if entity_id in (None, ""):
            return None
        if entity_type in {"connection", "tableau_connection"}:
            return self._plan("diagnose_connection", {"connection_id": int(entity_id)}, "connection", str(entity_id), reason, depth)
        if entity_type == "skill":
            return self._plan("diagnose_skill", {"skill_key": str(entity_id)}, "skill", str(entity_id), reason, depth)
        if entity_type in {"task_run", "task"}:
            return self._plan("diagnose_task_run", {"task_run_id": int(entity_id)}, "task_run", str(entity_id), reason, depth)
        if entity_type in {"agent_run", "run"}:
            return self._plan("diagnose_agent_run", {"run_id": str(entity_id)}, "agent_run", str(entity_id), reason, depth)
        return None

    def _plan(self, tool_name: str, params: dict[str, Any], target_type: str, target_id: str, reason: str, depth: int = 0) -> ToolCallPlan:
        return ToolCallPlan(
            tool_name=tool_name,
            params=params,
            target_type=target_type,
            target_id=str(target_id),
            label=_TOOL_LABELS.get(tool_name, tool_name),
            reason=reason,
            depth=depth,
        )

    def _should_consume_selection(self, entry_point: EntryPoint, question: str) -> bool:
        if entry_point == EntryPoint.inline_panel:
            return not self._is_unrelated_to_selection(question)
        if entry_point == EntryPoint.route_page:
            return bool(question) and self._has_weak_reference(question)
        return bool(question) and self._has_weak_reference(question)

    def _is_unrelated_to_selection(self, question: str) -> bool:
        if not question:
            return False
        lowered = question.lower()
        return any(term in lowered for term in _CONNECTION_SETUP_TERMS)

    def _has_weak_reference(self, question: str) -> bool:
        return any(term in question for term in _WEAK_REFERENCE_TERMS)

    def _is_page_help(self, question: str) -> bool:
        return any(term in question for term in _PAGE_HELP_TERMS)

    def _is_recent_failure(self, question: str) -> bool:
        return bool(question) and ("刚才" in question or "最近" in question) and ("失败" in question or "报错" in question)

    def _has_selection(self, selection: PageSelection) -> bool:
        return any([selection.run_id, selection.task_run_id, selection.connection_id, selection.tableau_connection_id, selection.skill_key])

    def _selection_hint(self, selection: PageSelection | None) -> str | None:
        if selection is None or not self._has_selection(selection):
            return None
        return "如果你想诊断当前选中的对象，可以直接问失败原因或点击重新诊断。"

    def _page_hint(self, request: HelpAgentRequest) -> dict[str, Any]:
        context = request.page_context
        if not context:
            return {}
        hint: dict[str, Any] = {"path": context.path, "entry_point": request.entry_point.value}
        if context.visible_state:
            hint["visible_state"] = redact_value(context.visible_state)
        if context.selection:
            hint["candidate_entities"] = redact_value(context.selection.model_dump(exclude_none=True))
        return redact_value(hint)

    def _intent_for_tool(self, tool_name: str) -> str:
        return {
            "diagnose_agent_run": "agent_run_diagnosis",
            "diagnose_recent_agent_failure": "recent_failure_diagnosis",
            "diagnose_task_run": "task_diagnosis",
            "diagnose_connection": "connection_diagnosis",
            "diagnose_skill": "skill_diagnosis",
        }.get(tool_name, "general_help")
