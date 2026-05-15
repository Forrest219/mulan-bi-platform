from pathlib import Path

import pytest
import yaml

from services.data_agent.answer_prompt_builder import build_answer_prompt
from services.data_agent.dynamic_column_engine import append_derived_columns
from services.data_agent.dynamic_column_engine import append_derived_columns_to_response_data
from services.data_agent.mcp_first_main import _normalize_mcp_data
from services.data_agent.queryspec import QuerySpec

pytestmark = pytest.mark.skip_db

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "data_agent" / "derived_metrics_registry.yaml"


def _registry_metric(index: int = 0) -> dict:
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    return payload["derived_metrics"][index]


def _input_fields(definition: dict) -> list[str]:
    return [spec["fields"][0] for spec in definition["inputs"].values()]


def _base_metric_name(field: str) -> str:
    if "(" in field and field.endswith(")"):
        return field.split("(", 1)[1][:-1]
    return field


def test_append_derived_columns_uses_registry_formula_without_mutating_source_rows():
    definition = _registry_metric()
    source_fields = _input_fields(definition)
    fields = ["dimension_key", *source_fields]
    rows = [["segment_a", 10, 2]]

    result = append_derived_columns(
        fields,
        rows,
        requested_metric_names=[definition["name"]],
        registry_path=REGISTRY_PATH,
    )

    assert fields == ["dimension_key", *source_fields]
    assert rows == [["segment_a", 10, 2]]
    assert result.fields == ["dimension_key", *source_fields, definition["label"]]
    assert result.rows == [["segment_a", 10, 2, 5.0]]
    assert result.metadata[0]["status"] == "computed"
    assert result.diagnostics == []


def test_division_by_zero_appends_null_value_and_diagnostic():
    definition = _registry_metric()
    source_fields = _input_fields(definition)

    result = append_derived_columns(
        source_fields,
        [[10, 0]],
        requested_metric_names=[definition["name"]],
        registry_path=REGISTRY_PATH,
    )

    assert result.fields == [*source_fields, definition["label"]]
    assert result.rows == [[10, 0, None]]
    assert result.metadata[0]["status"] == "computed_with_nulls"
    assert result.diagnostics[0]["null_reasons"] == {"division_by_zero": 1}


def test_missing_input_field_appends_null_column_and_diagnostic():
    definition = _registry_metric()
    first_source_field = _input_fields(definition)[0]
    missing_alias = list(definition["inputs"])[1]

    result = append_derived_columns(
        [first_source_field],
        [[10]],
        requested_metric_names=[definition["name"]],
        registry_path=REGISTRY_PATH,
    )

    assert result.fields == [first_source_field, definition["label"]]
    assert result.rows == [[10, None]]
    assert result.metadata[0]["status"] == "missing_input"
    assert result.diagnostics[0]["missing_inputs"] == [missing_alias]


def test_existing_mcp_column_is_not_overwritten():
    definition = _registry_metric()
    source_fields = _input_fields(definition)
    rows = [[10, 2, 99]]

    result = append_derived_columns(
        [*source_fields, definition["label"]],
        rows,
        requested_metric_names=[definition["name"]],
        registry_path=REGISTRY_PATH,
    )

    assert result.rows == [[10, 2, 99]]
    assert result.metadata[0]["status"] == "already_present"
    assert result.metadata[0]["source"] == "mcp"


def test_response_data_helper_preserves_diagnostics_contract():
    definition = _registry_metric()
    first_source_field = _input_fields(definition)[0]

    response_data = append_derived_columns_to_response_data(
        {"fields": [first_source_field], "rows": [[10]], "diagnostics": {"source": "unit"}},
        requested_metric_names=[definition["name"]],
        registry_path=REGISTRY_PATH,
    )

    assert response_data["fields"] == [first_source_field, definition["label"]]
    assert response_data["rows"] == [[10, None]]
    assert response_data["diagnostics"]["source"] == "unit"
    assert response_data["diagnostics"]["derived_columns"][0]["status"] == "missing_input"


def test_mcp_first_renderer_input_receives_computed_derived_values(monkeypatch):
    definition = _registry_metric()
    source_fields = _input_fields(definition)
    monkeypatch.setenv("DATA_AGENT_DERIVED_METRICS_REGISTRY", str(REGISTRY_PATH))
    spec = QuerySpec.model_validate(
        {
            "intent": "aggregate",
            "operator": "aggregate",
            "metrics": [
                {"field": _base_metric_name(source_fields[0]), "aggregation": "SUM"},
                {"field": _base_metric_name(source_fields[1]), "aggregation": "SUM"},
            ],
            "derived_metrics": [{"name": definition["name"]}],
            "dimensions": ["dimension_key"],
            "sort": [],
        }
    )

    response_data = _normalize_mcp_data(
        {"fields": ["dimension_key", *source_fields], "rows": [["segment_a", 10, 2]]},
        spec,
        {"name": "unit_ds", "luid": "ds-1"},
    )
    messages = build_answer_prompt(
        question="unit question",
        response_data=response_data,
        rendering_skill_content="render",
    )

    assert response_data["fields"] == ["dimension_key", *source_fields, definition["label"]]
    assert response_data["rows"] == [["segment_a", 10, 2, 5.0]]
    assert response_data["table_display"]["columns"][-1]["key"] == definition["label"]
    assert definition["label"] in messages[1]["content"]
    assert "5.0" in messages[1]["content"]
