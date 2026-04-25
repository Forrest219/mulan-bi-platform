"""
SchemaTool 单元测试 — 使用 mock db session，不依赖真实数据库
"""

import pytest
import uuid
from unittest.mock import MagicMock, patch

from services.data_agent.tools.schema_tool import SchemaTool
from services.data_agent.tool_base import ToolContext, ToolResult


class TestSchemaTool:
    """SchemaTool 测试用例"""

    @pytest.fixture
    def tool(self):
        return SchemaTool()

    # =============================================================================
    # TC-SCHEMA-001: connection_id 缺失
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_schema_001_missing_connection_id(self, tool):
        """TC-SCHEMA-001: connection_id 缺失时返回错误"""
        context = ToolContext(
            session_id="s1", user_id=1, connection_id=None, trace_id="t1"
        )

        result = await tool.execute({}, context)

        assert result.success is False
        assert "connection_id is required" in result.error

    # =============================================================================
    # TC-SCHEMA-002: DataSource 不存在
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_schema_002_datasource_not_found(self, tool):
        """TC-SCHEMA-002: connection_id 对应的 DataSource 不存在时返回错误"""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db = MagicMock()
        mock_db.query = mock_query

        context = ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=9999,
            trace_id="t1",
        )

        with patch("app.core.database.SessionLocal", return_value=mock_db):
            result = await tool.execute({}, context)

        assert result.success is False
        assert "not found" in result.error

    # =============================================================================
    # TC-SCHEMA-003: 成功查询（PostgreSQL，无 table_name）
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_schema_003_success_no_table_name(self, tool):
        """TC-SCHEMA-003: 不指定 table_name 时返回表列表"""
        # Mock DataSource
        mock_ds = MagicMock()
        mock_ds.id = 1
        mock_ds.name = "test_datasource"
        mock_ds.db_type = "postgresql"
        mock_ds.host = "localhost"
        mock_ds.port = 5432
        mock_ds.database_name = "test_db"
        mock_ds.username = "user"
        mock_ds.password_encrypted = "pass"

        # Mock DataSource
        mock_ds = MagicMock()
        mock_ds.id = 1
        mock_ds.name = "test_datasource"
        mock_ds.db_type = "postgresql"
        mock_ds.host = "localhost"
        mock_ds.port = 5432
        mock_ds.database_name = "test_db"
        mock_ds.username = "user"
        mock_ds.password_encrypted = "pass"

        # SQLAlchemy session.query is a bound method — replace it entirely with MagicMock
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_ds
        mock_query.return_value = mock_query  # query(Model) returns same mock_query for chaining
        mock_db = MagicMock()
        mock_db.query = mock_query

        context = ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=1,
            trace_id="t1",
        )

        # Mock remote DB query — use real list, wrapped in mock that returns it
        mock_tables = [("sales", "BASE TABLE", "YES"), ("orders", "BASE TABLE", "YES")]
        
        # Use a real list wrapper that mimics cursor result
        class MockResult:
            def __init__(self, rows):
                self._rows = rows
            def __iter__(self):
                return iter(self._rows)
        
        mock_conn = MagicMock()
        mock_conn.execute.return_value = MockResult(mock_tables)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_engine.dispose = MagicMock()

        with patch("app.core.database.SessionLocal", return_value=mock_db):
            with patch("services.data_agent.tools.schema_tool.create_engine", return_value=mock_engine):
                with patch("services.data_agent.tools.schema_tool.get_datasource_crypto") as mock_crypto:
                    mock_crypto.return_value.decrypt.return_value = "test_password"
                    with patch("services.data_agent.tools.schema_tool.asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                        result = await tool.execute({"limit": 100}, context)

        assert result.success is True
        assert "tables" in result.data
        assert len(result.data["tables"]) == 2
        assert result.data["connection_id"] == 1
        assert result.data["db_type"] == "postgresql"

    # =============================================================================
    # TC-SCHEMA-004: 成功查询指定表字段
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_schema_004_success_with_table_name(self, tool):
        """TC-SCHEMA-004: 指定 table_name 时返回表结构（字段信息）"""
        # Mock DataSource
        mock_ds = MagicMock()
        mock_ds.id = 1
        mock_ds.name = "test_datasource"
        mock_ds.db_type = "postgresql"
        mock_ds.host = "localhost"
        mock_ds.port = 5432
        mock_ds.database_name = "test_db"
        mock_ds.username = "user"
        mock_ds.password_encrypted = "pass"

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_ds
        mock_query.return_value = mock_query  # query(Model) returns same mock_query for chaining
        mock_db = MagicMock()
        mock_db.query = mock_query

        context = ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=1,
            trace_id="t1",
        )

        # Mock remote DB query — use real list wrappers
        class MockResult:
            def __init__(self, rows):
                self._rows = rows
            def __iter__(self):
                return iter(self._rows)

        # Three execute calls: tables query, columns query, PK query
        mock_tables_result = MockResult([("sales", "BASE TABLE", "YES")])
        mock_columns_result = MockResult([
            ("id", "integer", None, "NO", None, "YES"),
            ("amount", "numeric", None, "YES", None, None),
        ])
        mock_pk_result = MockResult([("id",)])

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [
            mock_tables_result,
            mock_columns_result,
            mock_pk_result,
        ]

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_engine.dispose = MagicMock()

        with patch("app.core.database.SessionLocal", return_value=mock_db):
            with patch("services.data_agent.tools.schema_tool.create_engine", return_value=mock_engine):
                with patch("services.data_agent.tools.schema_tool.get_datasource_crypto") as mock_crypto:
                    mock_crypto.return_value.decrypt.return_value = "test_password"
                    with patch("services.data_agent.tools.schema_tool.asyncio.to_thread",
                               side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                        result = await tool.execute({"table_name": "sales"}, context)

        assert result.success is True
        assert "tables" in result.data
        assert "fields" in result.data
        assert "sales" in result.data["fields"]
        assert len(result.data["fields"]["sales"]) == 2
        assert result.data["fields"]["sales"][0]["name"] == "id"
        assert result.data["fields"]["sales"][0]["is_primary_key"] is True
        assert result.data["fields"]["sales"][1]["name"] == "amount"

    # =============================================================================
    # TC-SCHEMA-005: 异常处理（数据库连接失败）
    # =============================================================================
    @pytest.mark.asyncio
    async def test_tc_schema_005_db_exception(self, tool):
        """TC-SCHEMA-005: 数据库异常时返回错误"""
        # Mock DataSource
        mock_ds = MagicMock()
        mock_ds.id = 1
        mock_ds.name = "test_datasource"
        mock_ds.db_type = "postgresql"
        mock_ds.host = "localhost"
        mock_ds.port = 5432
        mock_ds.database_name = "test_db"
        mock_ds.username = "user"
        mock_ds.password_encrypted = "pass"

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_ds
        mock_query.return_value = mock_query  # query(Model) returns same mock_query for chaining
        mock_db = MagicMock()
        mock_db.query = mock_query

        context = ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=1,
            trace_id="t1",
        )

        # Use a real exception-raising wrapper instead of MagicMock side_effect
        class RaisingMockConn:
            def execute(self, *args, **kwargs):
                raise Exception("Connection refused")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        mock_engine = MagicMock()
        mock_engine.connect.return_value = RaisingMockConn()
        mock_engine.dispose = MagicMock()

        with patch("app.core.database.SessionLocal", return_value=mock_db):
            with patch("services.data_agent.tools.schema_tool.create_engine", return_value=mock_engine):
                with patch("services.data_agent.tools.schema_tool.get_datasource_crypto") as mock_crypto:
                    mock_crypto.return_value.decrypt.return_value = "test_password"
                    result = await tool.execute({}, context)

        assert result.success is False
        assert "查询表结构失败" in result.error


class TestSchemaToolMySQL:
    """SchemaTool MySQL 场景测试"""

    @pytest.fixture
    def tool(self):
        return SchemaTool()

    @pytest.mark.asyncio
    async def test_mysql_schema_success(self, tool):
        """MySQL 数据源成功查询表结构"""
        # Mock DataSource
        mock_ds = MagicMock()
        mock_ds.id = 2
        mock_ds.name = "mysql_datasource"
        mock_ds.db_type = "mysql"
        mock_ds.host = "localhost"
        mock_ds.port = 3306
        mock_ds.database_name = "test_db"
        mock_ds.username = "root"
        mock_ds.password_encrypted = "pass"

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_ds
        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        context = ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=2,
            trace_id="t1",
        )

        # MockResult for MySQL (2-column tuple)
        class MockResult:
            def __init__(self, rows):
                self._rows = rows
            def __iter__(self):
                return iter(self._rows)

        mock_conn = MagicMock()
        mock_conn.execute.return_value = MockResult([("users", "BASE TABLE", "YES")])

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_engine.dispose = MagicMock()

        with patch("services.data_agent.tools.schema_tool.SessionLocal", return_value=mock_db):
            with patch("services.data_agent.tools.schema_tool.create_engine", return_value=mock_engine):
                with patch("services.data_agent.tools.schema_tool.get_datasource_crypto") as mock_crypto:
                    mock_crypto.return_value.decrypt.return_value = "test_password"
                    with patch("services.data_agent.tools.schema_tool.asyncio.to_thread",
                               side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                        result = await tool.execute({}, context)

        assert result.success is True
        assert result.data["db_type"] == "mysql"
        assert result.data["datasource_name"] == "mysql_datasource"


class TestSchemaToolSqlServer:
    """SchemaTool SQL Server 场景测试"""

    @pytest.fixture
    def tool(self):
        return SchemaTool()

    @pytest.mark.asyncio
    async def test_sqlserver_schema_success(self, tool):
        """SQL Server 数据源成功查询表结构"""
        # Mock DataSource
        mock_ds = MagicMock()
        mock_ds.id = 3
        mock_ds.name = "sqlserver_datasource"
        mock_ds.db_type = "sqlserver"
        mock_ds.host = "localhost"
        mock_ds.port = 1433
        mock_ds.database_name = "test_db"
        mock_ds.username = "sa"
        mock_ds.password_encrypted = "pass"

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_ds
        mock_query.return_value = mock_query
        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        context = ToolContext(
            session_id="s1",
            user_id=1,
            connection_id=3,
            trace_id="t1",
        )

        class MockResult:
            def __init__(self, rows):
                self._rows = rows
            def __iter__(self):
                return iter(self._rows)

        mock_conn = MagicMock()
        mock_result = MagicMock(fetchall=MagicMock(return_value=[("Sales", "BASE TABLE")]))
        mock_conn.execute.return_value = mock_result

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_engine.dispose = MagicMock()

        with patch("services.data_agent.tools.schema_tool.SessionLocal", return_value=mock_db):
            with patch("services.data_agent.tools.schema_tool.create_engine", return_value=mock_engine):
                with patch("services.data_agent.tools.schema_tool.get_datasource_crypto") as mock_crypto:
                    mock_crypto.return_value.decrypt.return_value = "test_password"
                    with patch("services.data_agent.tools.schema_tool.asyncio.to_thread",
                               side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                        result = await tool.execute({"table_name": "Sales"}, context)

        assert result.success is True
        assert result.data["db_type"] == "sqlserver"
        assert result.data["datasource_name"] == "sqlserver_datasource"