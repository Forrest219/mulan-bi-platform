"""Draft tests for services.data_agent.query_plan_patch."""

import uuid

import pytest

from services.data_agent.analysis_context import AnalysisContext
from services.data_agent.query_plan_patch import (
    PatchApplyError,
    apply_query_plan_patch,
    make_patch,
)


pytestmark = pytest.mark.skip_db


def _base_context(*, metrics=None, dimensions=None, filters=None, time=None, analysis_type="lookup"):
    return AnalysisContext.new(
        conversation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        trace_id="t-patch",
        turn_no=1,
        scope={
            "tenant_id": None,
            "user_id": 7,
            "role": "analyst",
            "connection_id": 12,
            "connection_type": "tableau",
            "datasource_luid": "ds-luid",
            "datasource_name": "订单+ (示例 - 超市)",
        },
        analysis_type=analysis_type,
        confidence=0.9,
        query_plan={
            "subject": "销售表现",
            "metrics": metrics or [{"name": "销售额", "field_caption": "销售额", "aggregation": "SUM"}],
            "dimensions": dimensions or [{"name": "类别", "field_caption": "类别"}],
            "filters": filters or [],
            "time": time,
        },
    )


def test_q1_to_q2_followup_inherits_metric_and_adds_year_time():
    previous = _base_context(dimensions=[])
    patch = make_patch(
        previous_context=previous,
        patch_type="clarify_reference",
        payload={
            "resolved_refs": [{"type": "metric", "name": "销售额"}],
            "patches": [
                {
                    "patch_type": "set_time_range",
                    "payload": {
                        "time": {
                            "field_caption": "订单日期",
                            "range": {"type": "relative", "period": "years", "last_n": 4},
                            "grain": "year",
                            "timezone": "Asia/Shanghai",
                        }
                    },
                },
                {"patch_type": "set_time_grain", "payload": {"grain": "year"}},
            ],
        },
        reason="用户说这个指标过去几年，继承上一轮唯一指标",
        confidence=0.93,
    )

    applied = apply_query_plan_patch(previous, patch)

    assert [m["name"] for m in applied.next_context.query_plan["metrics"]] == ["销售额"]
    assert applied.next_context.query_plan["time"]["grain"] == "year"
    assert applied.next_context.semantic_resolution["resolved_refs"][0]["name"] == "销售额"


def test_q3_to_q4_inherits_subcategory_and_adds_year_grain():
    previous = _base_context(dimensions=[{"name": "子类别", "field_caption": "子类别"}])
    patch = make_patch(
        previous_context=previous,
        patch_type="set_time_range",
        payload={
            "time": {
                "field_caption": "订单日期",
                "range": {"type": "relative", "period": "years", "last_n": 4},
                "grain": "year",
            }
        },
        reason="继续拆分到每个年份",
        confidence=0.91,
    )

    applied = apply_query_plan_patch(previous, patch)

    assert [d["name"] for d in applied.next_context.query_plan["dimensions"]] == ["子类别"]
    assert applied.next_context.query_plan["time"]["grain"] == "year"


def test_q9_followup_inherits_province_filter_and_switches_root_cause():
    previous = _base_context(
        metrics=[{"name": "利润", "field_caption": "利润", "aggregation": "SUM"}],
        dimensions=[{"name": "省份", "field_caption": "省份"}],
        filters=[{"id": "f_province_loss", "field_caption": "省份", "operator": "in", "value": ["辽宁", "福建"]}],
        analysis_type="all_period_condition",
    )
    patch = make_patch(
        previous_context=previous,
        patch_type="switch_analysis_type",
        payload={"from_type": "all_period_condition", "to_type": "root_cause", "semantic_operator": "root_cause"},
        reason="用户问这些省份为什么亏，继承省份筛选并切换归因算子",
        confidence=0.95,
    )

    applied = apply_query_plan_patch(previous, patch)

    assert applied.next_context.analysis_intent["analysis_type"] == "root_cause"
    assert applied.next_context.query_plan["filters"][0]["value"] == ["辽宁", "福建"]
    assert applied.next_context.query_plan["postprocess"]["semantic_operator"] == "root_cause"


def test_replace_dimension_removes_old_dimension_only():
    previous = _base_context(dimensions=[{"name": "地区", "field_caption": "地区"}])
    patch = make_patch(
        previous_context=previous,
        patch_type="replace_dimension",
        payload={
            "from_dimension_ref": "地区",
            "to_dimension": {"name": "类别", "field_caption": "类别"},
        },
        reason="不是地区，是类别",
        confidence=0.96,
    )

    applied = apply_query_plan_patch(previous, patch)

    assert [d["name"] for d in applied.next_context.query_plan["dimensions"]] == ["类别"]
    assert applied.diff["dimensions_added"] == ["类别"]
    assert applied.diff["dimensions_removed"] == ["地区"]


def test_hash_mismatch_blocks_stale_patch():
    previous = _base_context()
    patch = make_patch(
        previous_context=previous,
        patch_type="add_dimension",
        payload={"dimension": {"name": "省份", "field_caption": "省份"}},
        reason="再按省份",
    )
    patch.base_context_hash = "stale"

    with pytest.raises(PatchApplyError) as exc:
        apply_query_plan_patch(previous, patch)

    assert exc.value.code == "context_hash_mismatch"


def test_fallback_required_does_not_update_context():
    previous = _base_context()
    patch = make_patch(
        previous_context=previous,
        patch_type="fallback_required",
        payload={"reason_code": "clarification_required", "user_hint": "请明确指标"},
        reason="引用无法唯一消解",
    )

    with pytest.raises(PatchApplyError) as exc:
        apply_query_plan_patch(previous, patch)

    assert exc.value.code == "clarification_required"
    assert previous.turn_no == 1
