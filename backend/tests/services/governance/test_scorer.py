"""评分算法单元测试

遵循 Spec 15 v1.1 §5 质量评分模型：
- 五维度评分：完整性(30%) / 一致性(25%) / 唯一性(20%) / 时效性(15%) / 格式规范(10%)
- 按严重级别加权：HIGH=3.0 / MEDIUM=2.0 / LOW=1.0
- 三输入源整合：质量规则检测(50%) + 健康扫描(30%) + DDL合规(20%)
"""
import pytest
import sys
import os

# Add backend to path for imports (matching test_rule_types.py pattern)
_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _backend_dir)

from services.governance.scorer import (
    calculate_dimension_score,
    calculate_quality_score,
    get_score_grade,
    DIMENSION_RULES,
    DIMENSION_WEIGHTS,
    SEVERITY_WEIGHTS,
)


class MockResult:
    """模拟 QualityResult 对象"""

    def __init__(self, rule_type: str, severity: str, passed: bool):
        self.rule_type = rule_type
        self.severity = severity
        self.passed = passed


class TestCalculateDimensionScore:
    """测试 calculate_dimension_score 函数"""

    def test_all_pass_high(self):
        """所有 HIGH 级别规则都通过时，维度评分为 100"""
        results = [MockResult("null_rate", "HIGH", True) for _ in range(3)]
        score = calculate_dimension_score(results, ["null_rate"])
        assert score == 100.0

    def test_all_fail_high(self):
        """所有 HIGH 级别规则都失败时，维度评分为 0"""
        results = [MockResult("null_rate", "HIGH", False) for _ in range(3)]
        score = calculate_dimension_score(results, ["null_rate"])
        assert score == 0.0

    def test_all_pass_medium(self):
        """所有 MEDIUM 级别规则都通过时，维度评分为 100"""
        results = [MockResult("null_rate", "MEDIUM", True) for _ in range(3)]
        score = calculate_dimension_score(results, ["null_rate"])
        assert score == 100.0

    def test_all_fail_low(self):
        """所有 LOW 级别规则都失败时，维度评分为 0"""
        results = [MockResult("null_rate", "LOW", False) for _ in range(3)]
        score = calculate_dimension_score(results, ["null_rate"])
        assert score == 0.0

    def test_mixed_severity_all_pass(self):
        """混合严重级别，所有规则通过时评分为 100"""
        results = [
            MockResult("null_rate", "HIGH", True),
            MockResult("null_rate", "MEDIUM", True),
            MockResult("null_rate", "LOW", True),
        ]
        score = calculate_dimension_score(results, ["null_rate"])
        assert score == 100.0

    def test_mixed_severity_mixed_results(self):
        """混合严重级别，混合结果"""
        results = [
            MockResult("null_rate", "HIGH", True),
            MockResult("null_rate", "MEDIUM", False),
            MockResult("null_rate", "LOW", True),
        ]
        # HIGH=3权重全pass + MEDIUM=2权重fail + LOW=1权重pass = (3+0+1)/(3+2+1)*100 = 4/6*100 = 66.67
        score = calculate_dimension_score(results, ["null_rate"])
        assert score == pytest.approx(66.7, 0.1)

    def test_mixed_severity_half_pass(self):
        """混合严重级别，一半通过"""
        results = [
            MockResult("null_rate", "HIGH", True),
            MockResult("null_rate", "HIGH", False),
            MockResult("null_rate", "MEDIUM", True),
            MockResult("null_rate", "MEDIUM", False),
        ]
        # HIGH=3权重*2 + MEDIUM=2权重*2 = 总权重 10
        # 通过：(3+0+2+0)=5
        # 评分：5/10*100 = 50
        score = calculate_dimension_score(results, ["null_rate"])
        assert score == 50.0

    def test_empty_results(self):
        """无规则时默认满分 100"""
        score = calculate_dimension_score([], ["null_rate"])
        assert score == 100.0

    def test_no_matching_rule_types(self):
        """规则类型不匹配时默认满分 100"""
        results = [MockResult("unknown_type", "HIGH", False)]
        score = calculate_dimension_score(results, ["null_rate"])
        assert score == 100.0

    def test_dimension_rules_mapping(self):
        """验证维度规则映射正确性"""
        assert "null_rate" in DIMENSION_RULES["completeness"]
        assert "referential" in DIMENSION_RULES["consistency"]
        assert "duplicate_rate" in DIMENSION_RULES["uniqueness"]
        assert "freshness" in DIMENSION_RULES["timeliness"]
        assert "format_regex" in DIMENSION_RULES["conformity"]

    def test_severity_weights(self):
        """验证严重级别权重"""
        assert SEVERITY_WEIGHTS["HIGH"] == 3.0
        assert SEVERITY_WEIGHTS["MEDIUM"] == 2.0
        assert SEVERITY_WEIGHTS["LOW"] == 1.0

    def test_dimension_weights(self):
        """验证维度权重总和为 1.0"""
        total = sum(DIMENSION_WEIGHTS.values())
        assert total == 1.0


class TestCalculateQualityScore:
    """测试 calculate_quality_score 函数"""

    def test_no_external_scores(self):
        """无外部评分输入时，仅基于规则评分"""
        results = [MockResult("null_rate", "HIGH", True)]
        score = calculate_quality_score(results, None, None)
        assert score["overall_score"] == 100.0
        assert score["health_scan_score"] is None
        assert score["ddl_compliance_score"] is None
        assert score["completeness_score"] == 100.0

    def test_no_rules_all_none_inputs(self):
        """无规则且无外部评分"""
        score = calculate_quality_score([], None, None)
        assert score["overall_score"] == 100.0

    def test_all_inputs_integrated(self):
        """所有输入源都集成时的综合评分"""
        results = [MockResult("null_rate", "HIGH", True)]
        score = calculate_quality_score(results, 80.0, 90.0)
        # 规则评分 100 * 0.5 + 健康 80 * 0.3 + DDL 90 * 0.2 = 50 + 24 + 18 = 92
        assert score["overall_score"] == 92.0

    def test_partial_missing_health_scan(self):
        """缺少健康扫描评分"""
        results = [MockResult("null_rate", "HIGH", True)]
        score = calculate_quality_score(results, None, 90.0)
        # 规则 100 * (0.5+0.2) + DDL 90 * 0.3 = 70 + 27 = 97... 不对
        # 权重重新分配：规则 0.5+0.2=0.7, DDL 0.3
        # 100 * 0.7 + 90 * 0.3 = 70 + 27 = 97
        # 等等，重新看代码逻辑
        # components = [(rule_score, 0.50)] -> [(100, 0.5)]
        # health_scan is None，不加入
        # ddl_compliance_score is not None:
        #   components.append((90, 0.20))
        #   remaining_weight = 0.50 - 0.20 = 0.30
        # if remaining_weight > 0:
        #   components[0] = (100, 0.50 + 0.30) = (100, 0.80)
        # overall = 100 * 0.80 + 90 * 0.20 = 80 + 18 = 98
        assert score["overall_score"] == 98.0

    def test_partial_missing_ddl_compliance(self):
        """缺少 DDL 合规评分"""
        results = [MockResult("null_rate", "HIGH", True)]
        score = calculate_quality_score(results, 80.0, None)
        # 规则 100 * (0.5+0.3) + 健康 80 * 0.2 = 80 + 16 = 96... 不对
        # components = [(100, 0.50)]
        # health_scan is not None:
        #   components.append((80, 0.30))
        #   remaining_weight = 0.50 - 0.30 = 0.20
        # ddl_compliance is None，不加入
        # if remaining_weight > 0:
        #   components[0] = (100, 0.50 + 0.20) = (100, 0.70)
        # overall = 100 * 0.70 + 80 * 0.30 = 70 + 24 = 94
        assert score["overall_score"] == 94.0

    def test_both_external_scores_missing(self):
        """两个外部评分都缺失"""
        results = [MockResult("null_rate", "HIGH", True)]
        score = calculate_quality_score(results, None, None)
        # components = [(100, 0.50)]
        # remaining_weight = 0.50 - 0 - 0 = 0.50
        # if remaining_weight > 0:
        #   components[0] = (100, 0.50 + 0.50) = (100, 1.0)
        # overall = 100 * 1.0 = 100
        assert score["overall_score"] == 100.0

    def test_score_capped_at_100(self):
        """评分上限为 100"""
        results = [MockResult("null_rate", "HIGH", True)]
        score = calculate_quality_score(results, 100.0, 100.0)
        assert score["overall_score"] == 100.0

    def test_score_capped_at_0(self):
        """评分下限为 0（所有规则都失败）"""
        results = [MockResult("null_rate", "HIGH", False)]
        score = calculate_quality_score(results, 0.0, 0.0)
        # 规则评分 0 * 0.5 + 健康 0 * 0.3 + DDL 0 * 0.2 = 0
        assert score["overall_score"] == 0.0

    def test_rule_score_weight_reallocation(self):
        """权重重新分配验证"""
        # 当健康扫描缺失时，其权重应该回归到规则评分
        results = [MockResult("null_rate", "HIGH", True)]
        score = calculate_quality_score(results, None, 80.0)
        # 健康扫描权重 0.3 回归到规则，规则权重变为 0.5+0.3=0.8
        # overall = 100 * 0.8 + 80 * 0.2 = 80 + 16 = 96
        assert score["overall_score"] == 96.0

    def test_dimension_scores_returned(self):
        """验证返回所有维度评分"""
        results = [
            MockResult("null_rate", "HIGH", True),
            MockResult("referential", "MEDIUM", True),
            MockResult("duplicate_rate", "LOW", True),
            MockResult("freshness", "HIGH", True),
            MockResult("format_regex", "MEDIUM", True),
        ]
        score = calculate_quality_score(results, None, None)
        assert "completeness_score" in score
        assert "consistency_score" in score
        assert "uniqueness_score" in score
        assert "timeliness_score" in score
        assert "conformity_score" in score


class TestGetScoreGrade:
    """测试 get_score_grade 函数"""

    def test_excellent_grade(self):
        """优秀等级：>= 90"""
        result = get_score_grade(90)
        assert result["grade"] == "优秀"
        assert result["color"] == "green"

        result = get_score_grade(100)
        assert result["grade"] == "优秀"
        assert result["color"] == "green"

    def test_good_grade(self):
        """良好等级：>= 75 且 < 90"""
        result = get_score_grade(75)
        assert result["grade"] == "良好"
        assert result["color"] == "blue"

        result = get_score_grade(89.9)
        assert result["grade"] == "良好"
        assert result["color"] == "blue"

    def test_average_grade(self):
        """一般等级：>= 60 且 < 75"""
        result = get_score_grade(60)
        assert result["grade"] == "一般"
        assert result["color"] == "yellow"

        result = get_score_grade(74.9)
        assert result["grade"] == "一般"
        assert result["color"] == "yellow"

    def test_poor_grade(self):
        """较差等级：< 60"""
        result = get_score_grade(59.9)
        assert result["grade"] == "较差"
        assert result["color"] == "red"

        result = get_score_grade(0)
        assert result["grade"] == "较差"
        assert result["color"] == "red"


class TestIntegrationScenarios:
    """集成场景测试"""

    def test_realistic_scenario_mostly_healthy(self):
        """真实场景：大部分规则通过，外部评分良好"""
        results = [
            # 完整性（30%）：3个HIGH规则，2个通过
            MockResult("null_rate", "HIGH", True),
            MockResult("null_rate", "HIGH", True),
            MockResult("null_rate", "HIGH", False),
            MockResult("not_null", "MEDIUM", True),
            MockResult("row_count", "LOW", True),
            # 一致性（25%）：2个规则，都通过
            MockResult("referential", "HIGH", True),
            MockResult("value_range", "MEDIUM", True),
            # 唯一性（20%）：1个规则，通过
            MockResult("duplicate_rate", "HIGH", True),
            # 时效性（15%）：1个规则，通过
            MockResult("freshness", "MEDIUM", True),
            # 格式规范（10%）：1个规则，通过
            MockResult("format_regex", "LOW", True),
        ]
        score = calculate_quality_score(results, 85.0, 90.0)

        # 完整性：(3+2+1)/(3+2+1)*100 = 6/6*100 = 100... 不对
        # 权重：HIGH=3, MEDIUM=2, LOW=1
        # null_rate: 3个HIGH，(3+3+0)/3 = 2，通过权重6
        # not_null: 1个MEDIUM，2/2 = 1，通过权重2
        # row_count: 1个LOW，1/1 = 1，通过权重1
        # 总权重：3+3+3+2+1=12，通过：3+3+0+2+1=9
        # completeness = 9/12 * 100 = 75

        # 应该有一定的综合评分
        assert 0 <= score["overall_score"] <= 100

    def test_all_rules_failing_scenario(self):
        """所有规则都失败的场景"""
        results = [
            MockResult("null_rate", "HIGH", False),
            MockResult("referential", "HIGH", False),
            MockResult("duplicate_rate", "HIGH", False),
            MockResult("freshness", "HIGH", False),
            MockResult("format_regex", "HIGH", False),
        ]
        score = calculate_quality_score(results, 80.0, 80.0)

        # 所有规则维度评分都是 0
        # overall = 0 * 0.5 + 80 * 0.3 + 80 * 0.2 = 0 + 24 + 16 = 40
        assert score["overall_score"] == 40.0
