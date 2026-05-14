"""Draft tests for MCP snapshot baseline comparator."""

import uuid

import pytest

from services.data_agent.analysis_context import AnalysisContext
from services.data_agent.mcp_baseline_comparator import BaselineCase, compare_case_to_snapshot


pytestmark = pytest.mark.skip_db


def test_compare_case_to_snapshot_blocks_shape_mismatch():
    case = BaselineCase.from_dict({
        "id": "batch2.q6_top10_customers",
        "group": "batch2",
        "question": "Top 10 大客户是谁？",
        "connection_fixture": "superstore_tableau",
        "expected_patch": {},
        "baseline": {
            "result_shape": {"required_fields": ["客户名称", "销售额"], "max_rows": 10},
            "tolerances": {"numeric_rel": 0.001},
        },
    })
    context = AnalysisContext.new(
        conversation_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        trace_id="t-baseline",
        turn_no=1,
        scope={
            "user_id": 7,
            "role": "analyst",
            "connection_id": 12,
            "connection_type": "tableau",
            "datasource_luid": "ds-luid",
            "datasource_name": "订单+ (示例 - 超市)",
        },
        query_plan={
            "metrics": [{"name": "销售额", "field_caption": "销售额", "aggregation": "SUM"}],
            "dimensions": [{"name": "客户名称", "field_caption": "客户名称"}],
        },
    )
    snapshot = {
        "snapshot_id": "superstore_2026_05_13",
        "cases": {
            "batch2.q6_top10_customers": {
                "rows": [["客户A", 100.0]],
                "result_shape": {"required_fields": ["客户名称", "销售额"], "max_rows": 10},
                "tolerances": {"numeric_rel": 0.001, "row_set": "exact"},
            }
        },
    }

    comparison = compare_case_to_snapshot(
        case=case,
        context=context,
        response_data={"fields": ["客户名称"], "rows": [["客户A"]]},
        snapshot=snapshot,
    )

    assert comparison.status == "block"
    assert any(check.name == "baseline_required_fields" for check in comparison.checks)
