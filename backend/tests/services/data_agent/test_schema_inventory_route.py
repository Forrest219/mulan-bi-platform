from dataclasses import dataclass

import pytest

from services.data_agent.deterministic import (
    DeterministicRouteResult,
    build_schema_inventory_tool_params,
    detect_deterministic_route,
    normalize_schema_inventory,
    render_schema_inventory_markdown,
    run_schema_inventory_route,
    validate_schema_inventory_payload,
)
from services.data_agent.tool_base import ToolContext, ToolResult

pytestmark = pytest.mark.skip_db


class FakeSchemaTool:
    name = "schema"

    def __init__(self, data):
        self.data = data
        self.calls = []

    async def execute(self, params, context):
        self.calls.append({"params": params, "context": context})
        return ToolResult(success=True, data=self.data)


class FakeRegistry:
    def __init__(self, tool):
        self.tool = tool
        self.requested = []

    def get(self, name):
        self.requested.append(name)
        assert name == "schema"
        return self.tool


@dataclass
class ActiveVersion:
    version_id: str


def sample_tool_data():
    return {
        "connection_id": 7,
        "datasource_name": "Tableau-online",
        "db_type": "tableau",
        "tables": [
            {"name": "zeta view", "type": "view", "project": "B"},
            {"name": "Orders", "type": "datasource", "project": ""},
            {"name": "alpha", "type": "datasource", "project": "A"},
            {"name": "Workbook A", "type": "workbook", "project": "A"},
            {"name": "Flow A", "type": "flow", "project": "A"},
            {"name": "Custom Asset", "type": "metric", "project": "A"},
        ],
    }


@pytest.mark.parametrize(
    "question",
    [
        "有哪些数据源",
        "有什么数据源",
        "有哪些表",
        "当前连接",
        "可用数据源",
        "数据源列表",
        "表列表",
        "有哪些资产",
        "有哪些视图",
        "schema",
        "What data sources are available?",
        "show datasets",
        "list tables",
        "show views",
        "what fields exist",
        "available sources",
        "订单明细表 有哪些字段？",
        "customers-客户维度表字段有哪些",
        "月度指标汇总表 有哪些字段？",
    ],
)
def test_detect_deterministic_route_hits_inventory_keywords(question):
    assert detect_deterministic_route(question, "tableau") == "schema_inventory"


@pytest.mark.parametrize(
    "question",
    [
        "有哪些数据源包含销售额",
        "数据源列表里只看订单数",
        "推荐第二个数据源",
        "分析一下有哪些表",
        "top tables by revenue",
        "有哪些表名字里有客户字样",
    ],
)
def test_detect_deterministic_route_excludes_ambiguous_or_analytic_questions(question):
    assert detect_deterministic_route(question, "tableau") is None


def test_build_schema_inventory_tool_params_for_field_and_asset_questions():
    assert build_schema_inventory_tool_params("月度指标汇总表 有哪些字段？") == {
        "table_name": "月度指标汇总表"
    }
    assert build_schema_inventory_tool_params("当前连接有哪些资产？") == {
        "include_all_asset_types": True
    }
    assert build_schema_inventory_tool_params("你有哪些数据源？") == {}


def test_normalize_sorts_by_type_project_name_and_counts():
    payload = normalize_schema_inventory(sample_tool_data())

    assert [asset["asset_type"] for asset in payload["assets"]] == ["datasource", "datasource"]
    assert [asset["name"] for asset in payload["assets"][:2]] == ["alpha", "Orders"]
    assert payload["assets"][1]["project"] == "未分组"
    assert payload["total_count"] == 2
    assert payload["shown_count"] == 2
    assert payload["omitted_count"] == 0


def test_normalize_allows_assets_only_when_explicitly_requested():
    payload = normalize_schema_inventory(sample_tool_data(), request={"mode": "assets"})

    assert [asset["asset_type"] for asset in payload["assets"]] == [
        "datasource",
        "datasource",
        "view",
        "workbook",
        "flow",
        "metric",
    ]
    assert payload["total_count"] == 6


def test_render_schema_inventory_markdown_is_byte_stable_and_uses_exact_counts():
    payload = normalize_schema_inventory(sample_tool_data())

    first = render_schema_inventory_markdown(payload)
    second = render_schema_inventory_markdown(payload)

    assert first == second
    assert "共 2 个Tableau datasource，展示 2 个，省略 0 个。" in first
    assert "zeta view" not in first
    assert "Workbook A" not in first
    assert "+" not in first
    assert "约" not in first
    assert "多个" not in first
    assert "推荐" not in first


def test_truncates_each_asset_type_but_keeps_true_total_count():
    tool_data = {
        "tables": [
            {"name": f"ds-{index:03d}", "type": "datasource", "project": "P"}
            for index in range(105)
        ]
    }

    payload = normalize_schema_inventory(tool_data)

    assert payload["total_count"] == 105
    assert payload["shown_count"] == 100
    assert payload["omitted_count"] == 5
    assert payload["asset_types"][0]["total_count"] == 105
    assert payload["asset_types"][0]["shown_count"] == 100
    assert payload["asset_types"][0]["omitted_count"] == 5


def test_validate_schema_inventory_payload_rejects_invalid_counts():
    payload = normalize_schema_inventory(sample_tool_data())
    payload["omitted_count"] = 99

    with pytest.raises(ValueError, match="omitted_count"):
        validate_schema_inventory_payload(payload)


@pytest.mark.asyncio
async def test_run_schema_inventory_route_calls_only_schema_tool_with_empty_params():
    tool = FakeSchemaTool(sample_tool_data())
    registry = FakeRegistry(tool)
    context = ToolContext(session_id="s1", user_id=1, connection_id=7, connection_type="tableau")

    result = await run_schema_inventory_route(registry, context, ActiveVersion("ver-1"))

    assert isinstance(result, DeterministicRouteResult)
    assert registry.requested == ["schema"]
    assert tool.calls == [{"params": {}, "context": context}]
    assert result.tools_used == ["schema"]
    assert result.response_type == "schema_inventory"
    assert result.steps_count == 4
    assert result.tool_name == "schema"
    assert result.tool_params == {}
    assert result.skill_version_id == "ver-1"
    assert result.response_data["total_count"] == 2
    assert result.answer == render_schema_inventory_markdown(result.response_data)


@pytest.mark.asyncio
async def test_run_schema_inventory_route_for_assets_passes_explicit_asset_flag():
    tool = FakeSchemaTool(sample_tool_data())
    registry = FakeRegistry(tool)
    context = ToolContext(session_id="s1", user_id=1, connection_id=7, connection_type="tableau")

    result = await run_schema_inventory_route(
        registry,
        context,
        question="当前连接有哪些资产？",
    )

    assert tool.calls == [{"params": {"include_all_asset_types": True}, "context": context}]
    assert result.response_data["mode"] == "assets"
    assert [asset["asset_type"] for asset in result.response_data["assets"]] == [
        "datasource",
        "datasource",
        "view",
        "workbook",
        "flow",
        "metric",
    ]


@pytest.mark.asyncio
async def test_run_schema_inventory_route_sets_skill_version_id_none_when_missing():
    tool = FakeSchemaTool(sample_tool_data())
    registry = FakeRegistry(tool)
    context = ToolContext(session_id="s1", user_id=1, connection_id=7)

    result = await run_schema_inventory_route(registry, context)

    assert result.skill_version_id is None


@pytest.mark.asyncio
async def test_run_schema_inventory_route_for_field_question_uses_table_name_and_friendly_fields():
    tool = FakeSchemaTool({
        "requested_table_name": "订单明细表",
        "matched_asset": {
            "name": "orders-订单明细表",
            "type": "datasource",
            "web_url": "https://example.test/datasource",
        },
        "field_count": 3,
        "fields": {
            "orders-订单明细表": [
                {"name": "orders_5D2D0CE41EE948FBBB5EAAF793DD6314", "caption": "", "data_type": "string", "role": "dimension", "is_calculated": False},
                {"name": "[order_id]", "caption": "订单 ID", "data_type": "string", "role": "dimension", "is_calculated": False},
                {"name": "[sales]", "caption": "销售额", "data_type": "real", "role": "measure", "is_calculated": False},
            ]
        },
    })
    registry = FakeRegistry(tool)
    context = ToolContext(session_id="s1", user_id=1, connection_id=7, connection_type="tableau")

    result = await run_schema_inventory_route(
        registry,
        context,
        question="订单明细表 有哪些字段？",
    )

    assert tool.calls == [{"params": {"table_name": "订单明细表"}, "context": context}]
    assert result.response_data["mode"] == "fields"
    assert result.response_data["field_count"] == 2
    assert [field["display_name"] for field in result.response_data["fields"]] == ["订单 ID", "销售额"]
    assert "orders_5D2D0CE41EE948FBBB5EAAF793DD6314" not in result.answer
    assert "订单 ID" in result.answer
    assert "销售额" in result.answer
    assert "资产链接：https://example.test/datasource" in result.answer


@pytest.mark.asyncio
async def test_run_schema_inventory_route_for_field_question_with_excluded_word_uses_table_name():
    tool = FakeSchemaTool({
        "requested_table_name": "月度指标汇总表",
        "matched_asset": {
            "name": "bidm_ai_metric_summary_mth-月度指标汇总表",
            "type": "datasource",
            "web_url": "https://example.test/datasource",
        },
        "field_count": 2,
        "fields": {
            "bidm_ai_metric_summary_mth-月度指标汇总表": [
                {"name": "净额", "caption": "", "data_type": "", "role": "", "is_calculated": False},
                {"name": "统计月份", "caption": "", "data_type": "", "role": "", "is_calculated": False},
            ]
        },
    })
    registry = FakeRegistry(tool)
    context = ToolContext(session_id="s1", user_id=1, connection_id=7, connection_type="tableau")

    result = await run_schema_inventory_route(
        registry,
        context,
        question="月度指标汇总表 有哪些字段？",
    )

    assert tool.calls == [{"params": {"table_name": "月度指标汇总表"}, "context": context}]
    assert result.response_data["mode"] == "fields"
    assert result.response_data["matched_asset"]["asset_type"] == "datasource"
    assert "净额" in result.answer
    assert "统计月份" in result.answer
    assert "数据资产 **bidm_ai_metric_summary_mth-月度指标汇总表** 返回了 **2 个字段**" in result.answer


def test_field_normalize_keeps_logic_id_when_it_is_the_only_field():
    payload = normalize_schema_inventory(
        {
            "requested_table_name": "订单明细表",
            "matched_asset": {"name": "orders-订单明细表", "type": "datasource"},
            "fields": {
                "orders-订单明细表": [
                    {"name": "orders_5D2D0CE41EE948FBBB5EAAF793DD6314", "caption": "", "data_type": "string"},
                ]
            },
        },
        request={"mode": "fields", "table_name": "订单明细表"},
    )

    assert payload["field_count"] == 1
    assert payload["fields"][0]["display_name"] == "orders_5D2D0CE41EE948FBBB5EAAF793DD6314"


def test_field_normalize_keeps_regular_snake_case_fields():
    payload = normalize_schema_inventory(
        {
            "requested_table_name": "orders",
            "matched_asset": {"name": "orders", "type": "datasource"},
            "fields": {
                "orders": [
                    {"name": "customer_id", "caption": "", "data_type": "string"},
                    {"name": "orders_5D2D0CE41EE948FBBB5EAAF793DD6314", "caption": "", "data_type": "string"},
                ]
            },
        },
        request={"mode": "fields", "table_name": "orders"},
    )

    assert [field["display_name"] for field in payload["fields"]] == ["customer_id"]
