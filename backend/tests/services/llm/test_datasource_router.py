"""
Datasource Router 单元测试（Spec 14 §12.2）

测试项：
- 评分公式正确
- 自动连接路由（C4）
- 最低分拒绝
"""
import pytest
from datetime import datetime, timezone

from services.llm.datasource_router import (
    calculate_routing_score,
    calculate_freshness,
    calculate_field_count_score,
    calculate_usage_frequency,
    extract_terms,
    MIN_ROUTING_SCORE,
    WEIGHT_FIELD_COVERAGE,
    WEIGHT_FRESHNESS,
    WEIGHT_FIELD_COUNT,
    WEIGHT_USAGE_FREQUENCY,
)


class TestCalculateFreshness:
    """新鲜度计算测试"""

    def test_recent_sync(self):
        """最近同步"""
        now = datetime.now(timezone.utc)
        result = calculate_freshness(now)
        assert result == 1.0

    def test_12_hours_ago(self):
        """12 小时前"""
        now = datetime.now(timezone.utc)
        twelve_hours_ago = now - timedelta(hours=12)
        result = calculate_freshness(twelve_hours_ago)
        assert 0.4 < result < 0.6

    def test_48_hours_ago(self):
        """48 小时前（应接近 0）"""
        now = datetime.now(timezone.utc)
        forty_eight_hours_ago = now - timedelta(hours=48)
        result = calculate_freshness(forty_eight_hours_ago)
        assert result == 0.0

    def test_none_sync_time(self):
        """无同步时间（默认 0.5）"""
        result = calculate_freshness(None)
        assert result == 0.5


class TestCalculateFieldCountScore:
    """字段数量得分测试"""

    def test_optimal_range(self):
        """10-100 范围内返回 1.0"""
        assert calculate_field_count_score(10) == 1.0
        assert calculate_field_count_score(50) == 1.0
        assert calculate_field_count_score(100) == 1.0

    def test_too_small(self):
        """过小返回 0.8"""
        assert calculate_field_count_score(5) == 0.8
        assert calculate_field_count_score(9) == 0.8

    def test_too_large(self):
        """过大返回 0.8"""
        assert calculate_field_count_score(101) == 0.8
        assert calculate_field_count_score(500) == 0.8


class TestCalculateUsageFrequency:
    """使用频次测试"""

    def test_zero_queries(self):
        """零查询"""
        result = calculate_usage_frequency(0)
        assert result == 0.0

    def test_50_queries(self):
        """50 次查询"""
        result = calculate_usage_frequency(50)
        assert result == 0.5

    def test_100_queries(self):
        """100 次查询"""
        result = calculate_usage_frequency(100)
        assert result == 1.0

    def test_200_queries(self):
        """超过 100 次（上限 1.0）"""
        result = calculate_usage_frequency(200)
        assert result == 1.0


class TestCalculateRoutingScore:
    """路由评分公式测试"""

    def test_perfect_coverage(self):
        """完美字段覆盖"""
        terms = ["销售额", "区域"]
        fields = ["销售额", "区域", "利润"]
        score = calculate_routing_score(terms, fields)
        # field_coverage = 2/2 = 1.0
        # freshness = 0.5 (default)
        # field_count_score = 1.0
        # usage = 0.0
        expected = (
            WEIGHT_FIELD_COVERAGE * 1.0 +
            WEIGHT_FRESHNESS * 0.5 +
            WEIGHT_FIELD_COUNT * 1.0 +
            WEIGHT_USAGE_FREQUENCY * 0.0
        )
        assert score == round(expected, 4)

    def test_no_coverage(self):
        """无字段覆盖"""
        terms = ["未知词"]
        fields = ["销售额", "区域"]
        score = calculate_routing_score(terms, fields)
        # field_coverage = 0/1 = 0
        # freshness = 0.5
        # field_count_score = 1.0
        # usage = 0.0
        expected = (
            WEIGHT_FIELD_COVERAGE * 0.0 +
            WEIGHT_FRESHNESS * 0.5 +
            WEIGHT_FIELD_COUNT * 1.0 +
            WEIGHT_USAGE_FREQUENCY * 0.0
        )
        assert score == round(expected, 4)

    def test_partial_coverage(self):
        """部分覆盖"""
        terms = ["销售额", "利润"]
        fields = ["销售额", "区域"]
        score = calculate_routing_score(terms, fields)
        # field_coverage = 1/2 = 0.5
        expected = (
            WEIGHT_FIELD_COVERAGE * 0.5 +
            WEIGHT_FRESHNESS * 0.5 +
            WEIGHT_FIELD_COUNT * 1.0 +
            WEIGHT_USAGE_FREQUENCY * 0.0
        )
        assert score == round(expected, 4)


class TestExtractTerms:
    """术语提取测试"""

    def test_chinese_terms(self):
        """中文术语"""
        q = "上个月各区域销售额是多少"
        result = extract_terms(q)
        assert "销售额" in result
        assert "区域" in result

    def test_english_terms(self):
        """英文术语"""
        q = "show me total sales by region"
        result = extract_terms(q)
        assert "total" in result
        assert "sales" in result
        assert "region" in result

    def test_stopwords_filtered(self):
        """停用词被过滤"""
        q = "的 是 在 有"
        result = extract_terms(q)
        # 这些都是单字，会被过滤掉
        assert len(result) == 0


class TestMinRoutingScore:
    """最低路由评分阈值测试"""

    def test_threshold_value(self):
        """阈值应该是 0.3"""
        assert MIN_ROUTING_SCORE == 0.3
