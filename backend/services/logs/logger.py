"""日志服务"""
import json
from datetime import datetime
from typing import Dict, Any, Optional

from .models import LogDatabase, ScanLog, RuleChangeLog, OperationLog


class Logger:
    """日志服务"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._db = LogDatabase()
        return cls._instance

    def log_scan(
        self,
        database_name: str,
        db_type: str,
        table_count: int,
        total_violations: int,
        error_count: int,
        warning_count: int,
        info_count: int,
        duration_seconds: float,
        status: str = "completed",
        error_message: str = None,
        results: Dict[str, Any] = None
    ):
        """
        记录扫描日志

        Args:
            database_name: 数据库名称
            db_type: 数据库类型
            table_count: 扫描的表数量
            total_violations: 总违规数
            error_count: 错误数
            warning_count: 警告数
            info_count: 提示数
            duration_seconds: 耗时（秒）
            status: 状态 (completed/failed)
            error_message: 错误信息
            results: 详细结果
        """
        log = ScanLog(
            scan_time=datetime.now(),
            database_name=database_name,
            db_type=db_type,
            table_count=table_count,
            total_violations=total_violations,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            duration_seconds=f"{duration_seconds:.2f}",
            status=status,
            error_message=error_message,
            results_json=json.dumps(results, ensure_ascii=False) if results else None
        )
        self._db.add_scan_log(log)

        # 同时记录操作日志
        self.log_operation(
            operation_type="scan",
            target=f"{db_type}:{database_name}",
            status=status,
            details={
                "table_count": table_count,
                "total_violations": total_violations,
                "error_count": error_count,
                "warning_count": warning_count
            }
        )

    def log_rule_change(
        self,
        rule_section: str,
        change_type: str,
        operator: str = "system",
        old_value: Any = None,
        new_value: Any = None,
        description: str = None
    ):
        """
        记录规则变更日志

        Args:
            rule_section: 规则配置节
            change_type: 变更类型 (created/updated/deleted)
            operator: 操作人
            old_value: 旧值
            new_value: 新值
            description: 描述
        """
        log = RuleChangeLog(
            change_time=datetime.now(),
            operator=operator,
            rule_section=rule_section,
            change_type=change_type,
            old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None,
            new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None,
            description=description
        )
        self._db.add_rule_change_log(log)

        # 同时记录操作日志
        self.log_operation(
            operation_type="rule_change",
            target=rule_section,
            status="success",
            details={
                "change_type": change_type,
                "description": description
            }
        )

    def log_operation(
        self,
        operation_type: str,
        target: str = None,
        status: str = "success",
        details: Any = None,
        operator: str = "anonymous"
    ):
        """
        记录操作日志

        Args:
            operation_type: 操作类型
            target: 操作目标
            status: 状态
            details: 详情
            operator: 操作人
        """
        log = OperationLog(
            op_time=datetime.now(),
            operator=operator,
            operation_type=operation_type,
            target=target,
            status=status,
            details=json.dumps(details, ensure_ascii=False) if details else None
        )
        self._db.add_operation_log(log)

    def get_scan_history(self, limit: int = 100, database_name: str = None) -> list:
        """获取扫描历史"""
        logs = self._db.get_scan_logs(limit=limit, database_name=database_name)
        return [log.to_dict() for log in logs]

    def get_rule_change_history(self, limit: int = 100) -> list:
        """获取规则变更历史"""
        logs = self._db.get_rule_change_logs(limit=limit)
        return [log.to_dict() for log in logs]

    def get_operation_history(self, limit: int = 100, operation_type: str = None) -> list:
        """获取操作历史"""
        logs = self._db.get_operation_logs(limit=limit, operation_type=operation_type)
        return [log.to_dict() for log in logs]

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计数据"""
        return self._db.get_statistics()


# 全局日志实例
logger = Logger()
