import time

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects import postgresql

from services.data_explorer.connector import DataExplorerConnector
from services.data_explorer.connector import InvalidPreviewRequestError
from services.data_explorer.connector import MetadataTimeoutError
from services.data_explorer.connector import PreviewObjectNotAllowedError
from services.data_explorer.connector import PreviewTimeoutError
from services.data_explorer.connector import UnsupportedDatabaseError
from services.data_explorer.connector import unsupported_reason

pytestmark = pytest.mark.skip_db


class FakeInspector:
    def __init__(self, *, schemas=None, tables=None, views=None, columns=None, sleep_seconds=0):
        self.schemas = schemas or ["public"]
        self.tables = tables or {}
        self.views = views or {}
        self.columns = columns or {}
        self.sleep_seconds = sleep_seconds

    def _sleep(self):
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)

    def get_schema_names(self):
        self._sleep()
        return self.schemas

    def get_table_names(self, schema=None):
        self._sleep()
        return self.tables.get(schema, [])

    def get_view_names(self, schema=None):
        self._sleep()
        return self.views.get(schema, [])

    def get_columns(self, table_name, schema=None):
        self._sleep()
        return self.columns.get((schema, table_name), [])


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchmany(self, limit):
        return self.rows[:limit]


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, rows=None, sleep_seconds=0, fail_timeout_setup=False):
        self.rows = rows or []
        self.sleep_seconds = sleep_seconds
        self.fail_timeout_setup = fail_timeout_setup
        self.executed = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False

    def begin(self):
        return FakeTransaction()

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        sql_text = str(statement)
        if self.fail_timeout_setup and "MAX_EXECUTION_TIME" in sql_text:
            from sqlalchemy.exc import SQLAlchemyError

            raise SQLAlchemyError("unsupported timeout")
        if self.sleep_seconds and "SELECT" in sql_text.upper():
            time.sleep(self.sleep_seconds)
        if sql_text.startswith("SET"):
            return FakeResult([])
        return FakeResult(self.rows)


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


def _connector(db_type="mysql", *, inspector=None, connection=None, timeout_seconds=1):
    inspector = inspector or FakeInspector(
        tables={"analytics": ["orders.table"]},
        columns={
            ("analytics", "orders.table"): [
                {"name": "Order ID", "type": "BIGINT", "nullable": False},
                {"name": "amount.total", "type": "DECIMAL", "nullable": True},
            ]
        },
    )
    engine = FakeEngine(connection or FakeConnection(rows=[(1, "99.00")]))
    return DataExplorerConnector(
        {"db_type": db_type, "host": "localhost", "database": "db", "username": "u", "password": "p"},
        timeout_seconds=timeout_seconds,
        engine=engine,
        inspector=inspector,
    )


@pytest.mark.parametrize("db_type", ["sqlserver", "hive", "doris"])
def test_unsupported_db_types_have_clear_reason(db_type):
    assert unsupported_reason(db_type)
    with pytest.raises(UnsupportedDatabaseError) as exc:
        _connector(db_type=db_type)
    assert db_type in exc.value.reason.lower()


def test_metadata_filters_system_schemas():
    connector = _connector(
        inspector=FakeInspector(schemas=["public", "information_schema", "pg_catalog", "biz"])
    )

    assert connector.list_schemas() == ["public", "biz"]


def test_metadata_timeout_raises_mappable_error():
    connector = _connector(inspector=FakeInspector(sleep_seconds=0.05), timeout_seconds=0.01)

    with pytest.raises(MetadataTimeoutError):
        connector.list_schemas()


def test_preview_rejects_limit_above_100():
    connector = _connector()

    with pytest.raises(InvalidPreviewRequestError):
        connector.preview_table("analytics", "orders.table", limit=101)


def test_preview_rejects_system_schema():
    connector = _connector(inspector=FakeInspector(tables={"information_schema": ["tables"]}))

    with pytest.raises(PreviewObjectNotAllowedError):
        connector.preview_table("information_schema", "tables", limit=10)


@pytest.mark.parametrize("db_type", ["mysql", "starrocks"])
def test_mysql_protocol_preview_uses_core_quoted_identifiers_and_closes_connection(db_type):
    connection = FakeConnection(rows=[(1, "99.00")])
    connector = _connector(db_type=db_type, connection=connection)

    result = connector.preview_table("analytics", "orders.table", limit=10)

    assert result.rows == [[1, "99.00"]]
    assert connection.closed is True
    preview_stmt = connection.executed[-1][0]
    compiled = str(preview_stmt.compile(dialect=mysql.dialect()))
    assert "FROM analytics.`orders.table`" in compiled
    assert "`Order ID`" in compiled
    assert "`amount.total`" in compiled
    assert "LIMIT" in compiled


def test_postgresql_preview_applies_statement_timeout_in_transaction():
    connection = FakeConnection(rows=[(1,)])
    inspector = FakeInspector(
        tables={"Sales Schema": ["Mixed Table"]},
        columns={("Sales Schema", "Mixed Table"): [{"name": "Mixed Column", "type": "TEXT"}]},
    )
    connector = _connector(db_type="postgresql", inspector=inspector, connection=connection)

    connector.preview_table("Sales Schema", "Mixed Table", limit=5)

    timeout_stmt = str(connection.executed[0][0])
    preview_stmt = connection.executed[-1][0]
    compiled = str(preview_stmt.compile(dialect=postgresql.dialect()))
    assert "SET LOCAL statement_timeout" in timeout_stmt
    assert '"Sales Schema"."Mixed Table"' in compiled
    assert '"Mixed Column"' in compiled
    assert connection.closed is True


def test_mysql_timeout_setup_failure_is_best_effort_and_connection_closes(caplog):
    connection = FakeConnection(rows=[(1,)], fail_timeout_setup=True)
    inspector = FakeInspector(
        tables={"analytics": ["orders"]},
        columns={("analytics", "orders"): [{"name": "id", "type": "BIGINT"}]},
    )
    connector = _connector(inspector=inspector, connection=connection)

    result = connector.preview_table("analytics", "orders", limit=1)

    assert result.rows == [[1]]
    assert connection.closed is True
    assert "session timeout setup failed" in caplog.text


def test_preview_timeout_raises_mappable_error_and_closes_connection():
    connection = FakeConnection(rows=[(1,)], sleep_seconds=0.05)
    inspector = FakeInspector(
        tables={"analytics": ["orders"]},
        columns={("analytics", "orders"): [{"name": "id", "type": "BIGINT"}]},
    )
    connector = _connector(inspector=inspector, connection=connection, timeout_seconds=0.01)

    with pytest.raises(PreviewTimeoutError):
        connector.preview_table("analytics", "orders", limit=1)

    time.sleep(0.06)
    assert connection.closed is True
