"""Guardrail for transparent MCP args before execution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Literal

import jsonschema

GuardrailDecision = Literal["allow", "repair", "reject"]

DEFAULT_LIMIT = 100
MAX_LIMIT = 100
MAX_RESULT_FIELDS = 20

FIELD_KEYS = frozenset({"fieldCaption", "fieldName", "field", "name", "caption"})
FIELD_CONTAINER_KEYS = frozenset({"fields", "dimensions", "metrics", "filters", "order_by", "sort"})
ENUM_KEYS = frozenset({"sortDirection", "direction", "sort_direction", "order", "operator", "filterType"})
LIMIT_KEYS = frozenset({"limit", "max_rows", "maxRows"})
DATASOURCE_KEYS = frozenset({"datasource_luid", "datasourceLuid", "datasource_id", "datasourceId"})
CONNECTION_KEYS = frozenset({"connection_id", "connectionId"})
DANGEROUS_OPERATIONS = frozenset(
    {
        "delete",
        "drop",
        "truncate",
        "insert",
        "update",
        "upsert",
        "merge",
        "alter",
        "create",
        "execute_sql",
        "raw_sql",
        "ddl",
        "dml",
    }
)
DANGEROUS_SQL_TOKENS = (
    " delete ",
    " drop ",
    " truncate ",
    " insert ",
    " update ",
    " upsert ",
    " merge ",
    " alter ",
    " create ",
)
NEGATIVE_QUESTION_MARKERS = ("没有", "未发生", "未购买", "未下单", "流失", "不活跃")
POSITIVE_ARG_MARKERS = ("top", "desc", "发生销售", "有销售")


@dataclass(frozen=True)
class McpArgsGuardrailInput:
    """Input contract for MCP args guardrail validation."""

    question: str
    tool_name: str
    tool_schema: dict[str, Any]
    args: dict[str, Any]
    queryable_fields: list[str]
    current_datasource: dict[str, Any]
    user_context: dict[str, Any]


@dataclass(frozen=True)
class McpArgsRepair:
    """A deterministic repair applied to MCP args."""

    type: str
    path: str
    before: Any
    after: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable repair payload."""
        return asdict(self)


@dataclass(frozen=True)
class McpArgsGuardrailResult:
    """Output contract for MCP args guardrail validation."""

    decision: GuardrailDecision
    args: dict[str, Any] | None
    repairs: list[McpArgsRepair]
    reject_code: str | None
    message: str
    user_hint: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable guardrail result."""
        return {
            "decision": self.decision,
            "args": self.args,
            "repairs": [repair.to_dict() for repair in self.repairs],
            "reject_code": self.reject_code,
            "message": self.message,
            "user_hint": self.user_hint,
        }


def validate_mcp_args(request: McpArgsGuardrailInput) -> McpArgsGuardrailResult:  # noqa: PLR0911
    """Validate and conservatively repair MCP args.

    The guardrail is intentionally not a planner. It never adds business metrics,
    rewrites the question, decomposes metrics, or changes business operators.
    """
    if not isinstance(request.tool_schema, dict) or not isinstance(request.args, dict):
        return _reject(
            "MCP_ARGS_SCHEMA_INVALID",
            "MCP 参数或 schema 不是合法对象。",
            "请重新生成结构化查询参数后再试。",
        )

    try:
        jsonschema.Draft7Validator.check_schema(request.tool_schema)
    except jsonschema.SchemaError:
        return _reject(
            "MCP_ARGS_SCHEMA_INVALID",
            "MCP tool schema 不合法，无法安全执行。",
            "请联系管理员检查工具 schema 配置。",
        )

    args = deepcopy(request.args)
    repairs: list[McpArgsRepair] = []

    unsafe_operation = _find_unsafe_operation(request.tool_name, args)
    if unsafe_operation:
        return _reject(
            "MCP_ARGS_UNSAFE_OPERATION",
            f"已阻止危险操作：{unsafe_operation}。",
            "只能执行只读、受控的数据查询。",
        )

    permission_error = _validate_datasource_permission(args, request.current_datasource, request.user_context)
    if permission_error:
        return _reject(*permission_error)

    limit_error = _repair_limit(args, request.tool_schema, repairs)
    if limit_error:
        return _reject(*limit_error)

    enum_error = _repair_enum_case(args, request.tool_schema, repairs)
    if enum_error:
        return _reject(*enum_error)

    field_error = _repair_and_validate_fields(args, request.queryable_fields, request.current_datasource, repairs)
    if field_error:
        return _reject(*field_error)

    detail_error = _validate_detail_scan(request.question, args, request.args)
    if detail_error:
        return _reject(*detail_error)

    too_wide_error = _validate_result_width(args)
    if too_wide_error:
        return _reject(*too_wide_error)

    semantic_error = _validate_directional_semantics(request.question, args)
    if semantic_error:
        return _reject(*semantic_error)

    try:
        jsonschema.validate(instance=args, schema=request.tool_schema)
    except jsonschema.ValidationError as exc:
        return _reject(
            "MCP_ARGS_SCHEMA_INVALID",
            f"MCP 参数不符合工具 schema：{exc.message}",
            "请调整查询参数后再试。",
        )

    if repairs:
        return McpArgsGuardrailResult(
            decision="repair",
            args=args,
            repairs=repairs,
            reject_code=None,
            message="MCP 参数已完成安全修复。",
            user_hint="已应用确定性的安全修复后继续查询。",
        )
    return McpArgsGuardrailResult(
        decision="allow",
        args=args,
        repairs=[],
        reject_code=None,
        message="MCP 参数通过安全检查。",
        user_hint="",
    )


def _reject(code: str, message: str, user_hint: str) -> McpArgsGuardrailResult:
    return McpArgsGuardrailResult(
        decision="reject",
        args=None,
        repairs=[],
        reject_code=code,
        message=message,
        user_hint=user_hint,
    )


def _schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _schema_has_limit(schema: dict[str, Any]) -> bool:
    return any(key in _schema_properties(schema) for key in LIMIT_KEYS)


def _repair_limit(args: dict[str, Any], schema: dict[str, Any], repairs: list[McpArgsRepair]) -> tuple[str, str, str] | None:
    limit_path = _find_first_key_path(args, LIMIT_KEYS)
    if limit_path is None:
        if not _schema_has_limit(schema):
            return (
                "MCP_ARGS_LIMIT_REQUIRED",
                "查询缺少 limit，且工具 schema 不支持安全补齐 limit。",
                "请指定一个明确的返回行数上限。",
            )
        args["limit"] = DEFAULT_LIMIT
        repairs.append(
            McpArgsRepair(
                type="limit_default",
                path="limit",
                before=None,
                after=DEFAULT_LIMIT,
                reason="schema supports limit and args omitted it",
            )
        )
        return None

    value = _get_path(args, limit_path)
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return (
            "MCP_ARGS_SCHEMA_INVALID",
            "limit 必须是整数。",
            "请指定一个明确的整数 limit。",
        )
    if limit <= 0:
        return (
            "MCP_ARGS_SCHEMA_INVALID",
            "limit 必须大于 0。",
            "请指定一个大于 0 的返回行数上限。",
        )
    if limit > MAX_LIMIT:
        _set_path(args, limit_path, MAX_LIMIT)
        repairs.append(
            McpArgsRepair(
                type="limit_clamp",
                path=_format_path(limit_path),
                before=value,
                after=MAX_LIMIT,
                reason="limit exceeds guardrail maximum",
            )
        )
    return None


def _repair_enum_case(
    args: dict[str, Any],
    schema: dict[str, Any],
    repairs: list[McpArgsRepair],
) -> tuple[str, str, str] | None:
    enum_by_key = {
        key: prop["enum"]
        for key, prop in _schema_properties(schema).items()
        if isinstance(prop, dict) and isinstance(prop.get("enum"), list)
    }
    if not enum_by_key:
        return None

    for path, key, value in _walk_key_values(args):
        if key not in enum_by_key or not isinstance(value, str):
            continue
        enum_values = enum_by_key[key]
        exact_values = [item for item in enum_values if item == value]
        if exact_values:
            continue
        matches = [item for item in enum_values if isinstance(item, str) and item.lower() == value.lower()]
        if len(matches) == 1:
            _set_path(args, path, matches[0])
            repairs.append(
                McpArgsRepair(
                    type="enum_case",
                    path=_format_path(path),
                    before=value,
                    after=matches[0],
                    reason="enum value differs only by case",
                )
            )
    return None


def _repair_and_validate_fields(
    args: dict[str, Any],
    queryable_fields: list[str],
    current_datasource: dict[str, Any],
    repairs: list[McpArgsRepair],
) -> tuple[str, str, str] | None:
    canonical_by_normalized = {_normalize_field(field): field for field in queryable_fields if field}
    synonyms = _field_synonyms(current_datasource)

    for path, value in _iter_field_values(args):
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = _normalize_field(value)
        if normalized in canonical_by_normalized:
            canonical = canonical_by_normalized[normalized]
            if canonical != value:
                _set_path(args, path, canonical)
                repairs.append(
                    McpArgsRepair(
                        type="field_case",
                        path=_format_path(path),
                        before=value,
                        after=canonical,
                        reason="field differs only by case or whitespace",
                    )
                )
            continue

        synonym_matches = [
            candidate
            for candidate in synonyms.get(value, [])
            if _normalize_field(candidate) in canonical_by_normalized
        ]
        if len(synonym_matches) == 1:
            repaired = canonical_by_normalized[_normalize_field(synonym_matches[0])]
            _set_path(args, path, repaired)
            repairs.append(
                McpArgsRepair(
                    type="field_mapping",
                    path=_format_path(path),
                    before=value,
                    after=repaired,
                    reason="requested field has a unique safe synonym in queryable fields",
                )
            )
            continue

        return (
            "MCP_ARGS_UNKNOWN_FIELD",
            f"字段不存在或不可查询：{value}",
            "请改用当前数据源中可查询的字段。",
        )
    return None


def _field_synonyms(current_datasource: dict[str, Any]) -> dict[str, list[str]]:
    raw = current_datasource.get("field_synonyms") or current_datasource.get("safe_field_synonyms") or {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            result[str(key)] = [value]
        elif isinstance(value, list):
            result[str(key)] = [str(item) for item in value if str(item).strip()]
    return result


def _validate_datasource_permission(
    args: dict[str, Any],
    current_datasource: dict[str, Any],
    user_context: dict[str, Any],
) -> tuple[str, str, str] | None:
    requested_datasource = _first_value_for_keys(args, DATASOURCE_KEYS)
    current_luid = (
        current_datasource.get("luid")
        or current_datasource.get("datasource_luid")
        or current_datasource.get("tableau_id")
        or current_datasource.get("id")
    )
    accessible = user_context.get("accessible_datasource_luids")
    if accessible is None and current_luid:
        accessible = [current_luid]
    if requested_datasource and accessible is not None and requested_datasource not in set(accessible):
        return (
            "MCP_ARGS_DATASOURCE_FORBIDDEN",
            "请求的数据源不在当前用户可访问范围内。",
            "请切换到有权限的数据源后再查询。",
        )
    if requested_datasource and current_luid and requested_datasource != current_luid:
        return (
            "MCP_ARGS_DATASOURCE_FORBIDDEN",
            "请求的数据源与当前会话数据源不一致。",
            "请使用当前数据源重新发起查询。",
        )

    requested_connection = _first_value_for_keys(args, CONNECTION_KEYS)
    current_connection = current_datasource.get("connection_id") or user_context.get("connection_id")
    accessible_connections = user_context.get("accessible_connection_ids")
    if accessible_connections is None and current_connection is not None:
        accessible_connections = [current_connection]
    if (
        requested_connection is not None
        and accessible_connections is not None
        and requested_connection not in set(accessible_connections)
    ):
        return (
            "MCP_ARGS_DATASOURCE_FORBIDDEN",
            "请求的连接不在当前用户可访问范围内。",
            "请使用有权限的连接重新查询。",
        )
    if requested_connection is not None and current_connection is not None and requested_connection != current_connection:
        return (
            "MCP_ARGS_DATASOURCE_FORBIDDEN",
            "请求的连接与当前会话连接不一致。",
            "请使用当前连接重新发起查询。",
        )
    return None


def _find_unsafe_operation(tool_name: str, args: dict[str, Any]) -> str | None:
    normalized_tool = _normalize_token(tool_name)
    if normalized_tool in DANGEROUS_OPERATIONS:
        return tool_name

    for _path, key, value in _walk_key_values(args):
        normalized_key = _normalize_token(key)
        if normalized_key in {"operation", "op", "action", "query_type", "querytype"}:
            normalized_value = _normalize_token(str(value))
            if normalized_value in DANGEROUS_OPERATIONS:
                return str(value)
        if normalized_key in {"sql", "query", "statement"} and isinstance(value, str):
            padded = f" {value.lower()} "
            if any(token in padded for token in DANGEROUS_SQL_TOKENS):
                return key
    return None


def _validate_detail_scan(question: str, args: dict[str, Any], original_args: dict[str, Any]) -> tuple[str, str, str] | None:
    if not _looks_like_detail_scan(args):
        return None
    original_limit_path = _find_first_key_path(original_args, LIMIT_KEYS)
    current_limit_path = _find_first_key_path(args, LIMIT_KEYS)
    current_limit = _get_path(args, current_limit_path) if current_limit_path else None
    if original_limit_path is None or current_limit is None or int(current_limit) >= MAX_LIMIT:
        return (
            "MCP_ARGS_UNSAFE_DETAIL_SCAN",
            "已阻止未受控的明细扫描。",
            "请改为聚合查询，或明确缩小筛选条件和返回行数。",
        )
    if _is_aggregate_question(question) and not _has_aggregate_field(args):
        return (
            "MCP_ARGS_UNSAFE_DETAIL_SCAN",
            "聚合类问题不能执行明细扫描。",
            "请让查询参数包含聚合字段和明确的返回上限。",
        )
    return None


def _validate_result_width(args: dict[str, Any]) -> tuple[str, str, str] | None:
    max_width = 0
    for value in _values_for_key(args, "fields"):
        if isinstance(value, list):
            max_width = max(max_width, len(value))
    if max_width > MAX_RESULT_FIELDS:
        return (
            "MCP_ARGS_RESULT_TOO_WIDE",
            f"查询结果字段数过多：{max_width}。",
            "请减少返回字段数量后再试。",
        )
    return None


def _validate_directional_semantics(question: str, args: dict[str, Any]) -> tuple[str, str, str] | None:
    compact_question = question.replace(" ", "")
    if not any(marker in compact_question for marker in NEGATIVE_QUESTION_MARKERS):
        return None
    flattened = " ".join(str(value).lower() for _path, _key, value in _walk_key_values(args))
    if any(marker in flattened for marker in POSITIVE_ARG_MARKERS):
        return (
            "MCP_ARGS_SEMANTIC_MISMATCH",
            "用户问题与查询参数方向可能相反，已停止执行。",
            "请重新生成能表达“未发生/没有”的查询参数。",
        )
    return None


def _looks_like_detail_scan(args: dict[str, Any]) -> bool:
    result_shape = _first_value_for_keys(args, {"result_shape", "resultShape", "query_shape", "queryShape"})
    if isinstance(result_shape, str) and result_shape.lower() in {"detail_table", "detail", "raw_rows", "records"}:
        return True
    operation = _first_value_for_keys(args, {"operation", "op", "query_type", "queryType"})
    if isinstance(operation, str) and operation.lower() in {"detail", "list", "records", "raw_rows"}:
        return True
    return False


def _is_aggregate_question(question: str) -> bool:
    return any(token in question for token in ("多少", "总计", "合计", "汇总", "统计", "排名", "Top", "top", "趋势"))


def _has_aggregate_field(args: dict[str, Any]) -> bool:
    aggregate_functions = {"sum", "avg", "average", "count", "countd", "min", "max"}
    for _path, key, value in _walk_key_values(args):
        if key in {"function", "aggregation", "agg"} and str(value).lower() in aggregate_functions:
            return True
    return False


def _iter_field_values(node: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], Any]]:
    found: list[tuple[tuple[Any, ...], Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = (*path, key)
            if key in FIELD_KEYS and isinstance(value, str) and _is_field_context(path, key):
                found.append((next_path, value))
            elif key in FIELD_CONTAINER_KEYS:
                found.extend(_iter_field_values(value, next_path))
            elif isinstance(value, (dict, list)):
                found.extend(_iter_field_values(value, next_path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            next_path = (*path, index)
            if isinstance(item, str) and path and str(path[-1]) in {"fields", "dimensions", "metrics"}:
                found.append((next_path, item))
            else:
                found.extend(_iter_field_values(item, next_path))
    return found


def _is_field_context(path: tuple[Any, ...], key: str) -> bool:
    if key in {"fieldCaption", "fieldName"}:
        return True
    return bool(path and str(path[-1]) in FIELD_CONTAINER_KEYS)


def _walk_key_values(node: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], str, Any]]:
    found: list[tuple[tuple[Any, ...], str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = (*path, key)
            found.append((next_path, str(key), value))
            if isinstance(value, (dict, list)):
                found.extend(_walk_key_values(value, next_path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            if isinstance(item, (dict, list)):
                found.extend(_walk_key_values(item, (*path, index)))
    return found


def _find_first_key_path(node: Any, keys: frozenset[str] | set[str], path: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = (*path, key)
            if key in keys:
                return next_path
            nested = _find_first_key_path(value, keys, next_path)
            if nested:
                return nested
    elif isinstance(node, list):
        for index, item in enumerate(node):
            nested = _find_first_key_path(item, keys, (*path, index))
            if nested:
                return nested
    return None


def _values_for_key(node: Any, key: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(node, dict):
        for item_key, value in node.items():
            if item_key == key:
                values.append(value)
            if isinstance(value, (dict, list)):
                values.extend(_values_for_key(value, key))
    elif isinstance(node, list):
        for item in node:
            values.extend(_values_for_key(item, key))
    return values


def _first_value_for_keys(node: Any, keys: frozenset[str] | set[str]) -> Any:
    path = _find_first_key_path(node, keys)
    if path is None:
        return None
    return _get_path(node, path)


def _get_path(node: Any, path: tuple[Any, ...]) -> Any:
    current = node
    for item in path:
        current = current[item]
    return current


def _set_path(node: Any, path: tuple[Any, ...], value: Any) -> None:
    current = node
    for item in path[:-1]:
        current = current[item]
    current[path[-1]] = value


def _format_path(path: tuple[Any, ...]) -> str:
    return ".".join(str(item) for item in path)


def _normalize_field(value: str) -> str:
    return value.strip().lower().replace(" ", "").replace("　", "").replace("\u00a0", "")


def _normalize_token(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")
