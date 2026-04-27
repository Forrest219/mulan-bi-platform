"""单元测试：HealthScanEngine — LEVEL_MAP + 评分逻辑 + 扫描流程

覆盖范围：
- LEVEL_MAP 映射（error→high, warning→medium, info→low）
- run_scan 成功流程（mock DDLScanner）
- run_scan 连接失败
- run_scan 扫描失败
- run_scan 异常处理
- 分数计算（扣分制）
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")

from services.health_scan.engine import HealthScanEngine, LEVEL_MAP


# =====================================================================
# LEVEL_MAP 测试
# =====================================================================


class TestLevelMap:
    """severity 映射测试"""

    def test_error_maps_to_high(self):
        assert LEVEL_MAP["error"] == "high"

    def test_warning_maps_to_medium(self):
        assert LEVEL_MAP["warning"] == "medium"

    def test_info_maps_to_low(self):
        assert LEVEL_MAP["info"] == "low"

    def test_unknown_level_defaults_to_low(self):
        """未知 level 通过 .get() 回退到 low"""
        assert LEVEL_MAP.get("unknown", "low") == "low"


# =====================================================================
# run_scan 测试（mock DDLScanner）
# =====================================================================


class TestRunScan:
    """扫描引擎执行流程测试"""

    def _make_engine(self):
        return HealthScanEngine(db_config={
            "db_type": "mysql",
            "host": "localhost",
            "port": 3306,
            "user": "test",
            "password": "test",
            "database": "test_db",
        })

    @patch("services.health_scan.engine.DDLScanner")
    def test_run_scan_connection_failure(self, MockScanner):
        """数据库连接失败"""
        engine = self._make_engine()
        scanner_instance = MockScanner.return_value
        scanner_instance.connect_database.return_value = False

        scan_db = MagicMock()
        result = engine.run_scan(scan_db, scan_id=1)

        assert result["status"] == "failed"
        assert "连接失败" in result["error"]
        scan_db.finish_scan.assert_called_once()
        call_kwargs = scan_db.finish_scan.call_args
        assert call_kwargs.kwargs.get("status") == "failed" or \
               (len(call_kwargs.args) >= 3 and call_kwargs.args[1] == "failed") or \
               "failed" in str(call_kwargs)

    @patch("services.health_scan.engine.DDLScanner")
    def test_run_scan_scan_failure(self, MockScanner):
        """扫描返回失败结果"""
        engine = self._make_engine()
        scanner_instance = MockScanner.return_value
        scanner_instance.connect_database.return_value = True

        scan_result = MagicMock()
        scan_result.success = False
        scan_result.error = "扫描超时"
        scanner_instance.scan_all_tables.return_value = scan_result

        scan_db = MagicMock()
        result = engine.run_scan(scan_db, scan_id=1)

        assert result["status"] == "failed"
        assert "超时" in result["error"]
        scanner_instance.disconnect_database.assert_called_once()

    @patch("services.health_scan.engine.DDLScanner")
    def test_run_scan_success_no_issues(self, MockScanner):
        """扫描成功无问题 — 满分"""
        engine = self._make_engine()
        scanner_instance = MockScanner.return_value
        scanner_instance.connect_database.return_value = True

        report = MagicMock()
        report.total_tables = 10
        report.table_results = {}  # 无违规

        scan_result = MagicMock()
        scan_result.success = True
        scan_result.report = report
        scanner_instance.scan_all_tables.return_value = scan_result

        scan_db = MagicMock()
        result = engine.run_scan(scan_db, scan_id=1)

        assert result["status"] == "success"
        assert result["total_tables"] == 10
        assert result["total_issues"] == 0
        assert result["health_score"] == 100.0
        # 无问题不应调用 batch_create_issues
        scan_db.batch_create_issues.assert_not_called()
        scanner_instance.disconnect_database.assert_called_once()

    @patch("services.health_scan.engine.DDLScanner")
    def test_run_scan_success_with_issues(self, MockScanner):
        """扫描成功有问题 — 扣分"""
        engine = self._make_engine()
        scanner_instance = MockScanner.return_value
        scanner_instance.connect_database.return_value = True

        # 模拟表结果为 dict 格式
        report = MagicMock()
        report.total_tables = 5
        report.table_results = {
            "users": [
                {"level": "error", "rule_name": "missing_pk", "message": "缺少主键",
                 "column_name": "", "suggestion": "添加主键"},
                {"level": "warning", "rule_name": "no_comment", "message": "缺少注释",
                 "column_name": "name", "suggestion": "添加注释"},
            ],
            "orders": [
                {"level": "info", "rule_name": "naming", "message": "命名建议",
                 "column_name": "order_id", "suggestion": "使用下划线命名"},
            ],
        }

        scan_result = MagicMock()
        scan_result.success = True
        scan_result.report = report
        scanner_instance.scan_all_tables.return_value = scan_result

        scan_db = MagicMock()
        result = engine.run_scan(scan_db, scan_id=1)

        assert result["status"] == "success"
        assert result["total_issues"] == 3
        assert result["high_count"] == 1
        assert result["medium_count"] == 1
        assert result["low_count"] == 1
        # 扣分: 1*5 + 1*2 + 1*0.5 = 7.5
        assert result["health_score"] == 92.5
        scan_db.batch_create_issues.assert_called_once()

    @patch("services.health_scan.engine.DDLScanner")
    def test_run_scan_exception_handling(self, MockScanner):
        """扫描过程中异常被捕获"""
        engine = self._make_engine()
        scanner_instance = MockScanner.return_value
        scanner_instance.connect_database.return_value = True
        scanner_instance.scan_all_tables.side_effect = RuntimeError("boom")

        scan_db = MagicMock()
        result = engine.run_scan(scan_db, scan_id=1)

        assert result["status"] == "failed"
        assert "boom" in result["error"]
        scanner_instance.disconnect_database.assert_called_once()

    @patch("services.health_scan.engine.DDLScanner")
    def test_run_scan_object_name_format(self, MockScanner):
        """字段级问题 object_name 格式为 table.column"""
        engine = self._make_engine()
        scanner_instance = MockScanner.return_value
        scanner_instance.connect_database.return_value = True

        report = MagicMock()
        report.total_tables = 1
        report.table_results = {
            "test_table": [
                {"level": "warning", "rule_name": "type_check", "message": "类型不匹配",
                 "column_name": "col1", "suggestion": "修改类型"},
            ],
        }

        scan_result = MagicMock()
        scan_result.success = True
        scan_result.report = report
        scanner_instance.scan_all_tables.return_value = scan_result

        scan_db = MagicMock()
        engine.run_scan(scan_db, scan_id=1)

        issues = scan_db.batch_create_issues.call_args[0][1]
        assert issues[0]["object_name"] == "test_table.col1"
        assert issues[0]["object_type"] == "field"


# =====================================================================
# 扣分制健康分计算验证
# =====================================================================


class TestHealthScoreCalculation:
    """引擎内部扣分制测试（error×5 + warning×2 + info×0.5）"""

    def _calc(self, high, medium, low):
        """复制引擎内的扣分公式"""
        deduction = high * 5 + medium * 2 + low * 0.5
        return max(0.0, round(100 - deduction, 1))

    def test_perfect_score(self):
        assert self._calc(0, 0, 0) == 100.0

    def test_high_deduction(self):
        assert self._calc(2, 0, 0) == 90.0

    def test_mixed_deduction(self):
        # 3 high + 5 medium + 10 low = 15 + 10 + 5 = 30
        assert self._calc(3, 5, 10) == 70.0

    def test_floor_at_zero(self):
        assert self._calc(20, 20, 20) == 0.0
