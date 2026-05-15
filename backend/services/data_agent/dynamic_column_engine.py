"""Registry-backed derived column calculation for Data Agent table responses."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


_REGISTRY_ENV = "DATA_AGENT_DERIVED_METRICS_REGISTRY"
_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "data_agent_derived_metrics.yaml"


@dataclass(slots=True)
class DerivedColumnResult:
    fields: list[Any]
    rows: list[list[Any]]
    metadata: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]


class FormulaEvaluationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def append_derived_columns(
    fields: list[Any],
    rows: list[Any],
    *,
    requested_metric_names: list[str] | set[str] | tuple[str, ...],
    registry_path: str | Path | None = None,
) -> DerivedColumnResult:
    """Append requested derived metrics using formulas from the YAML registry."""

    output_fields = list(fields or [])
    output_rows = [_copy_row(row) for row in (rows or [])]
    requested_names = _ordered_names(requested_metric_names)
    if not requested_names:
        return DerivedColumnResult(output_fields, output_rows, [], [])

    definitions = _load_registry(registry_path)
    metadata: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for requested_name in requested_names:
        definition = definitions.get(_key(requested_name))
        if not definition:
            diagnostic = {
                "name": requested_name,
                "status": "registry_missing",
                "message": "requested derived metric is not defined in registry",
            }
            metadata.append(diagnostic)
            diagnostics.append(diagnostic)
            continue

        column_name = str(definition.get("label") or definition.get("name") or requested_name)
        existing_index = _find_field_index(output_fields, [column_name, str(definition.get("name") or "")])
        if existing_index is not None:
            metadata.append(
                {
                    "name": str(definition.get("name") or requested_name),
                    "label": column_name,
                    "status": "already_present",
                    "source": "mcp",
                    "column_index": existing_index,
                }
            )
            continue

        input_indexes, missing_inputs = _resolve_inputs(output_fields, definition)
        if missing_inputs:
            output_fields.append(column_name)
            for row in output_rows:
                if isinstance(row, list):
                    row.append(None)
            diagnostic = {
                "name": str(definition.get("name") or requested_name),
                "label": column_name,
                "status": "missing_input",
                "missing_inputs": missing_inputs,
                "source": "metrics_registry",
            }
            metadata.append(diagnostic)
            diagnostics.append(diagnostic)
            continue

        formula = str(definition.get("formula") or "").strip()
        try:
            expression = ast.parse(formula, mode="eval").body
            _validate_expression(expression, set(input_indexes))
        except (SyntaxError, ValueError) as exc:
            output_fields.append(column_name)
            for row in output_rows:
                if isinstance(row, list):
                    row.append(None)
            diagnostic = {
                "name": str(definition.get("name") or requested_name),
                "label": column_name,
                "status": "invalid_formula",
                "source": "metrics_registry",
                "error": str(exc),
            }
            metadata.append(diagnostic)
            diagnostics.append(diagnostic)
            continue

        values: list[Any] = []
        null_reasons: dict[str, int] = {}
        totals = _input_totals(output_rows, input_indexes)
        for row in output_rows:
            if not isinstance(row, list):
                values.append(None)
                null_reasons["unsupported_row_shape"] = null_reasons.get("unsupported_row_shape", 0) + 1
                continue
            context = {
                alias: _numeric_value(row[index]) if len(row) > index else None
                for alias, index in input_indexes.items()
            }
            try:
                values.append(_eval_expression(expression, context, totals))
            except FormulaEvaluationError as exc:
                values.append(None)
                null_reasons[exc.code] = null_reasons.get(exc.code, 0) + 1

        output_fields.append(column_name)
        for index, row in enumerate(output_rows):
            if isinstance(row, list):
                row.append(values[index])

        status = "computed_with_nulls" if null_reasons else "computed"
        item_metadata = {
            "name": str(definition.get("name") or requested_name),
            "label": column_name,
            "status": status,
            "result_type": definition.get("result_type"),
            "source": "metrics_registry",
            "source_fields": {
                alias: _field_name(output_fields[field_index])
                for alias, field_index in input_indexes.items()
            },
            "null_count": sum(null_reasons.values()),
        }
        if null_reasons:
            item_metadata["null_reasons"] = null_reasons
            diagnostics.append(item_metadata)
        metadata.append(item_metadata)

    return DerivedColumnResult(output_fields, output_rows, metadata, diagnostics)


def append_derived_columns_to_response_data(
    response_data: Mapping[str, Any],
    *,
    requested_metric_names: list[str] | set[str] | tuple[str, ...],
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a response_data copy with registry-derived fields and diagnostics."""

    payload = dict(response_data)
    result = append_derived_columns(
        list(payload.get("fields") or []),
        list(payload.get("rows") or []),
        requested_metric_names=requested_metric_names,
        registry_path=registry_path,
    )
    payload["fields"] = result.fields
    payload["rows"] = result.rows
    if result.metadata:
        payload["derived_columns"] = result.metadata
    if result.diagnostics:
        diagnostics = dict(payload.get("diagnostics") or {})
        diagnostics["derived_columns"] = result.diagnostics
        payload["diagnostics"] = diagnostics
    return payload


def derived_metric_names_in_text(text: str, registry_path: str | Path | None = None) -> set[str]:
    """Return registry metric names whose name or aliases appear in text."""

    normalized_text = _key(text)
    if not normalized_text:
        return set()
    matched: set[str] = set()
    for definition in _load_registry(registry_path).values():
        name = str(definition.get("name") or "").strip()
        candidates = [name, *[str(alias) for alias in (definition.get("aliases") or [])]]
        if any(_key(candidate) and _key(candidate) in normalized_text for candidate in candidates):
            matched.add(name)
    return matched


def _load_registry(registry_path: str | Path | None) -> dict[str, Mapping[str, Any]]:
    path = Path(registry_path or os.getenv(_REGISTRY_ENV) or _DEFAULT_REGISTRY_PATH)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    raw_metrics = payload.get("derived_metrics") if isinstance(payload, Mapping) else []
    definitions: dict[str, Mapping[str, Any]] = {}
    for item in raw_metrics or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            definitions[_key(name)] = item
    return definitions


def _ordered_names(names: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw_name in names or []:
        name = str(raw_name or "").strip()
        name_key = _key(name)
        if name and name_key not in seen:
            seen.add(name_key)
            output.append(name)
    return output


def _copy_row(row: Any) -> Any:
    if isinstance(row, list):
        return list(row)
    if isinstance(row, tuple):
        return list(row)
    return row


def _resolve_inputs(fields: list[Any], definition: Mapping[str, Any]) -> tuple[dict[str, int], list[str]]:
    input_indexes: dict[str, int] = {}
    missing_inputs: list[str] = []
    inputs = definition.get("inputs")
    if not isinstance(inputs, Mapping):
        return {}, ["inputs"]
    for alias, raw_spec in inputs.items():
        candidates = _input_candidates(raw_spec)
        index = _find_field_index(fields, candidates)
        if index is None:
            missing_inputs.append(str(alias))
            continue
        input_indexes[str(alias)] = index
    return input_indexes, missing_inputs


def _input_candidates(raw_spec: Any) -> list[str]:
    if isinstance(raw_spec, Mapping):
        raw_fields = raw_spec.get("fields") or raw_spec.get("field") or []
    else:
        raw_fields = raw_spec
    if isinstance(raw_fields, str):
        raw_fields = [raw_fields]
    return [str(item) for item in raw_fields or [] if str(item or "").strip()]


def _find_field_index(fields: list[Any], candidates: list[str]) -> int | None:
    candidate_keys = {_key(candidate) for candidate in candidates if candidate}
    if not candidate_keys:
        return None
    for index, field in enumerate(fields):
        names = {_key(name) for name in _field_names(field) if name}
        if names & candidate_keys:
            return index
    return None


def _field_names(field: Any) -> list[str]:
    if isinstance(field, Mapping):
        return [
            str(field.get("name") or ""),
            str(field.get("fieldAlias") or ""),
            str(field.get("fieldCaption") or ""),
            str(field.get("caption") or ""),
        ]
    return [str(field or "")]


def _field_name(field: Any) -> str:
    for name in _field_names(field):
        if name:
            return name
    return ""


def _key(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "").replace("\u00a0", "")


def _numeric_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None
    is_percent = raw.endswith("%")
    if is_percent:
        raw = raw[:-1]
    try:
        number = float(raw.replace(",", ""))
    except ValueError:
        return None
    return number / 100 if is_percent else number


def _input_totals(rows: list[Any], input_indexes: Mapping[str, int]) -> dict[str, float | None]:
    totals: dict[str, float | None] = {}
    for alias, index in input_indexes.items():
        total = 0.0
        seen = False
        for row in rows:
            if not isinstance(row, list) or len(row) <= index:
                continue
            value = _numeric_value(row[index])
            if value is None:
                continue
            total += value
            seen = True
        totals[alias] = total if seen else None
    return totals


def _validate_expression(node: ast.AST, allowed_names: set[str]) -> None:
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            if child.id not in allowed_names and child.id not in {"total", "sum"}:
                raise ValueError(f"unknown formula variable: {child.id}")
        elif isinstance(child, ast.Call):
            if not isinstance(child.func, ast.Name) or child.func.id not in {"total", "sum"}:
                raise ValueError("formula contains unsupported function")
            if len(child.args) != 1 or not isinstance(child.args[0], ast.Name):
                raise ValueError("formula aggregate function requires one input variable")
            if child.args[0].id not in allowed_names:
                raise ValueError(f"unknown formula variable: {child.args[0].id}")
        elif isinstance(
            child,
            (
                ast.Expression,
                ast.BinOp,
                ast.UnaryOp,
                ast.Load,
                ast.Constant,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.Mod,
                ast.USub,
                ast.UAdd,
            ),
        ):
            continue
        else:
            raise ValueError(f"unsupported formula syntax: {type(child).__name__}")


def _eval_expression(node: ast.AST, context: Mapping[str, float | None], totals: Mapping[str, float | None]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaEvaluationError("invalid_constant")
        return float(node.value)
    if isinstance(node, ast.Name):
        value = context.get(node.id)
        if value is None:
            raise FormulaEvaluationError("missing_value")
        return value
    if isinstance(node, ast.UnaryOp):
        value = _eval_expression(node.operand, context, totals)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
    if isinstance(node, ast.BinOp):
        left = _eval_expression(node.left, context, totals)
        right = _eval_expression(node.right, context, totals)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise FormulaEvaluationError("division_by_zero")
            return left / right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise FormulaEvaluationError("division_by_zero")
            return left % right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        alias = node.args[0].id if node.args and isinstance(node.args[0], ast.Name) else ""
        value = totals.get(alias)
        if value is None:
            raise FormulaEvaluationError("missing_value")
        return value
    raise FormulaEvaluationError("unsupported_expression")
