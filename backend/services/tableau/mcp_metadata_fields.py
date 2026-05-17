"""Shared helpers for Tableau MCP datasource metadata fields."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def normalize_field_name(value: Any) -> str:
    """Normalize a field name for conservative exact matching."""
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def field_display_name(field: Any) -> str:
    if isinstance(field, Mapping):
        for key in ("fieldCaption", "field_caption", "caption", "name", "fieldName", "field_name"):
            value = str(field.get(key) or "").strip()
            if value:
                return value
    value = str(field or "").strip()
    return value


def extract_mcp_field_metadata(metadata: Any) -> list[dict[str, Any]]:
    """Extract unique field payloads from observed Tableau MCP metadata shapes."""
    seen: set[str] = set()
    fields: list[dict[str, Any]] = []

    def add(item: Any) -> None:
        if isinstance(item, Mapping):
            payload = dict(item)
        else:
            payload = {"name": str(item or "").strip()}
        name = field_display_name(payload)
        normalized = normalize_field_name(name)
        if normalized and normalized not in seen:
            seen.add(normalized)
            fields.append(payload)

    def add_group_fields(groups: Any) -> None:
        if not isinstance(groups, list):
            return
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            for item in group.get("fields") or []:
                add(item)

    if isinstance(metadata, Mapping):
        for item in metadata.get("fields") or []:
            add(item)
        add_group_fields(metadata.get("fieldGroups"))
        raw = metadata.get("raw")
        if isinstance(raw, Mapping):
            for item in raw.get("fields") or []:
                add(item)
            add_group_fields(raw.get("fieldGroups"))
    elif isinstance(metadata, list):
        for item in metadata:
            add(item)

    return fields


def extract_queryable_fields_from_metadata(metadata: Any) -> list[str]:
    """Extract queryable field names from Tableau MCP metadata payloads."""
    candidates: list[str] = []
    seen: set[str] = set()

    def add_name(value: Any) -> None:
        name = str(value or "").strip()
        if not name:
            return
        normalized = normalize_field_name(name)
        if normalized in seen:
            return
        seen.add(normalized)
        candidates.append(name)

    for field in extract_mcp_field_metadata(metadata):
        add_name(field_display_name(field))

    return candidates
