import pytest

from services.data_agent import mcp_first_main

pytestmark = pytest.mark.skip_db


QUERYABLE_FIELDS = ["客单价", "利润率", "客户数", "子类别", "发货年份", "发货日期", "销售额", "利润", "客户名称", "省/自治区", "类别"]
CATALOG_FIELDS = [
    "订单日期", "数量", "区域", "折扣", "订单 Id", "客户 Id", "城市", "产品名称", "装运模式",
    "客单价", "利润率", "客户数", "子类别", "发货年份", "发货日期", "销售额", "利润", "客户名称", "省/自治区", "类别",
]


def test_catalog_only_preflight_blocks_user_mentioned_catalog_field():
    result = mcp_first_main._catalog_only_preflight(
        "按订单日期统计销售额",
        {"asset_id": 422, "catalog_fields": CATALOG_FIELDS},
        QUERYABLE_FIELDS,
    )

    assert result is not None
    assert result["fields"] == ["订单日期"]
    assert "发货日期" in result["alternatives"]


def test_catalog_only_preflight_allows_queryable_field():
    result = mcp_first_main._catalog_only_preflight(
        "按类别统计销售额",
        {"asset_id": 422, "catalog_fields": CATALOG_FIELDS},
        QUERYABLE_FIELDS,
    )

    assert result is None


def test_catalog_only_preflight_does_not_mislabel_unknown_fields_without_queryable_set():
    result = mcp_first_main._catalog_only_preflight(
        "按销售额统计",
        {"asset_id": 422, "catalog_fields": ["销售额", "订单日期"]},
        [],
    )

    assert result is None
