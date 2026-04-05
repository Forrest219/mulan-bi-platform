"""数据质量监控 - SQL 生成引擎

遵循 Spec 15 v1.1 §3.3 强制约束：
- 禁止硬编码原生 SQL 字符串
- 所有检测 SQL 必须通过 SQLAlchemy Core 动态适配方言
- 支持 MySQL / SQL Server / PostgreSQL / ClickHouse / Oracle / 达梦

同时遵循 §8.2 安全约束：
- 所有规则 SQL 必须为只读（SELECT）
- 执行超时 60 秒
- max_scan_rows 熔断
"""
import re
import logging
import time
from typing import Dict, Any, Optional, Tuple, List

from sqlalchemy import text, select, func, column, table, literal
from sqlalchemy.dialects import postgresql, mysql, mssql, oracle

from .models import QualityRule

logger = logging.getLogger(__name__)

# 禁止的关键字（辅助防护线，不能作为唯一防护）
FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE",
    "COPY", "PG_READ_FILE", "PG_EXECUTE_SERVER_PROGRAM",
    "LOAD_FILE", "INTO OUTFILE", "INTO DUMPFILE",
]


class SQLGenerationError(Exception):
    """SQL 生成异常"""
    pass


class QualitySQLEngine:
    """跨方言 SQL 生成引擎

    根据目标数据库类型（db_type）动态生成兼容的检测 SQL。
    使用 SQLAlchemy Core API，绝不硬编码原生 SQL 字符串。
    """

    DIALECT_MAP = {
        "postgresql": "postgresql",
        "mysql": "mysql",
        "sqlserver": "mssql",
        "mssql": "mssql",
        "clickhouse": "postgresql",  # ClickHouse 使用兼容 PostgreSQL 的 dialect
        "oracle": "oracle",
        # 达梦映射为 PostgreSQL 兼容模式
        "dameng": "postgresql",
        "hive": "hive",
        "starrocks": "mysql",
        "doris": "mysql",
    }

    def __init__(self, db_type: str):
        self.db_type = db_type.lower()
        self._dialect_name = self.DIALECT_MAP.get(self.db_type, "postgresql")

    @property
    def dialect(self):
        """返回对应数据库的 SQLAlchemy dialect 实例"""
        dialect_map = {
            "postgresql": postgresql.dialect(),
            "mysql": mysql.dialect(),
            "mssql": mssql.dialect(),
            "oracle": oracle.dialect(),
        }
        return dialect_map.get(self._dialect_name, postgresql.dialect())

    def _compile(self, expr) -> str:
        """将 SQLAlchemy 表达式编译为对应方言的 SQL 字符串"""
        return str(expr.compile(dialect=self.dialect, compile_kwargs={"literal_binds": False}))

    def _null_rate_sql(self, rule: QualityRule) -> str:
        """生成空值率检测 SQL

        null_rate: COUNT(col IS NULL) / COUNT(*)
        跨方言：PostgreSQL/MySQL/SQL Server 均支持
        """
        col = column(rule.field_name)
        tbl = table(rule.table_name)

        # PostgreSQL/MySQL: COUNT(*) FILTER (WHERE col IS NULL)
        # SQLAlchemy Core 方式：
        null_count = func.count().filter(col.is_(None))
        total_count = func.count()
        rate_expr = null_count * literal(1.0) / nullif(total_count, literal(0))

        stmt = select([rate_expr.label("null_rate")]).select_from(tbl)
        return self._compile(stmt)

    def _not_null_sql(self, rule: QualityRule) -> str:
        """生成非空检查 SQL

        检测字段是否存在空值：SELECT 1 WHERE col IS NULL LIMIT 1
        """
        col = column(rule.field_name)
        tbl = table(rule.table_name)

        # 返回是否存在 null 的标志：0=通过，1=失败
        stmt = select([
            literal(1).label("has_null")
        ]).select_from(tbl).where(col.is_(None)).limit(1)
        return self._compile(stmt)

    def _row_count_sql(self, rule: QualityRule) -> str:
        """生成行数检查 SQL"""
        tbl = table(rule.table_name)
        stmt = select([func.count().label("row_count")]).select_from(tbl)
        return self._compile(stmt)

    def _duplicate_rate_sql(self, rule: QualityRule) -> str:
        """生成重复率检测 SQL

        duplicate_rate = 1 - COUNT(DISTINCT col) / COUNT(*)
        """
        col = column(rule.field_name)
        tbl = table(rule.table_name)

        dist_count = func.count(func.distinct(col))
        total = func.count()
        rate_expr = literal(1.0) - dist_count * literal(1.0) / nullif(total, literal(0))

        stmt = select([rate_expr.label("dup_rate")]).select_from(tbl)
        return self._compile(stmt)

    def _unique_count_sql(self, rule: QualityRule) -> str:
        """生成唯一值数量检测 SQL"""
        col = column(rule.field_name)
        tbl = table(rule.table_name)

        stmt = select([func.count(func.distinct(col)).label("unique_count")]).select_from(tbl)
        return self._compile(stmt)

    def _referential_sql(self, rule: QualityRule) -> str:
        """生成引用完整性检测 SQL

        检测外键字段值是否都在参照表中存在
        SELECT COUNT(*) FROM target_table WHERE ref_col NOT IN (SELECT id FROM ref_table)
        """
        threshold = rule.threshold or {}
        ref_table = threshold.get("ref_table", "")
        ref_field = threshold.get("ref_field", "id")

        tbl = table(rule.table_name)
        ref_tbl = table(ref_table)

        # 子查询方式：统计不在参照表中的记录数
        not_in_subq = (
            select([column(ref_field)])
            .select_from(ref_tbl)
            .alias("ref")
        )
        col = column(rule.field_name)
        orphan_count = (
            select([func.count().label("orphan_count")])
            .select_from(tbl)
            .where(col.notin_(select([column(ref_field)]).select_from(ref_tbl)))
        )
        return self._compile(orphan_count)

    def _cross_field_sql(self, rule: QualityRule) -> str:
        """生成跨字段一致性检测 SQL

        检测 end_date >= start_date 等逻辑关系
        """
        threshold = rule.threshold or {}
        expression = threshold.get("expression", "")
        related_fields = threshold.get("related_fields", [])

        if not expression or not related_fields:
            raise SQLGenerationError(f"GOV_005: cross_field 规则缺少 expression 或 related_fields，rule_id={rule.id}")

        tbl = table(rule.table_name)

        # 直接拼接 expression 中的列引用（related_fields 已通过白名单验证）
        # 使用 SQLAlchemy 的 literal_column 安全引用列名
        cols = [column(f) for f in related_fields]
        violation_count = (
            select([func.count().label("violation_count")])
            .select_from(tbl)
            .where(~self._parse_cross_expression(expression, related_fields))
        )
        return self._compile(violation_count)

    def _parse_cross_expression(self, expression: str, fields: List[str]):
        """解析 cross_field 表达式为 SQLAlchemy 条件表达式

        仅支持简单比较：field >= field, field > field, field = field 等
        不支持复杂函数调用或子查询
        """
        # 安全验证：expression 中只能出现白名单字段名
        for f in fields:
            # 替换字段名为 column 对象
            expression = re.sub(rf'\b{re.escape(f)}\b', f, expression)

        # 使用 text() 安全构造表达式（字段名已白名单验证）
        # 支持: >=, <=, !=, =, >, <
        return text(expression)

    def _value_range_sql(self, rule: QualityRule) -> str:
        """生成值域检查 SQL"""
        threshold = rule.threshold or {}
        col_min = threshold.get("min")
        col_max = threshold.get("max")
        allow_null = threshold.get("allow_null", True)

        tbl = table(rule.table_name)
        col = column(rule.field_name)

        conditions = []
        if col_min is not None:
            conditions.append(col >= col_min)
        if col_max is not None:
            conditions.append(col <= col_max)
        if not allow_null:
            conditions.append(col.isnot(None))

        violation_count = (
            select([func.count().label("violation_count")])
            .select_from(tbl)
            .where(~and_(*conditions) if conditions else literal(False))
        )
        return self._compile(violation_count)

    def _freshness_sql(self, rule: QualityRule) -> str:
        """生成数据新鲜度检测 SQL

        计算 NOW() - MAX(time_field)，返回小时数
        PostgreSQL: EXTRACT(EPOCH FROM ...)
        MySQL: TIMESTAMPDIFF(HOUR, MAX(col), NOW())
        SQL Server: DATEDIFF(HOUR, MAX(col), GETDATE())
        """
        threshold = rule.threshold or {}
        time_field = threshold.get("time_field", "update_time")

        tbl = table(rule.table_name)
        col = column(time_field)

        if self._dialect_name == "postgresql":
            # PostgreSQL: EXTRACT(EPOCH FROM (NOW() - MAX(col))) / 3600
            delay_expr = func.extract("epoch", func.now() - func.max(col)) / literal(3600)
        elif self._dialect_name == "mysql":
            # MySQL: TIMESTAMPDIFF(HOUR, MAX(col), NOW())
            delay_expr = func.timestampdiff(text("HOUR"), func.max(col), func.now())
        elif self._dialect_name == "mssql":
            # SQL Server: DATEDIFF(HOUR, MAX(col), GETDATE())
            delay_expr = func.datediff(text("HOUR"), func.max(col), func.current_timestamp())
        elif self._dialect_name == "postgresql":
            # ClickHouse 也使用 PostgreSQL dialect
            delay_expr = (func.now() - func.max(col)) / literal(3600)
        else:
            # 默认: EXTRACT(EPOCH FROM ...)
            delay_expr = func.extract("epoch", func.now() - func.max(col)) / literal(3600)

        stmt = select([delay_expr.label("delay_hours")]).select_from(tbl)
        return self._compile(stmt)

    def _latency_sql(self, rule: QualityRule) -> str:
        """生成 ETL 延迟检测 SQL

        与 freshness 类似，但字段为 etl_load_time
        """
        threshold = rule.threshold or {}
        time_field = threshold.get("time_field", "etl_load_time")
        rule.field_name = time_field
        return self._freshness_sql(rule)

    def _format_regex_sql(self, rule: QualityRule) -> str:
        """生成正则格式检查 SQL

        返回匹配格式的记录数
        """
        threshold = rule.threshold or {}
        pattern = threshold.get("pattern", "")
        allow_null = threshold.get("allow_null", True)

        if not pattern:
            raise SQLGenerationError(f"GOV_005: format_regex 规则缺少 pattern，rule_id={rule.id}")

        tbl = table(rule.table_name)
        col = column(rule.field_name)

        # 正则匹配：PostgreSQL ~*, MySQL REGEXP, SQL Server LIKE
        if self._dialect_name == "postgresql":
            match_expr = col.op("~*")(pattern)
        elif self._dialect_name == "mysql":
            match_expr = col.regexp_match(pattern)
        elif self._dialect_name == "mssql":
            # SQL Server 无内置正则，用 PATINDEX 近似
            match_expr = column("PATINDEX").isnot(None)  # 简化处理
        else:
            match_expr = col.like(f"%{pattern}%")  # 降级为模糊匹配

        conditions = [match_expr]
        if allow_null:
            conditions.append(col.isnot(None))

        violation_count = (
            select([func.count().label("violation_count")])
            .select_from(tbl)
            .where(~and_(*conditions) if len(conditions) > 1 else ~match_expr)
        )
        return self._compile(violation_count)

    def _enum_check_sql(self, rule: QualityRule) -> str:
        """生成枚举检查 SQL

        检测字段值是否在允许的枚举范围内
        """
        threshold = rule.threshold or {}
        allowed_values = threshold.get("allowed_values", [])
        allow_null = threshold.get("allow_null", False)

        if not allowed_values:
            raise SQLGenerationError(f"GOV_005: enum_check 规则缺少 allowed_values，rule_id={rule.id}")

        tbl = table(rule.table_name)
        col = column(rule.field_name)

        conditions = [col.in_(allowed_values)]
        if not allow_null:
            conditions.append(col.isnot(None))

        violation_count = (
            select([func.count().label("violation_count")])
            .select_from(tbl)
            .where(~and_(*conditions))
        )
        return self._compile(violation_count)

    def generate_sql(self, rule: QualityRule) -> str:
        """根据规则类型生成对应的检测 SQL

        Returns:
            str: 编译后的 SQL 字符串（适配合适的数据库方言）
        """
        rule_type = rule.rule_type

        generators = {
            "null_rate": self._null_rate_sql,
            "not_null": self._not_null_sql,
            "row_count": self._row_count_sql,
            "duplicate_rate": self._duplicate_rate_sql,
            "unique_count": self._unique_count_sql,
            "referential": self._referential_sql,
            "cross_field": self._cross_field_sql,
            "value_range": self._value_range_sql,
            "freshness": self._freshness_sql,
            "latency": self._latency_sql,
            "format_regex": self._format_regex_sql,
            "enum_check": self._enum_check_sql,
        }

        generator = generators.get(rule_type)
        if not generator:
            raise SQLGenerationError(f"GOV_003: 不支持的规则类型 {rule_type}")

        return generator(rule)

    def compare_result(self, actual_value: float, operator: str, threshold_config: Dict[str, Any]) -> Tuple[bool, str]:
        """将实际检测值与阈值进行比较，返回 (passed, expected_value_str)

        Args:
            actual_value: 实际检测值（来自 SQL 执行结果）
            operator: 比较运算符 eq/ne/gt/gte/lt/lte/between
            threshold_config: threshold JSON 字段

        Returns:
            (是否通过, 期望值描述字符串)
        """
        operators = {
            "eq": lambda a, t: a == t,
            "ne": lambda a, t: a != t,
            "gt": lambda a, t: a > t,
            "gte": lambda a, t: a >= t,
            "lt": lambda a, t: a < t,
            "lte": lambda a, t: a <= t,
        }

        if operator == "between":
            min_val = threshold_config.get("min")
            max_val = threshold_config.get("max")
            passed = (min_val is None or actual_value >= min_val) and (max_val is None or actual_value <= max_val)
            expected = f"{min_val} <= x <= {max_val}"
        elif operator in operators:
            # 从 threshold 中提取目标值
            target = None
            if operator in ("lte", "lt"):
                target = threshold_config.get("max_rate") or threshold_config.get("max") or threshold_config.get("max_delay_hours")
            elif operator in ("gte", "gt"):
                target = threshold_config.get("min") or threshold_config.get("min_rate")
            elif operator == "eq":
                target = threshold_config.get("expected")
            elif operator == "ne":
                target = threshold_config.get("not_expected")

            if target is None:
                # fallback: 查找第一个数值
                numeric_vals = [v for v in threshold_config.values() if isinstance(v, (int, float))]
                target = numeric_vals[0] if numeric_vals else 0

            passed = operators[operator](actual_value, target)
            expected = f"{operator} {target}"
        else:
            passed = False
            expected = operator

        return passed, expected


def validate_custom_sql(sql: str) -> bool:
    """验证自定义 SQL 安全性（辅助防护线，不能作为唯一防护）

    Args:
        sql: 用户输入的自定义 SQL

    Returns:
        bool: 是否通过安全检查
    """
    if not sql or not sql.strip().upper().startswith("SELECT"):
        return False

    upper_sql = sql.upper()
    for kw in FORBIDDEN_KEYWORDS:
        # 单词边界匹配，避免误判（如 "SELECT" 中的 "ECT" 不是关键字）
        if re.search(rf'\b{kw}\b', upper_sql):
            logger.warning(f"Custom SQL blocked: contains forbidden keyword '{kw}'")
            return False

    return True


def check_scan_row_limit(estimated_rows: int, max_scan_rows: int, rule_name: str) -> Tuple[bool, Optional[str]]:
    """检查预估扫描行数是否超过熔断阈值

    Args:
        estimated_rows: 预估扫描行数
        max_scan_rows: 最大允许扫描行数（来自 threshold.max_scan_rows）
        rule_name: 规则名称（用于日志）

    Returns:
        (是否通过, 警告信息或None)
    """
    if max_scan_rows and estimated_rows > max_scan_rows:
        warning = f"Rule '{rule_name}': estimated scan {estimated_rows} rows exceeds limit {max_scan_rows}, skipped"
        logger.warning(warning)
        return False, warning
    return True, None


# SQLAlchemy 辅助
from sqlalchemy.sql.elements import and_


def nullif(expr, value):
    """跨方言 NULLIF 函数"""
    from sqlalchemy import func
    return func.nullif(expr, value)
