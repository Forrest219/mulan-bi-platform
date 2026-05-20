"""Response normalization for the Tableau MCP mainline.

This module is the single response-contract boundary for Tableau MCP agent
answers.  It intentionally returns the existing Agent contract shape:
``response_type`` and ``response_data`` as siblings, with no nested
``response_data.data`` wrapper.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from services.data_agent.table_display import infer_table_display_schema


RESPONSE_ASSET_CANDIDATES = "asset_candidates"
RESPONSE_ASSET_METADATA = "asset_metadata"
RESPONSE_ASSET_NOT_FOUND = "asset_not_found"
RESPONSE_QUERY_RESULT = "query_result"
RESPONSE_TOOL_UNAVAILABLE = "tool_unavailable"
RESPONSE_CLARIFICATION = "clarification"


@dataclass(frozen=True)
class TableauMcpEnvelope:
    response_type: str
    response_data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_type": self.response_type,
            "response_data": deepcopy(self.response_data),
        }


class TableauMcpResponseNormalizer:
    """Normalize Tableau MCP outputs into the Agent done-event contract."""

    def asset_candidates(
        self,
        *,
        candidates: Sequence[Mapping[str, Any]],
        query: str,
        source: str,
        reason: str,
        message: str,
        chain_mode: str,
        candidate_limit: int | None = 5,
        telemetry: Mapping[str, Any] | None = None,
    ) -> TableauMcpEnvelope:
        visible = list(candidates) if candidate_limit is None else list(candidates)[:candidate_limit]
        payload: dict[str, Any] = {
            "source": source,
            "chain_mode": chain_mode,
            "query": query,
            "reason": reason,
            "message": message,
            "total_count": len(candidates),
            "shown_count": len(visible),
            "candidates": [self.candidate(item) for item in visible],
        }
        if telemetry:
            payload["telemetry"] = dict(telemetry)
        return TableauMcpEnvelope(RESPONSE_ASSET_CANDIDATES, payload)

    def asset_not_found(
        self,
        *,
        query: str,
        message: str,
        chain_mode: str,
        source: str = "catalog_cache",
        candidates: Sequence[Mapping[str, Any]] | None = None,
        telemetry: Mapping[str, Any] | None = None,
    ) -> TableauMcpEnvelope:
        payload: dict[str, Any] = {
            "source": source,
            "chain_mode": chain_mode,
            "query": query,
            "message": message,
            "candidates": [self.candidate(item) for item in list(candidates or [])],
        }
        if telemetry:
            payload["telemetry"] = dict(telemetry)
        return TableauMcpEnvelope(RESPONSE_ASSET_NOT_FOUND, payload)

    def asset_metadata(
        self,
        *,
        source: str,
        chain_mode: str,
        datasource_luid: Any,
        datasource_name: Any,
        project_name: Any = None,
        description: Any = None,
        fields: Sequence[Mapping[str, Any]] | None = None,
        field_count: int | None = None,
        raw_field_count: int | None = None,
        field_groups: Sequence[Mapping[str, Any]] | None = None,
        analysis_suggestions: Sequence[Mapping[str, Any]] | None = None,
        metadata_quality: Mapping[str, Any] | None = None,
        metadata_freshness: Any = None,
        telemetry: Mapping[str, Any] | None = None,
    ) -> TableauMcpEnvelope:
        normalized_fields = [dict(field) for field in list(fields or [])]
        payload: dict[str, Any] = {
            "source": source,
            "chain_mode": chain_mode,
            "datasource_luid": datasource_luid,
            "datasource_name": datasource_name,
            "project_name": project_name,
            "description": description,
            "field_count": field_count if field_count is not None else len(normalized_fields),
            "raw_field_count": raw_field_count if raw_field_count is not None else len(normalized_fields),
            "fields": normalized_fields,
            "field_groups": [dict(group) for group in list(field_groups or [])],
            "analysis_suggestions": [dict(item) for item in list(analysis_suggestions or [])],
            "metadata_quality": dict(metadata_quality or {}),
            "metadata_freshness": metadata_freshness,
        }
        if telemetry:
            payload["telemetry"] = dict(telemetry)
        return TableauMcpEnvelope(RESPONSE_ASSET_METADATA, payload)

    def query_result(
        self,
        *,
        result: Mapping[str, Any],
        datasource: Mapping[str, Any],
        args: Mapping[str, Any],
        chain_mode: str,
        guardrail_payload: Mapping[str, Any] | None = None,
        source: str = "mcp",
        telemetry: Mapping[str, Any] | None = None,
    ) -> TableauMcpEnvelope:
        fields = list(result.get("fields") or [])
        rows = [list(row) if isinstance(row, (list, tuple)) else row for row in list(result.get("rows") or [])]
        metric_names = self.metric_names_from_args(args)
        payload = dict(result)
        payload.update({
            "source": source,
            "fields": fields,
            "rows": rows,
            "datasource_name": datasource.get("name") or datasource.get("datasource_name"),
            "datasource_luid": datasource.get("luid") or datasource.get("datasource_luid"),
            "chain_mode": chain_mode,
            "guardrail_decision": (guardrail_payload or {}).get("decision"),
            "guardrail_repairs": (guardrail_payload or {}).get("repairs") or [],
            "mcp_args": self.redact_large(dict(args)),
            "table_display": infer_table_display_schema(
                fields,
                rows,
                operator="mcp_proxy",
                metric_names=metric_names,
            ),
        })
        if telemetry:
            payload["telemetry"] = dict(telemetry)
        return TableauMcpEnvelope(RESPONSE_QUERY_RESULT, payload)

    def tool_unavailable(
        self,
        *,
        code: str,
        message: str,
        user_hint: str,
        chain_mode: str,
        detail: Mapping[str, Any] | None = None,
        telemetry: Mapping[str, Any] | None = None,
    ) -> TableauMcpEnvelope:
        payload: dict[str, Any] = {
            "source": "mcp",
            "chain_mode": chain_mode,
            "error_code": code,
            "message": message,
            "user_hint": user_hint,
            "detail": dict(detail or {}),
        }
        if telemetry:
            payload["telemetry"] = dict(telemetry)
        return TableauMcpEnvelope(RESPONSE_TOOL_UNAVAILABLE, payload)

    def clarification(
        self,
        *,
        message: str,
        chain_mode: str,
        reason: str,
        candidates: Sequence[Mapping[str, Any]] | None = None,
        detail: Mapping[str, Any] | None = None,
        telemetry: Mapping[str, Any] | None = None,
    ) -> TableauMcpEnvelope:
        payload: dict[str, Any] = {
            "source": "deterministic_compiler",
            "chain_mode": chain_mode,
            "reason": reason,
            "message": message,
            "candidates": [dict(item) for item in list(candidates or [])],
            "detail": dict(detail or {}),
        }
        if telemetry:
            payload["telemetry"] = dict(telemetry)
        return TableauMcpEnvelope(RESPONSE_CLARIFICATION, payload)

    @staticmethod
    def candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "asset_id": candidate.get("asset_id"),
            "datasource_luid": candidate.get("datasource_luid") or candidate.get("luid"),
            "name": candidate.get("name"),
            "project_name": candidate.get("project_name"),
            "field_count": candidate.get("field_count"),
            "synced_at": candidate.get("synced_at"),
        }

    @staticmethod
    def metric_names_from_args(args: Mapping[str, Any]) -> list[str]:
        query = args.get("query")
        if not isinstance(query, Mapping):
            return []
        names: list[str] = []
        for field in query.get("fields") or []:
            if not isinstance(field, Mapping):
                continue
            function = field.get("function") or field.get("aggregation")
            caption = field.get("fieldAlias") or field.get("fieldCaption") or field.get("fieldName") or field.get("name")
            if function and caption:
                names.append(str(caption))
        return names

    @staticmethod
    def unwrap_mcp_result(result: Any) -> dict[str, Any]:
        if isinstance(result, Mapping):
            if isinstance(result.get("response_data"), Mapping):
                return dict(result["response_data"])
            if isinstance(result.get("content"), list):
                return TableauMcpResponseNormalizer.payload_from_mcp_content(result.get("content") or [])
            return dict(result)
        return {"raw_result": result}

    @staticmethod
    def payload_from_mcp_content(content: Sequence[Any]) -> dict[str, Any]:
        for item in content:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, Mapping):
                    return dict(parsed)
        return {"content": list(content)}

    @staticmethod
    def redact_large(value: Any, *, max_chars: int = 4000) -> Any:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
        if len(text) <= max_chars:
            return value
        return {"truncated": True, "preview": text[:max_chars]}
