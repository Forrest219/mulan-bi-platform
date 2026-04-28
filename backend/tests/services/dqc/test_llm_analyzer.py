"""DQC LLM 根因分析器单元测试"""
import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from services.dqc.llm_analyzer import DqcLlmAnalyzer, LlmAnalysisResult, DqcLlmAnalyzer


class TestLlmAnalysisResult:
    """LLM 分析结果测试"""

    def test_result_creation(self):
        """结果对象创建"""
        result = LlmAnalysisResult(
            root_cause=["原因1", "原因2"],
            fix_suggestion=["建议1"],
            fix_sql=["SELECT * FROM table"],
            confidence="high",
            raw_response="{}",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=1000,
        )
        assert result.root_cause == ["原因1", "原因2"]
        assert result.fix_suggestion == ["建议1"]
        assert result.confidence == "high"
        assert result.prompt_tokens == 100


class TestDqcLlmAnalyzerParsing:
    """LLM 分析器响应解析测试"""

    def test_parse_valid_json(self):
        """解析有效 JSON"""
        analyzer = DqcLlmAnalyzer()
        content = json.dumps({
            "root_cause": ["原因1", "原因2"],
            "fix_suggestion": ["建议1"],
            "fix_sql": ["SELECT * FROM table"],
            "confidence": "high"
        })
        result = analyzer._parse_llm_response(content)

        assert result.root_cause == ["原因1", "原因2"]
        assert result.fix_suggestion == ["建议1"]
        assert result.fix_sql == ["SELECT * FROM table"]
        assert result.confidence == "high"

    def test_parse_json_with_extra_whitespace(self):
        """解析带多余空白的 JSON"""
        analyzer = DqcLlmAnalyzer()
        content = '''
        {
            "root_cause": ["原因1"],
            "fix_suggestion": ["建议1"],
            "fix_sql": [],
            "confidence": "medium"
        }
        '''
        result = analyzer._parse_llm_response(content)
        assert result.root_cause == ["原因1"]
        assert result.confidence == "medium"

    def test_parse_invalid_json_returns_empty(self):
        """无效 JSON 返回空结果"""
        analyzer = DqcLlmAnalyzer()
        result = analyzer._parse_llm_response("这不是 JSON")
        assert result.root_cause == []
        assert result.fix_suggestion == []
        assert result.fix_sql == []
        assert result.confidence == "low"

    def test_parse_json_without_fields(self):
        """JSON 缺少字段时使用默认值"""
        analyzer = DqcLlmAnalyzer()
        content = json.dumps({"root_cause": ["原因1"]})
        result = analyzer._parse_llm_response(content)
        assert result.root_cause == ["原因1"]
        assert result.fix_suggestion == []
        assert result.fix_sql == []
        assert result.confidence == "medium"  # 默认值


class TestDqcLlmAnalyzerPromptBuilding:
    """LLM 分析器提示词构建测试"""

    def test_build_prompt_with_failing_dimensions(self):
        """构建包含失败维度的提示词"""
        analyzer = DqcLlmAnalyzer()

        # Mock asset
        asset = MagicMock()
        asset.datasource_id = 1
        asset.schema_name = "public"
        asset.table_name = "orders"
        asset.display_name = "订单表"

        # Mock snapshot
        snapshot = MagicMock()
        snapshot.confidence_score = 65.0
        snapshot.signal = "P1"
        snapshot.dimension_scores = {
            "completeness": 50.0,
            "accuracy": 80.0,
            "timeliness": 60.0,
        }
        snapshot.dimension_signals = {
            "completeness": "P0",
            "accuracy": "GREEN",
            "timeliness": "P1",
        }

        # Mock recent results
        recent_results = [
            MagicMock(
                rule_type="null_rate",
                dimension="completeness",
                passed=False,
                actual_value=0.15,
                error_message=None,
            )
        ]

        prompt = analyzer._build_prompt(asset, snapshot, ["completeness", "timeliness"], recent_results)

        assert "订单表" in prompt
        assert "completeness" in prompt
        assert "timeliness" in prompt
        assert "65.0" in prompt
        assert "P1" in prompt

    def test_build_prompt_empty_failing_dims(self):
        """无失败维度时构建提示词"""
        analyzer = DqcLlmAnalyzer()

        asset = MagicMock()
        asset.datasource_id = 1
        asset.schema_name = "public"
        asset.table_name = "orders"
        asset.display_name = "订单表"

        snapshot = MagicMock()
        snapshot.confidence_score = 95.0
        snapshot.signal = "GREEN"
        snapshot.dimension_scores = {}
        snapshot.dimension_signals = {}

        prompt = analyzer._build_prompt(asset, snapshot, [], [])

        assert "订单表" in prompt
        assert "无" in prompt  # 无失败维度


class TestDqcLlmAnalyzerIntegration:
    """LLM 分析器集成测试"""

    def test_get_failing_dimensions(self):
        """获取失败维度列表"""
        analyzer = DqcLlmAnalyzer()
        snapshot = MagicMock()
        snapshot.dimension_signals = {
            "completeness": "P0",
            "accuracy": "GREEN",
            "timeliness": "P1",
            "validity": "GREEN",
        }

        failing = analyzer._get_failing_dimensions(snapshot)
        assert set(failing) == {"completeness", "timeliness"}

    def test_get_failing_dimensions_empty(self):
        """无失败维度"""
        analyzer = DqcLlmAnalyzer()
        snapshot = MagicMock()
        snapshot.dimension_signals = {
            "completeness": "GREEN",
            "accuracy": "GREEN",
        }

        failing = analyzer._get_failing_dimensions(snapshot)
        assert failing == []

    def test_get_failing_dimensions_none(self):
        """dimension_signals 为 None"""
        analyzer = DqcLlmAnalyzer()
        snapshot = MagicMock()
        snapshot.dimension_signals = None

        failing = analyzer._get_failing_dimensions(snapshot)
        assert failing == []

    def test_build_suggested_rules(self):
        """从 fix_sql 推断建议规则"""
        analyzer = DqcLlmAnalyzer()
        asset = MagicMock()
        asset.id = 1
        asset.schema_name = "public"
        asset.table_name = "orders"

        fix_sql = [
            "SELECT COUNT(*) FROM orders WHERE status = 'cancelled'",
            "SELECT * FROM orders WHERE email IS NULL",
        ]

        suggested = analyzer._build_suggested_rules(asset, fix_sql)

        # 应该识别出 null_rate 规则
        assert len(suggested) >= 1
        rule_types = [r.get("rule_type") for r in suggested]
        assert "null_rate" in rule_types

    def test_build_suggested_rules_non_select_ignored(self):
        """非 SELECT 语句被忽略"""
        analyzer = DqcLlmAnalyzer()
        asset = MagicMock()
        asset.id = 1

        fix_sql = [
            "UPDATE orders SET status = 'cancelled' WHERE id = 1",  # 非 SELECT
            "INSERT INTO orders VALUES (1)",  # 非 SELECT
        ]

        suggested = analyzer._build_suggested_rules(asset, fix_sql)
        # 不应识别出任何规则
        assert len(suggested) == 0


class TestTriggerLlmAnalysis:
    """触发 LLM 分析测试"""

    def test_skip_non_p0_p1_signal(self):
        """非 P0/P1 信号跳过分析"""
        analyzer = DqcLlmAnalyzer()

        # Mock DAO
        mock_dao = MagicMock()
        analyzer.dao = mock_dao

        # Mock asset
        mock_asset = MagicMock()
        mock_dao.get_asset.return_value = mock_asset

        # Mock snapshot with GREEN signal
        mock_snapshot = MagicMock()
        mock_snapshot.signal = "GREEN"
        mock_snapshot.dimension_signals = {"completeness": "GREEN"}
        mock_dao.get_latest_snapshot.return_value = mock_snapshot

        # Mock db
        mock_db = MagicMock()

        result = analyzer.analyze_asset(
            mock_db,
            asset_id=1,
            cycle_id=uuid4(),
            trigger="p1_triggered",
        )

        assert result is None  # 应该跳过

    def test_skip_no_snapshot(self):
        """无快照时跳过"""
        analyzer = DqcLlmAnalyzer()

        mock_dao = MagicMock()
        analyzer.dao = mock_dao
        mock_dao.get_asset.return_value = MagicMock()
        mock_dao.get_latest_snapshot.return_value = None

        mock_db = MagicMock()

        result = analyzer.analyze_asset(
            mock_db,
            asset_id=1,
            cycle_id=uuid4(),
            trigger="p0_triggered",
        )

        assert result is None
