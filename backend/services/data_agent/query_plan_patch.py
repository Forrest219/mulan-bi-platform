"""Query Plan Patch primitives and pure patch application.

Draft target:
    backend/services/data_agent/query_plan_patch.py

This file intentionally implements only deterministic patch application. Patch
generation can initially be rule-based or LLM-assisted, but the generated patch
must pass through this pure function before execution.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.data_agent.analysis_context import (
    ANALYSIS_CONTEXT_VERSION,
    AnalysisContext,
    context_hash,
    field_caption,
    make_filter_id,
    normalize_query_plan,
    query_plan_summary,
)


QUERY_PLAN_PATCH_VERSION = "query_plan_patch.v1"

PATCH_TYPES = {
    "add_dimension",
    "remove_dimension",
    "replace_dimension",
    "add_filter",
    "remove_filter",
    "replace_filter",
    "set_time_range",
    "set_time_grain",
    "add_metric",
    "replace_metric",
    "switch_analysis_type",
    "set_comparison",
    "set_limit_sort",
    "request_chart",
    "clarify_reference",
    "reset_plan",
    "fallback_required",
}

PROTECTED_SCOPE_FIELDS = {"tenant_id", "user_id", "role"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


@dataclass(slots=True)
class QueryPlanPatch:
    patch_type: str
    payload: dict[str, Any]
    conversation_id: Optional[str]
    base_context_hash: str
    turn_no: int
    reason: str = ""
    source: str = "user_utterance"
    confidence: float = 0.0
    patch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = QUERY_PLAN_PATCH_VERSION
    created_at: str = field(default_factory=_utc_now_iso)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "QueryPlanPatch":
        version = payload.get("schema_version")
        if version != QUERY_PLAN_PATCH_VERSION:
            raise ValueError(f"unsupported query plan patch version: {version}")
        patch_type = str(payload.get("patch_type") or "")
        if patch_type not in PATCH_TYPES:
            raise ValueError(f"unsupported patch_type: {patch_type}")
        return cls(
            patch_id=str(payload.get("patch_id") or uuid.uuid4()),
            schema_version=QUERY_PLAN_PATCH_VERSION,
            conversation_id=payload.get("conversation_id"),
            base_context_hash=str(payload.get("base_context_hash") or ""),
            turn_no=int(payload.get("turn_no") or 0),
            patch_type=patch_type,
            payload=_deepcopy(payload.get("payload") or {}),
            reason=str(payload.get("reason") or ""),
            source=str(payload.get("source") or "user_utterance"),
            confidence=float(payload.get("confidence") or 0.0),
            created_at=str(payload.get("created_at") or _utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "schema_version": self.schema_version,
            "conversation_id": self.conversation_id,
            "base_context_hash": self.base_context_hash,
            "turn_no": self.turn_no,
            "patch_type": self.patch_type,
            "payload": _deepcopy(self.payload),
            "reason": self.reason,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class AppliedPatch:
    next_context: AnalysisContext
    patch: QueryPlanPatch
    diff: dict[str, Any]
    warnings: list[dict[str, str]] = field(default_factory=list)

    def to_step_summary(self) -> str:
        parts: list[str] = []
        for key in ("metrics_added", "dimensions_added", "filters_added"):
            for value in self.diff.get(key, []):
                parts.append(f"+{key.removesuffix('_added')[:-1]}={value}")
        for key in ("metrics_removed", "dimensions_removed", "filters_removed"):
            for value in self.diff.get(key, []):
                parts.append(f"-{key.removesuffix('_removed')[:-1]}={value}")
        if "analysis_type" in self.diff:
            parts.append(f"analysis_type={self.diff['analysis_type']}")
        if "time" in self.diff:
            parts.append("time=updated")
        return "; ".join(parts)[:500] or self.patch.patch_type


class PatchApplyError(Exception):
    def __init__(self, code: str, message: str, *, user_hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.user_hint = user_hint or message

    def to_fallback(self, trace_id: str) -> dict[str, Any]:
        return {
            "fallback_type": "query_plan_patch_failed",
            "error_code": self.code,
            "message": str(self),
            "user_hint": self.user_hint,
            "trace_id": trace_id,
        }


def make_patch(
    *,
    previous_context: AnalysisContext,
    patch_type: str,
    payload: Mapping[str, Any],
    reason: str,
    source: str = "user_utterance",
    confidence: float = 0.0,
) -> QueryPlanPatch:
    return QueryPlanPatch(
        conversation_id=previous_context.conversation_id,
        base_context_hash=previous_context.hash,
        turn_no=previous_context.turn_no + 1,
        patch_type=patch_type,
        payload=dict(payload),
        reason=reason,
        source=source,
        confidence=confidence,
    )


def apply_query_plan_patch(previous_context: AnalysisContext | Mapping[str, Any], patch_payload: QueryPlanPatch | Mapping[str, Any]) -> AppliedPatch:
    previous = previous_context if isinstance(previous_context, AnalysisContext) else AnalysisContext.from_payload(previous_context)
    patch = patch_payload if isinstance(patch_payload, QueryPlanPatch) else QueryPlanPatch.from_payload(patch_payload)

    if patch.base_context_hash and patch.base_context_hash != previous.hash:
        raise PatchApplyError(
            "context_hash_mismatch",
            "Query plan patch is based on a stale analysis context.",
            user_hint="当前对话上下文已变化，请基于最新结果重新提问。",
        )
    if patch.patch_type == "fallback_required":
        raise PatchApplyError(
            str(patch.payload.get("reason_code") or "fallback_required"),
            str(patch.payload.get("message") or "Patch cannot be safely applied."),
            user_hint=str(patch.payload.get("user_hint") or "这个问题需要先补充更明确的指标、维度或时间范围。"),
        )

    before = previous.to_dict()
    next_context = previous.clone()
    next_context.turn_no = patch.turn_no or previous.turn_no + 1
    next_context.updated_at = _utc_now_iso()
    next_context.provenance["last_patch_id"] = patch.patch_id
    next_context.query_plan = normalize_query_plan(next_context.query_plan)

    warnings: list[dict[str, str]] = []
    _apply_patch_payload(next_context, patch, warnings)

    if next_context.schema_version != ANALYSIS_CONTEXT_VERSION:
        raise PatchApplyError("invalid_context_version", "Patch produced invalid analysis context version.")
    _assert_protected_scope_unchanged(previous.scope, next_context.scope)

    after = next_context.to_dict()
    return AppliedPatch(
        next_context=next_context,
        patch=patch,
        diff=diff_query_plan(before, after),
        warnings=warnings,
    )


def _apply_patch_payload(context: AnalysisContext, patch: QueryPlanPatch, warnings: list[dict[str, str]]) -> None:
    plan = context.query_plan
    payload = patch.payload
    patch_type = patch.patch_type

    if patch_type == "add_dimension":
        _append_unique(plan["dimensions"], payload["dimension"], "dimension")
    elif patch_type == "remove_dimension":
        _remove_by_ref(plan["dimensions"], payload["dimension_ref"], "dimension")
    elif patch_type == "replace_dimension":
        _remove_by_ref(plan["dimensions"], payload["from_dimension_ref"], "dimension")
        _append_unique(plan["dimensions"], payload["to_dimension"], "dimension")
    elif patch_type == "add_filter":
        filter_spec = dict(payload["filter"])
        filter_spec.setdefault("id", make_filter_id())
        plan["filters"].append(filter_spec)
    elif patch_type == "remove_filter":
        _remove_by_ref(plan["filters"], payload["filter_ref"], "filter")
    elif patch_type == "replace_filter":
        _remove_by_ref(plan["filters"], payload["from_filter_ref"], "filter")
        filter_spec = dict(payload["to_filter"])
        filter_spec.setdefault("id", make_filter_id())
        plan["filters"].append(filter_spec)
    elif patch_type == "set_time_range":
        _set_time(plan, payload)
    elif patch_type == "set_time_grain":
        if not plan.get("time"):
            raise PatchApplyError("time_field_required", "Cannot set time grain without a time field.")
        plan["time"]["grain"] = payload["grain"]
    elif patch_type == "add_metric":
        _append_unique(plan["metrics"], payload["metric"], "metric")
    elif patch_type == "replace_metric":
        _remove_by_ref(plan["metrics"], payload["from_metric_ref"], "metric")
        _append_unique(plan["metrics"], payload["to_metric"], "metric")
    elif patch_type == "switch_analysis_type":
        context.analysis_intent["analysis_type"] = payload["to_type"]
        postprocess = plan.setdefault("postprocess", {})
        if payload.get("semantic_operator"):
            postprocess["semantic_operator"] = payload["semantic_operator"]
    elif patch_type == "set_comparison":
        plan["comparison"] = dict(payload["comparison"])
    elif patch_type == "set_limit_sort":
        if "limit" in payload:
            limit = int(payload["limit"])
            if limit < 1 or limit > 1000:
                raise PatchApplyError("limit_out_of_range", "Requested limit is outside the allowed range 1..1000.")
            plan["limit"] = limit
        if "order_by" in payload:
            plan["order_by"] = list(payload["order_by"])
    elif patch_type == "request_chart":
        plan["viz"] = {"requested": True, "chart_type": payload.get("chart_type")}
    elif patch_type == "clarify_reference":
        context.semantic_resolution.setdefault("resolved_refs", []).extend(list(payload.get("resolved_refs") or []))
        if payload.get("patches"):
            for nested in payload["patches"]:
                nested_patch = QueryPlanPatch(
                    conversation_id=patch.conversation_id,
                    base_context_hash="",
                    turn_no=patch.turn_no,
                    patch_type=nested["patch_type"],
                    payload=dict(nested.get("payload") or {}),
                    reason=f"nested clarify_reference: {patch.reason}",
                    confidence=patch.confidence,
                )
                _apply_patch_payload(context, nested_patch, warnings)
    elif patch_type == "reset_plan":
        context.query_plan = normalize_query_plan(payload["new_query_plan"])
        if payload.get("analysis_intent"):
            context.analysis_intent.update(dict(payload["analysis_intent"]))
    else:
        raise PatchApplyError("unsupported_patch_type", f"Unsupported patch type: {patch_type}")


def _append_unique(items: list[dict[str, Any]], spec: Mapping[str, Any], kind: str) -> None:
    candidate = dict(spec)
    caption = field_caption(candidate)
    if not caption:
        raise PatchApplyError(f"{kind}_caption_required", f"{kind} field_caption/name is required.")
    if any(field_caption(existing) == caption for existing in items):
        return
    items.append(candidate)


def _remove_by_ref(items: list[dict[str, Any]], ref: Any, kind: str) -> None:
    ref_text = str(ref)
    kept = []
    removed = False
    for item in items:
        item_refs = {
            str(item.get("id") or ""),
            str(item.get("name") or ""),
            str(item.get("semantic_name") or ""),
            str(item.get("field_caption") or item.get("fieldCaption") or ""),
        }
        if ref_text in item_refs:
            removed = True
        else:
            kept.append(item)
    if not removed:
        raise PatchApplyError(f"{kind}_not_found", f"Cannot remove unknown {kind}: {ref_text}")
    items[:] = kept


def _set_time(plan: dict[str, Any], payload: Mapping[str, Any]) -> None:
    time_payload = dict(payload["time"])
    field = field_caption(time_payload) or field_caption(plan.get("time") or {})
    if not field:
        raise PatchApplyError("time_field_required", "Time field is required for set_time_range.")
    time_payload.setdefault("field_caption", field)
    plan["time"] = time_payload

    range_payload = time_payload.get("range") or {}
    if range_payload.get("type") == "absolute":
        start = range_payload.get("start")
        end = range_payload.get("end")
        if not start or not end:
            raise PatchApplyError("absolute_time_range_required", "Absolute time range requires start and end.")
        plan["filters"] = [
            f for f in plan.get("filters", [])
            if field_caption(f) != field and str(f.get("id") or "").startswith("f_time_") is False
        ]
        plan["filters"].append({
            "id": f"f_time_{str(start)[:4]}",
            "field_caption": field,
            "operator": "between",
            "value": [start, end],
            "value_type": "date",
            "source": "user",
        })


def _assert_protected_scope_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    for field_name in PROTECTED_SCOPE_FIELDS:
        if before.get(field_name) != after.get(field_name):
            raise PatchApplyError("protected_scope_modified", f"Patch attempted to modify protected scope.{field_name}.")


def diff_query_plan(before_context: Mapping[str, Any], after_context: Mapping[str, Any]) -> dict[str, Any]:
    before_summary = query_plan_summary(before_context)
    after_summary = query_plan_summary(after_context)
    diff: dict[str, Any] = {}

    for key in ("metrics", "dimensions"):
        before_set = set(before_summary[key])
        after_set = set(after_summary[key])
        added = sorted(after_set - before_set)
        removed = sorted(before_set - after_set)
        if added:
            diff[f"{key}_added"] = added
        if removed:
            diff[f"{key}_removed"] = removed

    before_filters = {jsonish_filter(f) for f in before_summary["filters"]}
    after_filters = {jsonish_filter(f) for f in after_summary["filters"]}
    if after_filters - before_filters:
        diff["filters_added"] = sorted(after_filters - before_filters)
    if before_filters - after_filters:
        diff["filters_removed"] = sorted(before_filters - after_filters)

    if before_summary.get("time") != after_summary.get("time"):
        diff["time"] = {"before": before_summary.get("time"), "after": after_summary.get("time")}
    if before_summary.get("comparison") != after_summary.get("comparison"):
        diff["comparison"] = {"before": before_summary.get("comparison"), "after": after_summary.get("comparison")}
    if before_summary.get("limit") != after_summary.get("limit") or before_summary.get("order_by") != after_summary.get("order_by"):
        diff["limit_sort"] = {"limit": after_summary.get("limit"), "order_by": after_summary.get("order_by")}
    before_type = before_context.get("analysis_intent", {}).get("analysis_type")
    after_type = after_context.get("analysis_intent", {}).get("analysis_type")
    if before_type != after_type:
        diff["analysis_type"] = {"before": before_type, "after": after_type}
    return diff


def jsonish_filter(filter_spec: Mapping[str, Any]) -> str:
    return f"{filter_spec.get('field_caption')}|{filter_spec.get('operator')}|{filter_spec.get('value')}"
