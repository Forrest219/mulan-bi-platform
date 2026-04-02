"""数仓健康检查引擎 - 复用 DDL 扫描器"""
import logging
import time
from typing import Dict, Any

from ..ddl_checker.scanner import DDLScanner
from .models import HealthScanDatabase

logger = logging.getLogger(__name__)

# ViolationLevel -> severity 映射
LEVEL_MAP = {
    "error": "high",
    "warning": "medium",
    "info": "low",
}


class HealthScanEngine:
    """健康扫描引擎"""

    def __init__(self, db_config: Dict[str, Any]):
        """
        Args:
            db_config: {db_type, host, port, user, password, database}
        """
        self.db_config = db_config

    def run_scan(self, scan_db: HealthScanDatabase, scan_id: int) -> Dict[str, Any]:
        """
        执行扫描并写入结果。

        Returns:
            {status, total_tables, total_issues, health_score, ...}
        """
        scanner = DDLScanner(enable_logging=False)
        start_time = time.time()

        try:
            if not scanner.connect_database(self.db_config):
                scan_db.finish_scan(scan_id, status="failed", error_message="数据库连接失败")
                return {"status": "failed", "error": "数据库连接失败"}

            result = scanner.scan_all_tables(log_scan=False)

            if not result.success:
                scan_db.finish_scan(scan_id, status="failed", error_message=result.error)
                return {"status": "failed", "error": result.error}

            report = result.report

            # 将 Violation 转换为 HealthScanIssue
            issues = []
            for table_name, violations in report.table_results.items():
                for v in violations:
                    level_str = v["level"] if isinstance(v, dict) else v.level.value
                    rule_name = v["rule_name"] if isinstance(v, dict) else v.rule_name
                    message = v["message"] if isinstance(v, dict) else v.message
                    col_name = v.get("column_name", "") if isinstance(v, dict) else v.column_name
                    suggestion = v.get("suggestion", "") if isinstance(v, dict) else v.suggestion

                    severity = LEVEL_MAP.get(level_str, "low")
                    obj_type = "field" if col_name else "table"
                    obj_name = f"{table_name}.{col_name}" if col_name else table_name

                    issues.append({
                        "severity": severity,
                        "object_type": obj_type,
                        "object_name": obj_name,
                        "database_name": self.db_config.get("database", ""),
                        "issue_type": rule_name,
                        "description": message,
                        "suggestion": suggestion,
                    })

            # 统计
            high = sum(1 for i in issues if i["severity"] == "high")
            medium = sum(1 for i in issues if i["severity"] == "medium")
            low = sum(1 for i in issues if i["severity"] == "low")
            total_tables = report.total_tables
            total_issues = len(issues)

            # 健康分：扣分制，error 扣 5 分，warning 扣 2 分，info 扣 0.5 分，最低 0 分
            deduction = high * 5 + medium * 2 + low * 0.5
            health_score = max(0.0, round(100 - deduction, 1))

            # 批量写入问题
            if issues:
                scan_db.batch_create_issues(scan_id, issues)

            # 更新扫描记录
            scan_db.finish_scan(
                scan_id,
                status="success",
                total_tables=total_tables,
                total_issues=total_issues,
                high_count=high,
                medium_count=medium,
                low_count=low,
                health_score=health_score,
            )

            duration = round(time.time() - start_time, 1)
            logger.info("Health scan #%d completed: %d tables, %d issues, score=%.1f, %.1fs",
                        scan_id, total_tables, total_issues, health_score, duration)

            return {
                "status": "success",
                "total_tables": total_tables,
                "total_issues": total_issues,
                "high_count": high,
                "medium_count": medium,
                "low_count": low,
                "health_score": health_score,
                "duration_sec": duration,
            }

        except Exception as e:
            logger.error("Health scan #%d failed: %s", scan_id, e, exc_info=True)
            scan_db.finish_scan(scan_id, status="failed", error_message=str(e))
            return {"status": "failed", "error": str(e)}

        finally:
            scanner.disconnect_database()
