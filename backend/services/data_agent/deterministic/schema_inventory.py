"""Schema inventory deterministic route."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

ASSET_TYPE_ORDER = {
    "datasource": 0,
    "view": 1,
    "workbook": 2,
    "flow": 3,
}
DEFAULT_PROJECT = "未分组"
MAX_ITEMS_PER_ASSET_TYPE = 100


@dataclass
class DeterministicRouteResult:
    """Route-level result returned to the agent stream integration layer."""

    answer: str
    response_data: dict[str, Any]
    tools_used: list[str]
    response_type: str
    steps_count: int
    tool_name: str
    tool_params: dict[str, Any]
    tool_result_summary: str
    skill_version_id: str | None


def build_schema_inventory_tool_params(question: str | None) -> dict[str, Any]:
    """Return the exact schema tool params implied by a deterministic schema question."""
    request = _classify_schema_request(question or "")
    tool_params: dict[str, Any] = {}
    if request["mode"] == "fields" and request.get("table_name"):
        tool_params["table_name"] = request["table_name"]
    elif request["mode"] == "assets":
        tool_params["include_all_asset_types"] = True
    return tool_params


async def run_schema_inventory_route(
    registry: Any,
    context: Any,
    active_skill_version: Any | None = None,
    question: str | None = None,
) -> DeterministicRouteResult:
    """Run schema inventory through the registered schema tool only."""
    request = _classify_schema_request(question or "")
    tool_params = build_schema_inventory_tool_params(question)
    tool_result = await registry.get("schema").execute(params=tool_params, context=context)
    if not getattr(tool_result, "success", False):
        error = getattr(tool_result, "error", None) or "schema tool failed"
        raise ValueError(error)

    payload = normalize_schema_inventory(getattr(tool_result, "data", None), request=request)
    validate_schema_inventory_payload(payload)
    answer = render_schema_inventory_markdown(payload)
    return DeterministicRouteResult(
        answer=answer,
        response_data=payload,
        tools_used=["schema"],
        response_type="schema_inventory",
        steps_count=4,
        tool_name="schema",
        tool_params=tool_params,
        tool_result_summary=_summarize_payload(payload),
        skill_version_id=_get_version_id(active_skill_version),
    )


def normalize_schema_inventory(
    tool_data: Any,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize schema tool output into a stable, sorted inventory payload."""
    if not isinstance(tool_data, dict):
        raise ValueError("schema inventory tool_data must be a dict")
    request = request or {"mode": "datasources"}

    if request.get("mode") == "fields" or tool_data.get("requested_table_name"):
        return _normalize_schema_fields(tool_data)

    assets = [_normalize_asset(item) for item in _extract_assets(tool_data)]
    assets = [asset for asset in assets if asset is not None]
    if request.get("mode") != "assets":
        assets = [asset for asset in assets if asset["asset_type"] == "datasource"]
    assets.sort(key=_asset_sort_key)

    groups: list[dict[str, Any]] = []
    for asset_type in _ordered_asset_types(assets):
        type_assets = [asset for asset in assets if asset["asset_type"] == asset_type]
        shown_assets = type_assets[:MAX_ITEMS_PER_ASSET_TYPE]
        total_count = len(type_assets)
        shown_count = len(shown_assets)
        groups.append(
            {
                "asset_type": asset_type,
                "total_count": total_count,
                "shown_count": shown_count,
                "omitted_count": total_count - shown_count,
                "items": shown_assets,
            }
        )

    total_count = len(assets)
    shown_count = sum(group["shown_count"] for group in groups)
    return {
        "connection_id": tool_data.get("connection_id"),
        "connection_name": tool_data.get("datasource_name") or tool_data.get("connection_name"),
        "db_type": tool_data.get("db_type"),
        "mode": request.get("mode") or "datasources",
        "total_count": total_count,
        "shown_count": shown_count,
        "omitted_count": total_count - shown_count,
        "asset_types": groups,
        "assets": [asset for group in groups for asset in group["items"]],
    }


def render_schema_inventory_markdown(payload: dict[str, Any]) -> str:
    """Render a deterministic Markdown answer for a normalized inventory payload."""
    validate_schema_inventory_payload(payload)
    if payload.get("mode") == "fields":
        return _render_schema_fields_markdown(payload)

    connection_name = payload.get("connection_name") or "当前连接"
    asset_label = "数据资产" if payload.get("mode") == "assets" else "Tableau datasource"
    lines = [
        f"## {connection_name} 数据源清单",
        "",
        f"共 {payload['total_count']} 个{asset_label}，展示 {payload['shown_count']} 个，省略 {payload['omitted_count']} 个。",
    ]
    for group in payload["asset_types"]:
        lines.extend(
            [
                "",
                f"### {group['asset_type']} ({group['shown_count']}/{group['total_count']})",
            ]
        )
        for item in group["items"]:
            project = item["project"]
            name = item["name"]
            url = item.get("web_url")
            if url:
                lines.append(f"- [{project}] {name} - {url}")
            else:
                lines.append(f"- [{project}] {name}")
        if group["omitted_count"]:
            lines.append(f"- 省略 {group['omitted_count']} 个 {group['asset_type']} 资产")
    return "\n".join(lines)


def validate_schema_inventory_payload(payload: dict[str, Any]) -> None:
    """Validate normalized inventory payload invariants."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    if payload.get("mode") == "fields":
        _validate_fields_payload(payload)
        return
    for key in ("total_count", "shown_count", "omitted_count"):
        _require_non_negative_int(payload, key)
    if payload["shown_count"] > payload["total_count"]:
        raise ValueError("shown_count cannot exceed total_count")
    if payload["omitted_count"] != payload["total_count"] - payload["shown_count"]:
        raise ValueError("omitted_count must equal total_count - shown_count")

    groups = payload.get("asset_types")
    if not isinstance(groups, list):
        raise ValueError("asset_types must be a list")

    flattened_assets = []
    for group in groups:
        _validate_group(group)
        flattened_assets.extend(group["items"])

    if len(flattened_assets) != payload["shown_count"]:
        raise ValueError("shown_count must equal rendered item count")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("assets must be a list")
    if assets != flattened_assets:
        raise ValueError("assets must match grouped rendered items")


def _extract_assets(tool_data: dict[str, Any]) -> list[Any]:
    for key in ("assets", "tables", "datasources"):
        value = tool_data.get(key)
        if isinstance(value, list):
            return value
    return []


def _normalize_schema_fields(tool_data: dict[str, Any]) -> dict[str, Any]:
    fields_by_asset = tool_data.get("fields")
    asset_name = None
    raw_fields: list[Any] = []
    if isinstance(fields_by_asset, dict):
        for candidate_name, candidate_fields in fields_by_asset.items():
            if isinstance(candidate_fields, list):
                asset_name = str(candidate_name)
                raw_fields = candidate_fields
                break

    matched_asset = tool_data.get("matched_asset")
    if not isinstance(matched_asset, dict):
        matched_asset = {}

    fields = [_normalize_field(field) for field in raw_fields]
    fields = [field for field in fields if field is not None]
    filtered_fields = [field for field in fields if not _is_logic_table_id_field(field)]
    if filtered_fields:
        fields = filtered_fields

    field_count = len(fields)
    requested_field_count = tool_data.get("field_count")
    if not isinstance(requested_field_count, int):
        requested_field_count = len(raw_fields)

    return {
        "connection_id": tool_data.get("connection_id"),
        "connection_name": tool_data.get("datasource_name") or tool_data.get("connection_name"),
        "db_type": tool_data.get("db_type"),
        "mode": "fields",
        "requested_table_name": tool_data.get("requested_table_name"),
        "matched_asset": {
            "name": matched_asset.get("name") or asset_name,
            "asset_type": matched_asset.get("asset_type") or matched_asset.get("type"),
            "project": matched_asset.get("project") or matched_asset.get("project_name"),
            "web_url": matched_asset.get("web_url"),
            "tableau_id": matched_asset.get("tableau_id"),
        },
        "field_count": field_count,
        "raw_field_count": requested_field_count,
        "fields": fields,
        "warning": tool_data.get("warning") if isinstance(tool_data.get("warning"), str) else None,
    }


def _normalize_field(field: Any) -> dict[str, Any] | None:
    if not isinstance(field, dict):
        name = str(field).strip()
        if not name:
            return None
        return {
            "name": name,
            "caption": None,
            "display_name": name,
            "data_type": None,
            "role": None,
            "is_calculated": None,
        }

    name = _strip_tableau_brackets(field.get("name") or field.get("field_name"))
    caption = _strip_tableau_brackets(field.get("caption") or field.get("field_caption"))
    display_name = caption or name
    if not display_name:
        return None
    return {
        "name": name or None,
        "caption": caption or None,
        "display_name": display_name,
        "data_type": field.get("data_type") if isinstance(field.get("data_type"), str) else None,
        "role": field.get("role") if isinstance(field.get("role"), str) else None,
        "is_calculated": field.get("is_calculated") if isinstance(field.get("is_calculated"), bool) else None,
    }


def _normalize_asset(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    asset_type = item.get("asset_type") or item.get("type") or "other"
    if not isinstance(asset_type, str) or not asset_type.strip():
        asset_type = "other"
    project = item.get("project") or item.get("project_name") or DEFAULT_PROJECT
    if not isinstance(project, str) or not project.strip():
        project = DEFAULT_PROJECT
    return {
        "asset_type": asset_type.strip(),
        "project": project.strip(),
        "name": name.strip(),
        "web_url": item.get("web_url") if isinstance(item.get("web_url"), str) else None,
        "tableau_id": item.get("tableau_id") if isinstance(item.get("tableau_id"), str) else None,
    }


def _render_schema_fields_markdown(payload: dict[str, Any]) -> str:
    matched_asset = payload.get("matched_asset") if isinstance(payload.get("matched_asset"), dict) else {}
    display_name = matched_asset.get("name") or payload.get("requested_table_name") or "该数据资产"
    fields = payload.get("fields") if isinstance(payload.get("fields"), list) else []

    if not fields:
        return f"未找到 **{display_name}** 的字段信息。"

    lines = [
        f"数据资产 **{display_name}** 返回了 **{payload['field_count']} 个字段**：",
        "",
        "| 序号 | 字段名称 | 类型 | 角色 | 计算字段 |",
        "|---:|---|---|---|---|",
    ]
    for index, field in enumerate(fields, start=1):
        name = _escape_markdown_table_cell(
            str(field.get("display_name") or field.get("caption") or field.get("name") or "")
        )
        data_type = _escape_markdown_table_cell(str(field.get("data_type") or "")) or "-"
        role = _escape_markdown_table_cell(str(field.get("role") or "")) or "-"
        is_calculated = (
            "是"
            if field.get("is_calculated") is True
            else ("否" if field.get("is_calculated") is False else "-")
        )
        lines.append(f"| {index} | {name} | {data_type} | {role} | {is_calculated} |")

    web_url = matched_asset.get("web_url")
    if web_url:
        lines.extend(["", f"资产链接：{web_url}"])

    warning = payload.get("warning")
    if warning:
        lines.extend(["", f"注意：{warning}"])

    return "\n".join(lines)


def _ordered_asset_types(assets: list[dict[str, Any]]) -> list[str]:
    seen = {asset["asset_type"] for asset in assets}
    return sorted(seen, key=lambda asset_type: (ASSET_TYPE_ORDER.get(asset_type, 99), asset_type.casefold()))


def _asset_sort_key(asset: dict[str, Any]) -> tuple[int, str, str]:
    asset_type = asset["asset_type"]
    return (ASSET_TYPE_ORDER.get(asset_type, 99), asset["project"], asset["name"].casefold())


def _validate_group(group: Any) -> None:
    if not isinstance(group, dict):
        raise ValueError("asset type group must be a dict")
    asset_type = group.get("asset_type")
    if not isinstance(asset_type, str) or not asset_type:
        raise ValueError("group asset_type must be a non-empty string")
    for key in ("total_count", "shown_count", "omitted_count"):
        _require_non_negative_int(group, key)
    if group["shown_count"] > group["total_count"]:
        raise ValueError("group shown_count cannot exceed total_count")
    if group["omitted_count"] != group["total_count"] - group["shown_count"]:
        raise ValueError("group omitted_count must equal total_count - shown_count")
    items = group.get("items")
    if not isinstance(items, list):
        raise ValueError("group items must be a list")
    if len(items) != group["shown_count"]:
        raise ValueError("group shown_count must equal item count")
    if group["shown_count"] > MAX_ITEMS_PER_ASSET_TYPE:
        raise ValueError("group shown_count exceeds display limit")
    for item in items:
        _validate_asset(item)


def _validate_asset(item: Any) -> None:
    if not isinstance(item, dict):
        raise ValueError("asset item must be a dict")
    for key in ("asset_type", "project", "name"):
        value = item.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"asset {key} must be a non-empty string")
    for key in ("web_url", "tableau_id"):
        value = item.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"asset {key} must be a string or None")


def _validate_fields_payload(payload: dict[str, Any]) -> None:
    _require_non_negative_int(payload, "field_count")
    _require_non_negative_int(payload, "raw_field_count")
    fields = payload.get("fields")
    if not isinstance(fields, list):
        raise ValueError("fields must be a list")
    if len(fields) != payload["field_count"]:
        raise ValueError("field_count must equal rendered field count")
    matched_asset = payload.get("matched_asset")
    if not isinstance(matched_asset, dict):
        raise ValueError("matched_asset must be a dict")
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError("field item must be a dict")
        display_name = field.get("display_name")
        if not isinstance(display_name, str) or not display_name:
            raise ValueError("field display_name must be a non-empty string")
        for key in ("name", "caption", "data_type", "role"):
            value = field.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"field {key} must be a string or None")
        is_calculated = field.get("is_calculated")
        if is_calculated is not None and not isinstance(is_calculated, bool):
            raise ValueError("field is_calculated must be a bool or None")


def _require_non_negative_int(payload: dict[str, Any], key: str) -> None:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")


def _get_version_id(active_skill_version: Any | None) -> str | None:
    if active_skill_version is None:
        return None
    if isinstance(active_skill_version, dict):
        version_id = active_skill_version.get("version_id")
    else:
        version_id = getattr(active_skill_version, "version_id", None)
    return str(version_id) if version_id is not None else None


def _summarize_payload(payload: dict[str, Any]) -> str:
    if payload.get("mode") == "fields":
        matched_asset = payload.get("matched_asset") if isinstance(payload.get("matched_asset"), dict) else {}
        return (
            f"mode=fields, asset={matched_asset.get('name') or payload.get('requested_table_name')}, "
            f"fields={payload['field_count']}, raw_fields={payload['raw_field_count']}"
        )[:500]
    parts = [
        f"mode={payload.get('mode') or 'datasources'}",
        f"total={payload['total_count']}",
        f"shown={payload['shown_count']}",
        f"omitted={payload['omitted_count']}",
    ]
    for group in payload["asset_types"]:
        parts.append(f"{group['asset_type']}={group['total_count']}")
    return ", ".join(parts)[:500]


def _classify_schema_request(question: str) -> dict[str, Any]:
    normalized = _normalize_text(question)
    if _is_field_question(normalized):
        return {"mode": "fields", "table_name": _extract_table_name(question)}
    if _asks_for_assets(normalized):
        return {"mode": "assets"}
    return {"mode": "datasources"}


def _is_field_question(normalized: str) -> bool:
    return any(
        keyword in normalized
        for keyword in ("字段", "field", "fields", "column", "columns", "表结构", "数据结构")
    )


def _asks_for_assets(normalized: str) -> bool:
    return any(keyword in normalized for keyword in ("资产", "视图", "view", "views", "workbook", "workbooks"))


def _extract_table_name(question: str) -> str | None:
    text = unicodedata.normalize("NFKC", question or "").strip()
    if not text:
        return None
    text = re.sub(
        r"(?i)\b(tableau|schema|fields?|columns?|show|list|what|which|exist|available)\b",
        " ",
        text,
    )
    text = re.sub(r"(请|帮我|查看|查询|看一下|一下|当前连接|数据资产|数据源|表结构|数据结构|字段列表)", " ", text)
    text = re.sub(r"(有哪些字段|字段有哪些|有哪些列|列有哪些|字段是什么|的字段是什么|有什么字段|包含哪些字段)", " ", text)
    text = re.sub(r"[？?。！!,，：:；;]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _strip_tableau_brackets(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    if len(stripped) >= 2 and stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1].strip()
    return stripped


def _is_logic_table_id_field(field: dict[str, Any]) -> bool:
    value = field.get("display_name")
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return re.fullmatch(r"[A-Za-z]+_[0-9A-Fa-f]{12,}(?:_[A-Za-z0-9]+)?", stripped) is not None


def _escape_markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
