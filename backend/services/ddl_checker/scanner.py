"""DDL 扫描器 - 整合连接器、解析器和验证器"""
import logging
import time
from typing import List, Dict, Any, Optional
from pathlib import Path

from .connector import DatabaseConnector
from .parser import TableInfo, ColumnInfo
from .validator import DDLValidator, Violation
from .reporter import ReportGenerator, CheckReport

logger = logging.getLogger(__name__)


class DDLScanResult:
    """扫描结果"""
    def __init__(self, success: bool, report: Optional[CheckReport] = None, error: str = ""):
        self.success = success
        self.report = report
        self.error = error


class DDLScanner:
    """DDL 扫描器"""

    def __init__(self, rules_config_path: str = None, enable_logging: bool = True):
        """
        初始化扫描器

        Args:
            rules_config_path: 兼容旧接口，传入会被忽略。规则从数据库加载。
            enable_logging: 是否启用日志记录
        """
        # rules_config_path 参数已废弃，运行时规则从数据库加载
        self.rules_config_path = None
        self.connector: Optional[DatabaseConnector] = None
        self.validator: Optional[DDLValidator] = None
        self.enable_logging = enable_logging
        self._db_config = None

    def connect_database(self, db_config: Dict[str, Any]) -> bool:
        """
        连接数据库

        Args:
            db_config: 数据库配置
                - db_type: mysql/postgresql/sqlite
                - host: 主机地址
                - port: 端口
                - user: 用户名
                - password: 密码
                - database: 数据库名

        Returns:
            连接是否成功
        """
        self.connector = DatabaseConnector(db_config)
        self._db_config = db_config
        return self.connector.connect()

    def disconnect_database(self):
        """断开数据库连接"""
        if self.connector:
            self.connector.disconnect()

    def scan_all_tables(self, log_scan: bool = True) -> DDLScanResult:
        """
        扫描所有表

        Args:
            log_scan: 是否记录日志

        Returns:
            DDLScanResult 对象
        """
        if not self.connector:
            return DDLScanResult(success=False, error="请先连接数据库")

        start_time = time.time()

        try:
            # 初始化验证器
            self.validator = DDLValidator()

            # 获取所有表
            table_names = self.connector.get_table_names()
            tables = []

            # 读取每个表的结构
            for table_name in table_names:
                table_info = self._read_table_info(table_name)
                if table_info:
                    tables.append(table_info)

            # 验证所有表
            validation_results = self.validator.validate_tables(tables)

            # 生成报告
            report = ReportGenerator.generate(validation_results)

            # 记录日志
            if log_scan and self.enable_logging:
                duration = time.time() - start_time
                self._log_scan_result(report, duration, "completed")

            return DDLScanResult(success=True, report=report)

        except Exception as e:
            duration = time.time() - start_time
            if log_scan and self.enable_logging:
                self._log_scan_result(None, duration, "failed", str(e))
            return DDLScanResult(success=False, error=str(e))

    def _log_scan_result(self, report: CheckReport, duration: float, status: str, error_message: str = None):
        """记录扫描日志"""
        try:
            from ..logs import logger

            database_name = self._db_config.get("database", "unknown") if self._db_config else "unknown"
            db_type = self._db_config.get("db_type", "mysql") if self._db_config else "mysql"

            results = None
            if report:
                results = {
                    table_name: [v.to_dict() for v in violations]
                    for table_name, violations in report.table_results.items()
                }

            logger.log_scan(
                database_name=database_name,
                db_type=db_type,
                table_count=report.total_tables if report else 0,
                total_violations=report.total_violations if report else 0,
                error_count=report.error_count if report else 0,
                warning_count=report.warning_count if report else 0,
                info_count=report.info_count if report else 0,
                duration_seconds=duration,
                status=status,
                error_message=error_message,
                results=results
            )
        except Exception as e:
            logger.warning("记录扫描日志失败: %s", e)

    def scan_table(self, table_name: str) -> DDLScanResult:
        """
        扫描单个表

        Args:
            table_name: 表名

        Returns:
            DDLScanResult 对象
        """
        if not self.connector:
            return DDLScanResult(success=False, error="请先连接数据库")

        try:
            self.validator = DDLValidator()

            table_info = self._read_table_info(table_name)
            if not table_info:
                return DDLScanResult(success=False, error=f"表 {table_name} 不存在")

            violations = self.validator.validate_table(table_info)
            validation_results = {table_name: violations}
            report = ReportGenerator.generate(validation_results)

            return DDLScanResult(success=True, report=report)

        except Exception as e:
            return DDLScanResult(success=False, error=str(e))

    def scan_sql(self, sql: str) -> DDLScanResult:
        """
        扫描 SQL 语句

        Args:
            sql: CREATE TABLE SQL 语句

        Returns:
            DDLScanResult 对象
        """
        try:
            from .parser import DDLParser

            self.validator = DDLValidator()

            table_info = DDLParser.parse_create_table(sql)
            if not table_info:
                return DDLScanResult(success=False, error="无法解析 SQL 语句")

            violations = self.validator.validate_table(table_info)
            validation_results = {table_info.name: violations}
            report = ReportGenerator.generate(validation_results)

            return DDLScanResult(success=True, report=report)

        except Exception as e:
            return DDLScanResult(success=False, error=str(e))

    def _read_table_info(self, table_name: str) -> Optional[TableInfo]:
        """读取表信息"""
        try:
            # 获取列信息
            columns_raw = self.connector.get_table_columns(table_name)
            columns = []

            for col in columns_raw:
                # 防御性检查：确保列名和数据类型不为 None
                col_name = col.get("name")
                col_type = col.get("type")

                if col_name is None or col_type is None:
                    continue

                # 检查是否为主键
                pk_info = self.connector.get_table_primary_key(table_name)
                is_pk = col_name in pk_info.get("constrained_columns", [])

                # 检查是否为外键
                fk_info = self.connector.get_table_foreign_keys(table_name)
                is_fk = col_name in sum([fk.get("constrained_columns", []) for fk in fk_info], [])

                # 获取列注释
                comment = self.connector.get_column_comment(table_name, col_name) or ""

                column = ColumnInfo(
                    name=str(col_name),
                    data_type=str(col_type),
                    nullable=col.get("nullable", True),
                    default=str(col.get("default")) if col.get("default") is not None else None,
                    comment=comment,
                    is_primary_key=is_pk,
                    is_foreign_key=is_fk,
                )
                columns.append(column)

            # 获取索引信息
            from .parser import IndexInfo
            indexes_raw = self.connector.get_table_indexes(table_name)
            indexes = [
                IndexInfo(
                    name=idx["name"],
                    columns=idx["column_names"],
                    is_unique=idx.get("unique", False),
                )
                for idx in indexes_raw
            ]

            # 获取表注释
            comment = self.connector.get_table_comment(table_name)

            return TableInfo(
                name=table_name,
                columns=columns,
                indexes=indexes,
                comment=comment,
            )

        except Exception as e:
            logger.error("读取表 %s 信息失败: %s", table_name, e, exc_info=True)
            return None

    def export_report(self, report: CheckReport, output_path: str, format: str = "html"):
        """
        导出报告

        Args:
            report: 检查报告
            output_path: 输出文件路径
            format: 报告格式 (html/json)
        """
        if format == "html":
            ReportGenerator.export_html(report, output_path)
        elif format == "json":
            ReportGenerator.export_json(report, output_path)
        else:
            raise ValueError(f"不支持的格式: {format}")
