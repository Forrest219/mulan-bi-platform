"""单元测试：Tableau 健康评分引擎 — 7 因子评分"""
import pytest
from datetime import datetime, timedelta
from services.tableau.health import (
    compute_asset_health,
    get_health_level,
    HEALTH_CHECKS,
)


class MockObj:
    """简化 mock 对象"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestHealthLevel:
    """健康等级测试"""

    def test_excellent(self):
        assert get_health_level(80) == "excellent"
        assert get_health_level(100) == "excellent"

    def test_good(self):
        assert get_health_level(60) == "good"
        assert get_health_level(79) == "good"

    def test_warning(self):
        assert get_health_level(40) == "warning"
        assert get_health_level(59) == "warning"

    def test_poor(self):
        assert get_health_level(39) == "poor"
        assert get_health_level(0) == "poor"


class TestHealthChecksWeight:
    """权重总和测试"""

    def test_total_weight_100(self):
        total = sum(c["weight"] for c in HEALTH_CHECKS)
        assert total == 100, f"权重总和应为 100，实际为 {total}"


class TestHasDescription:
    """has_description 检查项"""

    def test_passes_with_description(self):
        asset = {"description": "销售月报"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["has_description"]["passed"] is True
        assert result["score"] >= 20

    def test_fails_without_description(self):
        asset = {"name": "test"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["has_description"]["passed"] is False

    def test_fails_with_blank_description(self):
        asset = {"description": "   "}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["has_description"]["passed"] is False


class TestHasOwner:
    """has_owner 检查项"""

    def test_passes_with_owner(self):
        asset = {"name": "test", "owner_name": "张三"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["has_owner"]["passed"] is True

    def test_fails_without_owner(self):
        asset = {"name": "test"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["has_owner"]["passed"] is False


class TestHasDatasourceLink:
    """has_datasource_link 检查项"""

    def test_passes_with_datasource(self):
        asset = {"name": "test"}
        ds = [MockObj(id=1)]
        result = compute_asset_health(asset, ds, [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["has_datasource_link"]["passed"] is True

    def test_fails_without_datasource(self):
        asset = {"name": "test"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["has_datasource_link"]["passed"] is False


class TestFieldsHaveCaptions:
    """fields_have_captions 检查项"""

    def test_full_coverage_passes(self):
        asset = {"name": "test"}
        fields = [MockObj(field_caption="销售额"), MockObj(field_caption="客户名")]
        result = compute_asset_health(asset, [], fields)
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["fields_have_captions"]["passed"] is True

    def test_50_percent_passes(self):
        """恰好 50% 通过"""
        asset = {"name": "test"}
        fields = [MockObj(field_caption="A"), MockObj(field_caption=None)]
        result = compute_asset_health(asset, [], fields)
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["fields_have_captions"]["passed"] is True

    def test_below_50_percent_fails(self):
        """低于 50% 不通过"""
        asset = {"name": "test"}
        fields = [MockObj(field_caption="A"), MockObj(field_caption=None), MockObj(field_caption=None)]
        result = compute_asset_health(asset, [], fields)
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["fields_have_captions"]["passed"] is False

    def test_no_fields_gives_full_score(self):
        """无字段时跳过，给满分"""
        asset = {"name": "test"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["fields_have_captions"]["passed"] is True
        assert "跳过检查" in checks["fields_have_captions"]["detail"]


class TestNamingConvention:
    """命名规范检查项"""

    def test_normal_name_passes(self):
        asset = {"name": "sales_report"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["naming_convention"]["passed"] is True

    def test_starts_with_digit_fails(self):
        asset = {"name": "2024_sales"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["naming_convention"]["passed"] is False

    def test_special_chars_fail(self):
        for char in ["@", "#", "$", "!"]:
            asset = {"name": f"name{char}test"}
            result = compute_asset_health(asset, [], [])
            checks = {c["key"]: c for c in result["checks"]}
            assert checks["naming_convention"]["passed"] is False, f"'{char}' 应导致命名检查失败"


class TestNotStale:
    """近期更新检查项"""

    def test_recently_updated_passes(self):
        recent = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        asset = {"name": "test", "updated_on_server": recent}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["not_stale"]["passed"] is True

    def test_over_90_days_fails(self):
        old = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
        asset = {"name": "test", "updated_on_server": old}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["not_stale"]["passed"] is False

    def test_no_updated_field_fails(self):
        asset = {"name": "test"}
        result = compute_asset_health(asset, [], [])
        checks = {c["key"]: c for c in result["checks"]}
        assert checks["not_stale"]["passed"] is False


class TestFullScore:
    """满分场景测试"""

    def test_perfect_asset_score_100(self):
        """全部通过的完美资产得 100 分"""
        recent = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        asset = {
            "name": "sales_monthly",
            "description": "月度销售报表",
            "owner_name": "李四",
            "is_certified": True,
            "updated_on_server": recent,
        }
        ds = [MockObj(id=1)]
        fields = [
            MockObj(field_caption="销售额"),
            MockObj(field_caption="客户名"),
            MockObj(field_caption="日期"),
            MockObj(field_caption="地区"),
        ]
        result = compute_asset_health(asset, ds, fields)
        assert result["score"] == 100.0
        assert result["level"] == "excellent"
