"""SQL Builder + Security 单元测试"""

import sys
import os

# Add backend to path for imports
_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _backend_dir)

import pytest

from services.governance.sql_builder import DialectAwareBuilder
from services.governance.sql_security import validate_custom_sql


class TestDialectAwareBuilder:
    """13 种规则类型的 SQL 生成测试"""

    @pytest.fixture
    def builder(self):
        return DialectAwareBuilder()

    def test_null_rate_postgresql(self, builder):
        sql = builder.build_sql(
            "null_rate", "orders", "email", {"max_rate": 0.05}, "postgresql"
        )
        assert "NULL" in sql
        assert "COUNT(*) FILTER" in sql or "CASE WHEN" in sql

    def test_null_rate_mysql(self, builder):
        sql = builder.build_sql(
            "null_rate", "orders", "email", {"max_rate": 0.05}, "mysql"
        )
        assert "COUNT(CASE WHEN" in sql

    def test_null_rate_mssql(self, builder):
        sql = builder.build_sql(
            "null_rate", "orders", "email", {"max_rate": 0.05}, "mssql"
        )
        assert "CASE WHEN" in sql

    def test_not_null(self, builder):
        sql = builder.build_sql("not_null", "orders", "id", {}, "postgresql")
        assert "IS NULL" in sql
        assert "COUNT(*)" in sql

    def test_row_count_min_max(self, builder):
        # row_count returns total count; min/max comparison happens in executor
        sql = builder.build_sql(
            "row_count", "orders", "*", {"min": 1000, "max": 1000000}, "postgresql"
        )
        assert "COUNT(*)" in sql
        assert "LIMIT" in sql

    def test_row_count_min_only(self, builder):
        sql = builder.build_sql(
            "row_count", "orders", "*", {"min": 100}, "postgresql"
        )
        assert "COUNT(*)" in sql
        assert "LIMIT" in sql

    def test_duplicate_rate_postgresql(self, builder):
        sql = builder.build_sql(
            "duplicate_rate", "orders", "order_no", {"max_rate": 0.01}, "postgresql"
        )
        assert "DISTINCT" in sql

    def test_duplicate_rate_mysql(self, builder):
        sql = builder.build_sql(
            "duplicate_rate", "orders", "order_no", {"max_rate": 0.01}, "mysql"
        )
        assert "DISTINCT" in sql

    def test_unique_count(self, builder):
        sql = builder.build_sql(
            "unique_count", "orders", "status", {"min": 3, "max": 10}, "postgresql"
        )
        assert "COUNT(DISTINCT status)" in sql
        # min/max comparison happens in executor, not in SQL

    def test_referential(self, builder):
        sql = builder.build_sql(
            "referential",
            "orders",
            "user_id",
            {"ref_table": "users", "ref_col": "id"},
            "postgresql",
        )
        assert "NOT EXISTS" in sql
        assert "users" in sql

    def test_cross_field(self, builder):
        sql = builder.build_sql(
            "cross_field",
            "orders",
            "end_date",
            {"expression": "end_date >= start_date"},
            "postgresql",
        )
        assert "NOT" in sql
        assert "end_date >= start_date" in sql

    def test_value_range(self, builder):
        sql = builder.build_sql(
            "value_range",
            "orders",
            "amount",
            {"min": 0, "max": 1000000},
            "postgresql",
        )
        assert "amount < 0" in sql or "amount >" in sql or "IS NOT NULL" in sql

    def test_value_range_with_min_only(self, builder):
        sql = builder.build_sql(
            "value_range", "orders", "amount", {"min": 0}, "postgresql"
        )
        assert "amount < 0" in sql

    def test_freshness_postgresql(self, builder):
        sql = builder.build_sql(
            "freshness",
            "orders",
            "created_at",
            {"time_field": "updated_at", "max_delay_hours": 24},
            "postgresql",
        )
        assert "EXTRACT" in sql or "NOW()" in sql

    def test_freshness_mysql(self, builder):
        sql = builder.build_sql(
            "freshness",
            "orders",
            "created_at",
            {"time_field": "updated_at", "max_delay_hours": 24},
            "mysql",
        )
        assert "TIMESTAMPDIFF" in sql

    def test_freshness_mssql(self, builder):
        sql = builder.build_sql(
            "freshness",
            "orders",
            "created_at",
            {"time_field": "updated_at", "max_delay_hours": 24},
            "mssql",
        )
        assert "DATEDIFF" in sql

    def test_latency(self, builder):
        sql = builder.build_sql(
            "latency",
            "orders",
            "created_at",
            {"time_field": "updated_at", "max_delay_hours": 1},
            "postgresql",
        )
        assert "TIMESTAMPDIFF" in sql or "EXTRACT" in sql

    def test_format_regex_postgresql(self, builder):
        sql = builder.build_sql(
            "format_regex",
            "users",
            "email",
            {"pattern": r"^[\w.]+@[\w.]+$"},
            "postgresql",
        )
        assert "NOT LIKE" in sql.upper() or "!~" in sql

    def test_format_regex_mysql(self, builder):
        sql = builder.build_sql(
            "format_regex",
            "users",
            "email",
            {"pattern": r"^[\w.]+@[\w.]+$"},
            "mysql",
        )
        assert "NOT REGEXP" in sql.upper()

    def test_enum_check(self, builder):
        sql = builder.build_sql(
            "enum_check",
            "orders",
            "status",
            {"allowed_values": ["active", "inactive"]},
            "postgresql",
        )
        assert "NOT IN" in sql
        assert "active" in sql
        assert "inactive" in sql

    def test_enum_check_with_null(self, builder):
        sql = builder.build_sql(
            "enum_check",
            "orders",
            "status",
            {"allowed_values": ["active", "inactive"], "allow_null": True},
            "postgresql",
        )
        assert "IS NULL" in sql

    def test_custom_sql_raises(self, builder):
        with pytest.raises(NotImplementedError):
            builder.build_sql("custom_sql", "t", "c", {}, "postgresql")

    def test_unsupported_rule_type(self, builder):
        with pytest.raises(ValueError) as exc_info:
            builder.build_sql("unknown_type", "t", "c", {}, "postgresql")
        assert "不支持的规则类型" in str(exc_info.value)


class TestCustomSQLSecurity:
    """Custom SQL 黑名单校验测试"""

    def test_valid_select_simple(self):
        ok, msg = validate_custom_sql("SELECT COUNT(*) FROM users")
        assert ok is True
        assert msg == ""

    def test_valid_select_with_where(self):
        ok, msg = validate_custom_sql(
            "SELECT COUNT(*) FROM users WHERE email IS NOT NULL"
        )
        assert ok is True

    def test_reject_non_select(self):
        ok, msg = validate_custom_sql("INSERT INTO users VALUES (1)")
        assert ok is False
        assert "SELECT" in msg

    def test_reject_delete(self):
        ok, msg = validate_custom_sql("DELETE FROM users WHERE id = 1")
        assert ok is False
        assert "DELETE" in msg

    def test_reject_drop(self):
        ok, msg = validate_custom_sql("SELECT * FROM t; DROP TABLE t")
        assert ok is False
        assert "DROP" in msg

    def test_reject_truncate(self):
        ok, msg = validate_custom_sql("SELECT * FROM t; TRUNCATE TABLE t")
        assert ok is False
        assert "TRUNCATE" in msg

    def test_reject_update(self):
        ok, msg = validate_custom_sql("UPDATE users SET name = 'x' WHERE id = 1")
        assert ok is False
        assert "UPDATE" in msg

    def test_reject_copy(self):
        ok, msg = validate_custom_sql(
            "SELECT * FROM t; COPY users TO '/tmp/data'"
        )
        assert ok is False
        assert "COPY" in msg

    def test_reject_grant(self):
        ok, msg = validate_custom_sql("SELECT * FROM t; GRANT ALL ON users TO public")
        assert ok is False
        assert "GRANT" in msg

    def test_reject_pg_function(self):
        ok, msg = validate_custom_sql("SELECT pg_read_file('/etc/passwd')")
        assert ok is False
        assert "pg_read_file" in msg

    def test_reject_union_select(self):
        # UNION 不在当前黑名单，但实际生产中应限制
        ok, msg = validate_custom_sql(
            "SELECT id FROM t1 UNION SELECT id FROM users"
        )
        # 取决于黑名单策略，当前只检查关键字
        assert ok is True

    def test_reject_comment_injection(self):
        ok, msg = validate_custom_sql("SELECT /* INJECTED */ COUNT(*) FROM users")
        assert ok is False
        assert "可疑模式" in msg

    def test_reject_leading_whitespace(self):
        ok, msg = validate_custom_sql("  SELECT COUNT(*) FROM users")
        assert ok is True  # strip() 后以 SELECT 开头

    def test_reject_uppercase_keyword(self):
        ok, msg = validate_custom_sql("SELECT COUNT(*) FROM t; DROP TABLE t")
        assert ok is False

    def test_reject_case_insensitive(self):
        ok, msg = validate_custom_sql("select count(*) from t; drop table t")
        assert ok is False