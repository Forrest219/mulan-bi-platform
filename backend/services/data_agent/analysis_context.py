"""Versioned Analysis Context for controlled Data Agent turns.

Draft target:
    backend/services/data_agent/analysis_context.py

The module is deliberately dependency-light. It can be copied into the backend
package before runner/engine wiring, and it does not depend on the proposed
pushdown/operator modules.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional


ANALYSIS_CONTEXT_VERSION = "analysis_context.v1"

CONTEXT_RESPONSE_DATA_KEY = "analysis_context"
PATCH_RESPONSE_DATA_KEY = "query_plan_patch"
QUALITY_RESPONSE_DATA_KEY = "quality_gate"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _deepcopy_json(value: Any) -> Any:
    return copy.deepcopy(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def context_hash(payload: Mapping[str, Any]) -> str:
    """Stable SHA-256 hash for optimistic concurrency on follow-up patches."""
    normalized = dict(payload)
    normalized.pop("context_hash", None)
    return hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()


def make_filter_id(prefix: str = "f") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class AnalysisContext:
    """Mutable value object persisted as JSON in assistant response_data."""

    conversation_id: Optional[str]
    run_id: Optional[str]
    trace_id: str
    turn_no: int
    scope: dict[str, Any]
    analysis_intent: dict[str, Any]
    query_plan: dict[str, Any]
    semantic_resolution: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    schema_version: str = ANALYSIS_CONTEXT_VERSION
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    @classmethod
    def new(
        cls,
        *,
        conversation_id: Optional[str],
        run_id: Optional[str],
        trace_id: str,
        turn_no: int,
        scope: Mapping[str, Any],
        query_plan: Mapping[str, Any],
        analysis_type: str = "lookup",
        confidence: float = 0.0,
        source: str = "router_guardrail",
        is_followup: bool = False,
        language: str = "zh-CN",
    ) -> "AnalysisContext":
        return cls(
            conversation_id=conversation_id,
            run_id=run_id,
            trace_id=trace_id,
            turn_no=turn_no,
            scope=_deepcopy_json(dict(scope)),
            analysis_intent={
                "analysis_type": analysis_type,
                "confidence": confidence,
                "source": source,
                "is_followup": is_followup,
                "language": language,
            },
            query_plan=normalize_query_plan(query_plan),
            semantic_resolution={
                "field_bindings": [],
                "unresolved_terms": [],
                "operator_checks": [],
            },
            provenance={
                "created_from_message_id": None,
                "last_patch_id": None,
                "source_step_ids": [],
                "tools_used": [],
                "mcp_baseline_id": None,
            },
            quality={
                "gate_status": "warn",
                "gate_level": "blocking",
                "checks": [],
                "warnings": [{"code": "not_evaluated", "message": "quality gate has not run"}],
                "blockers": [],
            },
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AnalysisContext":
        if payload.get("schema_version") != ANALYSIS_CONTEXT_VERSION:
            raise ValueError(f"unsupported analysis context version: {payload.get('schema_version')}")
        return cls(
            conversation_id=payload.get("conversation_id"),
            run_id=payload.get("run_id"),
            trace_id=str(payload.get("trace_id") or ""),
            turn_no=int(payload.get("turn_no") or 0),
            status=str(payload.get("status") or "active"),
            scope=_deepcopy_json(payload.get("scope") or {}),
            analysis_intent=_deepcopy_json(payload.get("analysis_intent") or {}),
            query_plan=normalize_query_plan(payload.get("query_plan") or {}),
            semantic_resolution=_deepcopy_json(payload.get("semantic_resolution") or {}),
            provenance=_deepcopy_json(payload.get("provenance") or {}),
            quality=_deepcopy_json(payload.get("quality") or {}),
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            updated_at=str(payload.get("updated_at") or _utc_now_iso()),
        )

    def clone(self) -> "AnalysisContext":
        return AnalysisContext.from_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "turn_no": self.turn_no,
            "status": self.status,
            "scope": _deepcopy_json(self.scope),
            "analysis_intent": _deepcopy_json(self.analysis_intent),
            "query_plan": normalize_query_plan(self.query_plan),
            "semantic_resolution": _deepcopy_json(self.semantic_resolution),
            "provenance": _deepcopy_json(self.provenance),
            "quality": _deepcopy_json(self.quality),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        payload["context_hash"] = context_hash(payload)
        return payload

    @property
    def hash(self) -> str:
        return self.to_dict()["context_hash"]


def empty_query_plan() -> dict[str, Any]:
    return {
        "subject": None,
        "metrics": [],
        "dimensions": [],
        "filters": [],
        "time": None,
        "comparison": {"mode": "none", "baseline": None},
        "order_by": [],
        "limit": None,
        "viz": {"requested": False, "chart_type": None},
        "postprocess": {},
    }


def normalize_query_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    normalized = empty_query_plan()
    for key, value in dict(plan).items():
        if key in normalized:
            normalized[key] = _deepcopy_json(value)
        else:
            normalized[key] = _deepcopy_json(value)
    normalized["metrics"] = list(normalized.get("metrics") or [])
    normalized["dimensions"] = list(normalized.get("dimensions") or [])
    normalized["filters"] = list(normalized.get("filters") or [])
    normalized["order_by"] = list(normalized.get("order_by") or [])
    normalized["comparison"] = normalized.get("comparison") or {"mode": "none", "baseline": None}
    normalized["viz"] = normalized.get("viz") or {"requested": False, "chart_type": None}
    normalized["postprocess"] = normalized.get("postprocess") or {}
    return normalized


def extract_analysis_context(response_data: Any) -> Optional[AnalysisContext]:
    if not isinstance(response_data, Mapping):
        return None
    payload = response_data.get(CONTEXT_RESPONSE_DATA_KEY)
    if not isinstance(payload, Mapping):
        return None
    try:
        return AnalysisContext.from_payload(payload)
    except (TypeError, ValueError):
        return None


def load_latest_analysis_context(
    session_mgr: Any,
    *,
    conversation_id: uuid.UUID,
    user_id: int,
    limit: int = 20,
) -> Optional[AnalysisContext]:
    """Load the latest assistant AnalysisContext from SessionManager messages.

    P0 uses agent_conversation_messages.response_data.analysis_context so no DB
    schema change is required.
    """
    messages = session_mgr.get_conversation_messages(
        conversation_id=conversation_id,
        user_id=user_id,
        limit=limit,
    )
    for message in reversed(messages):
        if getattr(message, "role", None) != "assistant":
            continue
        context = extract_analysis_context(getattr(message, "response_data", None))
        if context and context.status == "active":
            return context
    return None


def build_response_data_with_context(
    response_data: Optional[Mapping[str, Any]],
    *,
    analysis_context: AnalysisContext,
    query_plan_patch: Optional[Mapping[str, Any]] = None,
    quality_gate: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    payload = _deepcopy_json(dict(response_data or {}))
    payload[CONTEXT_RESPONSE_DATA_KEY] = analysis_context.to_dict()
    if query_plan_patch is not None:
        payload[PATCH_RESPONSE_DATA_KEY] = _deepcopy_json(dict(query_plan_patch))
    if quality_gate is not None:
        payload[QUALITY_RESPONSE_DATA_KEY] = _deepcopy_json(dict(quality_gate))
    return payload


def field_caption(spec: Mapping[str, Any]) -> str:
    return str(
        spec.get("field_caption")
        or spec.get("fieldCaption")
        or spec.get("name")
        or spec.get("semantic_name")
        or ""
    )


def names_for(specs: Iterable[Mapping[str, Any]]) -> list[str]:
    return [field_caption(spec) for spec in specs if field_caption(spec)]


def query_plan_summary(context_or_payload: AnalysisContext | Mapping[str, Any]) -> dict[str, Any]:
    payload = context_or_payload.to_dict() if isinstance(context_or_payload, AnalysisContext) else context_or_payload
    plan = normalize_query_plan(payload.get("query_plan") or {})
    return {
        "metrics": names_for(plan["metrics"]),
        "dimensions": names_for(plan["dimensions"]),
        "filters": [
            {
                "field_caption": field_caption(f),
                "operator": f.get("operator"),
                "value": f.get("value"),
            }
            for f in plan["filters"]
        ],
        "time": plan.get("time"),
        "comparison": plan.get("comparison"),
        "order_by": plan.get("order_by"),
        "limit": plan.get("limit"),
        "viz": plan.get("viz"),
        "postprocess": plan.get("postprocess"),
    }
