"""跨方言 SQL Builder — Spec 15 §3.2 + §3.3"""

from abc import ABC, abstractmethod
from typing import Any, Optional
import re


class DialectAwareBuilder:
    """跨方言 SQL Builder"""

    DIALECTS = ["postgresql", "mysql", "mssql", "clickhouse", "oracle", "dameng"]

    def build_sql(
        self,
        rule_type: str,
        table_name: str,
        column_name: str,
        threshold: dict,
        dialect: str = "postgresql",
    ) -> str:
        """根据规则类型和方言生成检测 SQL"""
        builders = {
            "null_rate": self._build_null_rate,
            "not_null": self._build_not_null,
            "row_count": self._build_row_count,
            "duplicate_rate": self._build_duplicate_rate,
            "unique_count": self._build_unique_count,
            "referential": self._build_referential,
            "cross_field": self._build_cross_field,
            "value_range": self._build_value_range,
            "freshness": self._build_freshness,
            "latency": self._build_latency,
            "format_regex": self._build_format_regex,
            "enum_check": self._build_enum_check,
            "custom_sql": self._build_custom_sql,
        }
        builder = builders.get(rule_type)
        if not builder:
            raise ValueError(f"不支持的规则类型: {rule_type}")
        return builder(table_name, column_name, threshold, dialect)

    def _build_null_rate(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        max_scan = threshold.get("max_scan_rows", 1_000_000)
        if dialect == "postgresql":
            return (
                f"SELECT CASE WHEN COUNT(*) = 0 THEN 0 "
                f"ELSE COUNT(*) FILTER (WHERE {col} IS NULL)::float / COUNT(*)::float END "
                f"FROM {table} LIMIT {max_scan}"
            )
        elif dialect == "mysql":
            return (
                f"SELECT CASE WHEN COUNT(*) = 0 THEN 0 "
                f"ELSE COUNT(CASE WHEN {col} IS NULL THEN 1 END) / COUNT(*) END "
                f"FROM {table} LIMIT {max_scan}"
            )
        elif dialect == "mssql":
            return (
                f"SELECT CASE WHEN COUNT(*) = 0 THEN 0 "
                f"ELSE CAST(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) END "
                f"FROM {table}"
            )
        else:
            return (
                f"SELECT CASE WHEN COUNT(*) = 0 THEN 0 "
                f"ELSE COUNT(CASE WHEN {col} IS NULL THEN 1 END) * 1.0 / COUNT(*) END "
                f"FROM {table}"
            )

    def _build_not_null(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        max_scan = threshold.get("max_scan_rows", 1_000_000)
        return f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL LIMIT {max_scan}"

    def _build_row_count(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        # row_count returns total row count; comparison happens in RuleExecutor._compare
        # SQL returns scalar row count; RuleExecutor checks against min/max
        max_scan = threshold.get("max_scan_rows", 1_000_000)
        return f"SELECT COUNT(*) FROM {table} LIMIT {max_scan}"

    def _build_duplicate_rate(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        max_scan = threshold.get("max_scan_rows", 1_000_000)
        if dialect == "postgresql":
            return (
                f"SELECT CASE WHEN COUNT(*) = 0 THEN 0 "
                f"ELSE 1.0 - COUNT(DISTINCT {col})::float / COUNT(*)::float END "
                f"FROM {table} LIMIT {max_scan}"
            )
        else:
            return (
                f"SELECT CASE WHEN COUNT(*) = 0 THEN 0 "
                f"ELSE 1.0 - COUNT(DISTINCT {col}) / COUNT(*) END "
                f"FROM {table}"
            )

    def _build_unique_count(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        # Returns scalar COUNT(DISTINCT col); comparison happens in executor
        return f"SELECT COUNT(DISTINCT {col}) FROM {table}"

    def _build_referential(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        ref_table = threshold["ref_table"]
        ref_col = threshold["ref_col"]
        max_scan = threshold.get("max_scan_rows", 500_000)
        return (
            f"SELECT COUNT(*) FROM {table} t "
            f"WHERE NOT EXISTS (SELECT 1 FROM {ref_table} r WHERE r.{ref_col} = t.{col}) "
            f"LIMIT {max_scan}"
        )

    def _build_cross_field(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        expr = threshold["expression"]
        return f"SELECT COUNT(*) FROM {table} WHERE NOT ({expr})"

    def _build_value_range(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        min_val = threshold.get("min")
        max_val = threshold.get("max")
        allow_null = threshold.get("allow_null", False)
        cond = []
        if min_val is not None:
            cond.append(f"{col} < {min_val}")
        if max_val is not None:
            cond.append(f"{col} > {max_val}")
        if not allow_null:
            cond.append(f"{col} IS NOT NULL")
        where_clause = " OR ".join(cond) if cond else "1=0"
        return f"SELECT COUNT(*) FROM {table} WHERE {where_clause}"

    def _build_freshness(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        time_field = threshold["time_field"]
        if dialect == "postgresql":
            return (
                f"SELECT EXTRACT(EPOCH FROM NOW() - MAX({time_field})) / 3600.0 "
                f"FROM {table}"
            )
        elif dialect == "mysql":
            return f"SELECT TIMESTAMPDIFF(HOUR, MAX({time_field}), NOW()) FROM {table}"
        elif dialect == "mssql":
            return f"SELECT DATEDIFF(HOUR, MAX({time_field}), GETDATE()) FROM {table}"
        else:
            return f"SELECT (NOW() - MAX({time_field})) / 3600.0 FROM {table}"

    def _build_latency(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        time_field = threshold["time_field"]
        if dialect == "postgresql":
            return f"SELECT EXTRACT(EPOCH FROM NOW() - MAX({time_field})) / 3600.0 FROM {table}"
        elif dialect == "mysql":
            return f"SELECT TIMESTAMPDIFF(HOUR, MAX({time_field}), NOW()) FROM {table}"
        elif dialect == "mssql":
            return f"SELECT DATEDIFF(HOUR, MAX({time_field}), GETDATE()) FROM {table}"
        else:
            return f"SELECT (NOW() - MAX({time_field})) / 3600.0 FROM {table}"

    def _build_format_regex(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        pattern = threshold["pattern"]
        allow_null = threshold.get("allow_null", False)
        if dialect == "postgresql":
            # PostgreSQL re2: !~ for regex match, pattern is already anchored
            if allow_null:
                return f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} !~ '{pattern}'"
            else:
                return f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} !~ '{pattern}'"
        elif dialect == "mysql":
            # MySQL: NOT REGEXP for negated match, IS NOT NULL for explicit null check
            if allow_null:
                return f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL OR ({col} IS NOT NULL AND {col} NOT REGEXP '{pattern}')"
            else:
                return f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} NOT REGEXP '{pattern}'"
        else:
            if allow_null:
                return f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL OR ({col} IS NOT NULL AND {col} NOT LIKE '{pattern}')"
            else:
                return f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} NOT LIKE '{pattern}'"

    def _build_enum_check(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        allowed = ",".join([f"'{v}'" for v in threshold["allowed_values"]])
        allow_null = threshold.get("allow_null", False)
        null_part = f" OR {col} IS NULL" if allow_null else ""
        return (
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE {col} NOT IN ({allowed}) AND {col} IS NOT NULL{null_part}"
        )

    def _build_custom_sql(self, table: str, col: str, threshold: dict, dialect: str) -> str:
        raise NotImplementedError("custom_sql 规则由单独执行器处理")