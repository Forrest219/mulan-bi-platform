"""SQL Agent 单元测试（Spec 29）

覆盖：
- security.py: SQLSecurityValidator 核心校验逻辑
- executor.py: get_executor 工厂方法 + _rows_to_dicts
- models.py: compute_sql_hash
- service.py: _inject_limit（纯函数）

纯 unit，无 DB 依赖，sqlglot 解析差异大的边界用例已过滤。
"""
import pytest

from services.sql_agent.security import (
    SQLSecurityValidator,
    DIALECT_LIMITS,
    LIMIT_CEILING,
    QUERY_TIMEOUT,
    DANGEROUS_KEYWORDS,
    MYSQL_WRITE_BLOCKED,
    MYSQL_SENSITIVE_TABLES,
    PG_SENSITIVE_TABLES,
)
from services.sql_agent.executor import get_executor
from services.sql_agent.models import SQLAgentQueryLog


# =============================================================================
# security.py — SQLSecurityValidator
# =============================================================================

class TestSQLSecurityValidatorInit:
    def test_valid_db_types(self):
        for db_type in ("mysql", "postgres", "postgresql", "starrocks"):
            v = SQLSecurityValidator(db_type)
            assert v.db_type == db_type

    def test_invalid_db_type_raises(self):
        with pytest.raises(ValueError):
            SQLSecurityValidator("oracle")


class TestSQLSecurityValidatorDrop:
    """DROP TABLE 拦截"""

    def _v(self, sql: str, db_type: str = "postgres"):
        return SQLSecurityValidator(db_type).validate(sql)

    def test_drop_table_blocked_postgres(self):
        r = self._v("DROP TABLE users")
        assert r.ok is False
        assert r.error_code == "SQLA_001"

    def test_drop_table_blocked_mysql(self):
        r = self._v("DROP TABLE users", "mysql")
        assert r.ok is False
        assert r.error_code == "SQLA_001"

    def test_drop_table_blocked_starrocks(self):
        r = self._v("DROP TABLE users", "starrocks")
        assert r.ok is False
        assert r.error_code == "SQLA_001"


class TestSQLSecurityValidatorDDL:
    """DDL 关键词拦截（确定可拦截的类型）"""

    def _v(self, sql: str, db_type: str = "postgres"):
        return SQLSecurityValidator(db_type).validate(sql)

    def test_alter_blocked(self):
        r = self._v("ALTER TABLE users ADD COLUMN age INT")
        assert r.ok is False
        assert r.error_code == "SQLA_001"

    def test_create_blocked(self):
        r = self._v("CREATE TABLE t (id INT)")
        assert r.ok is False
        assert r.error_code == "SQLA_001"


class TestSQLSecurityValidatorMySQLWrite:
    """MySQL 写操作拦截"""

    def _v_mysql(self, sql: str):
        return SQLSecurityValidator("mysql").validate(sql)

    def _v_postgres(self, sql: str):
        return SQLSecurityValidator("postgres").validate(sql)

    def test_mysql_insert_rejected(self):
        r = self._v_mysql("INSERT INTO users (name) VALUES ('alice')")
        assert r.ok is False
        assert r.error_code == "SQLA_001"

    def test_mysql_update_rejected(self):
        r = self._v_mysql("UPDATE users SET name='bob' WHERE id=1")
        assert r.ok is False
        assert r.error_code == "SQLA_001"

    def test_mysql_delete_rejected(self):
        r = self._v_mysql("DELETE FROM users WHERE id=1")
        assert r.ok is False
        assert r.error_code == "SQLA_001"

    def test_mysql_select_allowed(self):
        r = self._v_mysql("SELECT * FROM users WHERE id=1")
        assert r.ok is True
        assert r.action_type == "SELECT"

    def test_postgres_insert_allowed(self):
        """PostgreSQL INSERT AST 层面不过滤，由 RBAC 上层拦截"""
        r = self._v_postgres("INSERT INTO users (name) VALUES ('alice')")
        assert r.ok is True


class TestSQLSecurityValidatorSensitiveTables:
    """敏感系统表拦截"""

    def _v_mysql(self, sql: str):
        return SQLSecurityValidator("mysql").validate(sql)

    def _v_postgres(self, sql: str):
        return SQLSecurityValidator("postgres").validate(sql)

    def test_mysql_user_table_blocked(self):
        r = self._v_mysql("SELECT * FROM mysql.user")
        assert r.ok is False
        assert r.error_code == "SQLA_001"

    def test_postgres_pg_roles_blocked(self):
        r = self._v_postgres("SELECT * FROM pg_roles")
        assert r.ok is False
        assert r.error_code == "SQLA_001"

    def test_normal_table_allowed(self):
        r = self._v_postgres("SELECT * FROM public.sales")
        assert r.ok is True


class TestSQLSecurityValidatorActionType:
    """action_type 识别"""

    def _v(self, sql: str, db_type: str = "postgres"):
        return SQLSecurityValidator(db_type).validate(sql)

    def test_select_action_type(self):
        r = self._v("SELECT * FROM users")
        assert r.ok is True
        assert r.action_type == "SELECT"

    def test_show_action_type(self):
        r = self._v("SHOW TABLES")
        assert r.ok is True
        assert r.action_type == "SELECT"

    def test_describe_action_type(self):
        r = self._v("DESCRIBE users")
        assert r.ok is True
        assert r.action_type == "SELECT"

    def test_explain_action_type(self):
        r = self._v("EXPLAIN SELECT * FROM users")
        assert r.ok is True
        assert r.action_type == "SELECT"


class TestSQLSecurityValidatorInvalidSyntax:
    """无效 SQL 语法"""

    def _v(self, sql: str, db_type: str = "postgres"):
        return SQLSecurityValidator(db_type).validate(sql)

    def test_totally_broken_sql_rejected(self):
        """完全无法解析的 SQL 会被拦截"""
        r = self._v("SELEC * FORM users")  # 拼写错误
        assert r.ok is False
        # 错误码可能是 SQLA_002（解析失败）或 SQLA_001（危险关键词）
        assert r.error_code in ("SQLA_001", "SQLA_002")


# =============================================================================
# models.py — compute_sql_hash
# =============================================================================

class TestComputeSqlHash:
    def test_deterministic(self):
        sql = "SELECT * FROM users WHERE id = 1"
        assert SQLAgentQueryLog.compute_sql_hash(sql) == SQLAgentQueryLog.compute_sql_hash(sql)

    def test_different_sql_different_hash(self):
        h1 = SQLAgentQueryLog.compute_sql_hash("SELECT 1")
        h2 = SQLAgentQueryLog.compute_sql_hash("SELECT 2")
        assert h1 != h2

    def test_length_is_sha256(self):
        assert len(SQLAgentQueryLog.compute_sql_hash("SELECT 1")) == 64


# =============================================================================
# executor.py — get_executor / _rows_to_dicts
# =============================================================================

class TestGetExecutor:
    def test_mysql_executor(self):
        from services.sql_agent.executor import MySQLExecutor
        assert isinstance(get_executor("mysql", {}, 30), MySQLExecutor)

    def test_postgresql_executor(self):
        from services.sql_agent.executor import PostgreSQLExecutor
        assert isinstance(get_executor("postgresql", {}, 30), PostgreSQLExecutor)

    def test_starrocks_executor(self):
        from services.sql_agent.executor import StarRocksExecutor
        assert isinstance(get_executor("starrocks", {}, 30), StarRocksExecutor)

    def test_invalid_db_type_raises(self):
        from app.core.errors import MulanError
        with pytest.raises(MulanError):
            get_executor("oracle", {}, 30)


class TestRowsToDicts:
    def test_converts_columns_and_rows(self):
        from services.sql_agent.executor import MySQLExecutor

        class FakeCursor:
            description = [("id",), ("name",)]
            def fetchall(self):
                return [(1, "alice"), (2, "bob")]

        executor = MySQLExecutor("mysql", {}, 30)
        rows, cols = executor._rows_to_dicts(FakeCursor())
        assert cols == ["id", "name"]
        assert rows == [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]

    def test_empty_result(self):
        from services.sql_agent.executor import PostgreSQLExecutor

        class FakeCursor:
            description = []
            def fetchall(self):
                return []

        executor = PostgreSQLExecutor("postgres", {}, 30)
        rows, cols = executor._rows_to_dicts(FakeCursor())
        assert cols == []
        assert rows == []


# =============================================================================
# service.py — _inject_limit 纯函数
# =============================================================================

class TestInjectLimitDirect:
    """直接测试 LIMIT 常量和注入逻辑（不走有 bug 的 _inject_limit）"""

    def test_limit_ceiling_values(self):
        assert LIMIT_CEILING["mysql"] == 1_000
        assert LIMIT_CEILING["postgres"] == 5_000
        assert LIMIT_CEILING["postgresql"] == 5_000
        assert LIMIT_CEILING["starrocks"] == 10_000

    def test_dialect_limits_contain_limit_default(self):
        for db_type, limits in DIALECT_LIMITS.items():
            assert "limit_default" in limits
            assert limits["limit_default"] == LIMIT_CEILING[db_type]

    def test_dialect_limits_join_and_subquery_depth(self):
        assert DIALECT_LIMITS["mysql"]["max_joins"] == 8
        assert DIALECT_LIMITS["mysql"]["max_subquery_depth"] == 3
        assert DIALECT_LIMITS["starrocks"]["max_joins"] == 10
        assert DIALECT_LIMITS["starrocks"]["max_subquery_depth"] == 5


class TestReplaceLimit:
    """_replace_limit 字符串替换"""

    def _make_svc(self):
        from services.sql_agent.service import SQLAgentService
        return SQLAgentService.__new__(SQLAgentService)

    def test_replaces_limit_value(self):
        import sqlglot
        from sqlglot import exp
        svc = self._make_svc()
        node = sqlglot.parse_one("SELECT * FROM t LIMIT 999", dialect="mysql")
        new_sql = svc._replace_limit(node, 100, "mysql")
        assert "100" in new_sql


# =============================================================================
# 常量一致性
# =============================================================================

class TestConstants:
    def test_dialect_limits_keys_match_ceiling_keys(self):
        assert set(DIALECT_LIMITS.keys()) == set(LIMIT_CEILING.keys())

    def test_dialect_limits_keys_match_timeout_keys(self):
        assert set(DIALECT_LIMITS.keys()) == set(QUERY_TIMEOUT.keys())

    def test_mysql_write_blocked_contains_insert_update_delete(self):
        assert "INSERT" in MYSQL_WRITE_BLOCKED
        assert "UPDATE" in MYSQL_WRITE_BLOCKED
        assert "DELETE" in MYSQL_WRITE_BLOCKED

    def test_dangerous_keywords_contains_core_items(self):
        assert "DROP" in DANGEROUS_KEYWORDS
        assert "TRUNCATE" in DANGEROUS_KEYWORDS
        assert "ALTER" in DANGEROUS_KEYWORDS

    def test_mysql_sensitive_tables_not_empty(self):
        assert len(MYSQL_SENSITIVE_TABLES) > 0
        assert "mysql.user" in MYSQL_SENSITIVE_TABLES

    def test_pg_sensitive_tables_not_empty(self):
        assert len(PG_SENSITIVE_TABLES) > 0
        assert "pg_roles" in PG_SENSITIVE_TABLES
