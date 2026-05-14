"""Safe target-database connector for Data Explorer POC."""

from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy import table
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import column

logger = logging.getLogger(__name__)

SUPPORTED_DB_TYPES = {"postgresql", "mysql", "starrocks"}
UNSUPPORTED_REASONS = {
    "sqlserver": "当前 POC 暂不支持 sqlserver/SQL Server 浏览。",
    "hive": "当前 POC 暂不支持 hive/Hive 浏览。",
    "doris": "当前 POC 暂不支持 doris/Doris 浏览。",
}
SYSTEM_SCHEMAS = {
    "information_schema",
    "pg_catalog",
    "mysql",
    "performance_schema",
    "sys",
    "__internal_schema",
}
MAX_PREVIEW_LIMIT = 100
DEFAULT_TIMEOUT_SECONDS = 5.0


class DataExplorerConnectorError(Exception):
    """Base error for service/API mapping."""

    code = "DEX_008"


class UnsupportedDatabaseError(DataExplorerConnectorError):
    """Raised when the db_type is intentionally unsupported."""

    code = "DEX_004"

    def __init__(self, db_type: str, reason: str | None = None) -> None:
        self.db_type = db_type
        self.reason = reason or f"当前数据库类型暂不支持 Data Explorer 浏览: {db_type}"
        super().__init__(self.reason)


class ConnectorInitializationError(DataExplorerConnectorError):
    """Raised when connector configuration cannot create a dialect engine."""

    code = "DEX_008"


class TargetDatabaseConnectionError(DataExplorerConnectorError):
    """Raised when the target database cannot be reached."""

    code = "DEX_010"


class MetadataTimeoutError(DataExplorerConnectorError):
    """Raised when metadata inspection exceeds the connector timeout."""

    code = "DEX_006"


class PreviewTimeoutError(DataExplorerConnectorError):
    """Raised when preview execution exceeds the connector timeout."""

    code = "DEX_007"


class InvalidPreviewRequestError(DataExplorerConnectorError):
    """Raised for invalid preview arguments."""

    code = "DEX_001"


class PreviewObjectNotAllowedError(DataExplorerConnectorError):
    """Raised when preview targets a system or non-existent object."""

    code = "DEX_009"


@dataclass(frozen=True)
class ColumnMetadata:
    """Column metadata returned by the target database."""

    name: str
    data_type: str
    nullable: bool | None = None
    default: Any = None
    comment: str | None = None


@dataclass(frozen=True)
class TableMetadata:
    """Table or view metadata returned by the target database."""

    schema: str | None
    name: str
    object_type: str


@dataclass(frozen=True)
class PreviewResult:
    """Bounded preview result."""

    columns: list[ColumnMetadata]
    rows: list[list[Any]]
    limit: int
    truncated: bool
    execution_time_ms: int


@dataclass(frozen=True)
class TableOverviewMetadata:
    """Table overview metadata from target database catalogs."""

    schema: str | None
    name: str
    type: str
    comment: str | None = None
    primary_key: list[str] | None = None
    column_count: int | None = None
    indexes_count: int | None = None
    foreign_keys_count: int | None = None
    row_count_estimate: int | None = None
    data_size_bytes: int | None = None
    index_size_bytes: int | None = None
    total_size_bytes: int | None = None
    created_at: Any = None
    table_updated_at: Any = None
    preview_available: bool = True


def unsupported_reason(db_type: str) -> str | None:
    """Return the user-facing unsupported reason for a db_type."""

    normalized = (db_type or "").lower()
    if normalized in SUPPORTED_DB_TYPES:
        return None
    return UNSUPPORTED_REASONS.get(normalized, f"当前数据库类型暂不支持 Data Explorer 浏览: {db_type}")


class DataExplorerConnector:
    """Read-only metadata and preview connector for supported target databases."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        engine: Engine | None = None,
        inspector: Any | None = None,
    ) -> None:
        self.config = config
        self.db_type = str(config.get("db_type") or "").lower()
        self.timeout_seconds = min(float(timeout_seconds), DEFAULT_TIMEOUT_SECONDS)
        self._external_engine = engine is not None
        self.engine = engine
        self._inspector = inspector

        reason = unsupported_reason(self.db_type)
        if reason:
            raise UnsupportedDatabaseError(self.db_type, reason)

        if self.engine is None:
            self.engine = self._create_engine()

    def close(self) -> None:
        """Dispose the owned SQLAlchemy engine."""

        if self.engine is not None and not self._external_engine:
            self.engine.dispose()
        self.engine = None
        self._inspector = None

    def __enter__(self) -> "DataExplorerConnector":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def ping(self) -> None:
        """Open and release a target DB connection."""

        self._run_with_timeout(self._ping, timeout_error=TargetDatabaseConnectionError)

    def list_schemas(self) -> list[str | None]:
        """List schemas visible to the configured user."""

        return self._metadata_call(lambda: self._filter_schemas(self._inspector_for_metadata().get_schema_names()))

    def list_tables(self, schema: str | None = None, *, include_views: bool = True) -> list[TableMetadata]:
        """List tables and optionally views for a schema."""

        def _load() -> list[TableMetadata]:
            inspector = self._inspector_for_metadata()
            table_names = inspector.get_table_names(schema=schema)
            items = [TableMetadata(schema=schema, name=name, object_type="table") for name in table_names]
            if include_views:
                view_names = inspector.get_view_names(schema=schema)
                items.extend(TableMetadata(schema=schema, name=name, object_type="view") for name in view_names)
            return items

        return self._metadata_call(_load)

    def list_columns(self, schema: str | None, table_name: str) -> list[ColumnMetadata]:
        """List columns after validating that the table or view exists."""

        def _load() -> list[ColumnMetadata]:
            self._assert_preview_object_allowed(schema, table_name)
            return self._load_columns(schema, table_name)

        return self._metadata_call(_load)

    def get_table_overview(self, schema: str | None, table_name: str) -> TableOverviewMetadata:
        """Return catalog-only table metadata without scanning table rows."""

        def _load() -> TableOverviewMetadata:
            self._assert_preview_object_allowed(schema, table_name)
            columns = self._load_columns(schema, table_name)
            primary_key = self._load_primary_key(schema, table_name)
            catalog = self._load_table_catalog_stats(schema, table_name)
            return TableOverviewMetadata(
                schema=schema,
                name=table_name,
                type=catalog.get("type") or self._object_type(schema, table_name),
                comment=catalog.get("comment"),
                primary_key=primary_key,
                column_count=len(columns),
                indexes_count=catalog.get("indexes_count"),
                foreign_keys_count=catalog.get("foreign_keys_count"),
                row_count_estimate=catalog.get("row_count_estimate"),
                data_size_bytes=catalog.get("data_size_bytes"),
                index_size_bytes=catalog.get("index_size_bytes"),
                total_size_bytes=catalog.get("total_size_bytes"),
                created_at=catalog.get("created_at"),
                table_updated_at=catalog.get("table_updated_at"),
                preview_available=True,
            )

        return self._metadata_call(_load)

    def preview_table(self, schema: str | None, table_name: str, *, limit: int = MAX_PREVIEW_LIMIT) -> PreviewResult:
        """Run a generated read-only preview query with bounded rows and timeout."""

        if limit < 1 or limit > MAX_PREVIEW_LIMIT:
            raise InvalidPreviewRequestError(f"preview limit must be between 1 and {MAX_PREVIEW_LIMIT}")

        return self._run_with_timeout(
            lambda: self._preview_table(schema, table_name, limit),
            timeout_error=PreviewTimeoutError,
        )

    def _create_engine(self) -> Engine:
        try:
            return create_engine(
                self._build_url(),
                echo=False,
                pool_pre_ping=True,
                connect_args={"connect_timeout": int(self.timeout_seconds)},
            )
        except Exception as exc:
            raise ConnectorInitializationError("Data Explorer connector 初始化失败") from exc

    def _build_url(self) -> URL:
        host = self.config.get("host") or "localhost"
        port = self.config.get("port")
        database = self.config.get("database") or self.config.get("database_name") or ""
        username = self.config.get("user") or self.config.get("username") or ""
        password = self.config.get("password") or ""

        if self.db_type == "postgresql":
            drivername = "postgresql"
            default_port = 5432
        elif self.db_type in {"mysql", "starrocks"}:
            drivername = "mysql+pymysql"
            default_port = 3306 if self.db_type == "mysql" else 9030
        else:
            raise UnsupportedDatabaseError(self.db_type)

        return URL.create(
            drivername,
            username=username,
            password=password,
            host=host,
            port=int(port or default_port),
            database=database,
        )

    def _ping(self) -> None:
        try:
            assert self.engine is not None
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise TargetDatabaseConnectionError("目标数据库连接失败") from exc

    def _inspector_for_metadata(self) -> Any:
        if self._inspector is None:
            assert self.engine is not None
            try:
                self._inspector = inspect(self.engine)
            except SQLAlchemyError as exc:
                raise TargetDatabaseConnectionError("目标数据库连接失败") from exc
        return self._inspector

    def _metadata_call(self, fn: Any) -> Any:
        try:
            return self._run_with_timeout(fn, timeout_error=MetadataTimeoutError)
        except SQLAlchemyError as exc:
            raise TargetDatabaseConnectionError("目标数据库连接失败") from exc

    def _run_with_timeout(self, fn: Any, *, timeout_error: type[DataExplorerConnectorError]) -> Any:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fn)
        try:
            return future.result(timeout=self.timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise timeout_error(f"operation exceeded {self.timeout_seconds:.1f}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _filter_schemas(self, schemas: list[str]) -> list[str]:
        return [schema for schema in schemas if schema.lower() not in SYSTEM_SCHEMAS]

    def _assert_preview_object_allowed(self, schema: str | None, table_name: str) -> None:
        if schema and schema.lower() in SYSTEM_SCHEMAS:
            raise PreviewObjectNotAllowedError("禁止 preview 系统 schema")

        inspector = self._inspector_for_metadata()
        table_names = set(inspector.get_table_names(schema=schema))
        view_names = set(inspector.get_view_names(schema=schema))
        if table_name not in table_names and table_name not in view_names:
            raise PreviewObjectNotAllowedError("preview 对象不存在或不允许访问")

    def _load_columns(self, schema: str | None, table_name: str) -> list[ColumnMetadata]:
        inspector = self._inspector_for_metadata()
        columns = inspector.get_columns(table_name, schema=schema)
        return [
            ColumnMetadata(
                name=str(col["name"]),
                data_type=str(col.get("type", "")),
                nullable=col.get("nullable"),
                default=col.get("default"),
                comment=col.get("comment"),
            )
            for col in columns
        ]

    def _load_primary_key(self, schema: str | None, table_name: str) -> list[str]:
        inspector = self._inspector_for_metadata()
        try:
            pk = inspector.get_pk_constraint(table_name, schema=schema) or {}
        except SQLAlchemyError:
            return []
        return [str(column_name) for column_name in pk.get("constrained_columns") or []]

    def _object_type(self, schema: str | None, table_name: str) -> str:
        inspector = self._inspector_for_metadata()
        if table_name in set(inspector.get_view_names(schema=schema)):
            return "view"
        return "table"

    def _load_table_catalog_stats(self, schema: str | None, table_name: str) -> dict[str, Any]:
        if self.db_type in {"mysql", "starrocks"}:
            return self._load_mysql_table_catalog_stats(schema, table_name)
        if self.db_type == "postgresql":
            return self._load_postgresql_table_catalog_stats(schema, table_name)
        return {}

    def _load_mysql_table_catalog_stats(self, schema: str | None, table_name: str) -> dict[str, Any]:
        assert self.engine is not None
        table_schema = schema or self.config.get("database") or self.config.get("database_name")
        stats: dict[str, Any] = {}
        try:
            with self.engine.connect() as conn:
                table_row = conn.execute(
                    text(
                        """
                        SELECT TABLE_TYPE, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH, CREATE_TIME, UPDATE_TIME, TABLE_COMMENT
                        FROM information_schema.TABLES
                        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name
                        """
                    ),
                    {"schema": table_schema, "table_name": table_name},
                ).mappings().first()
                if table_row:
                    table_type = str(table_row.get("TABLE_TYPE") or "").upper()
                    data_size = _coerce_int(table_row.get("DATA_LENGTH"))
                    index_size = _coerce_int(table_row.get("INDEX_LENGTH"))
                    stats.update(
                        {
                            "type": "view" if "VIEW" in table_type else "table",
                            "comment": table_row.get("TABLE_COMMENT") or None,
                            "row_count_estimate": _coerce_int(table_row.get("TABLE_ROWS")),
                            "data_size_bytes": data_size,
                            "index_size_bytes": index_size,
                            "total_size_bytes": (data_size or 0) + (index_size or 0) if data_size is not None or index_size is not None else None,
                            "created_at": table_row.get("CREATE_TIME"),
                            "table_updated_at": table_row.get("UPDATE_TIME"),
                        }
                    )

                indexes_count = conn.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT INDEX_NAME)
                        FROM information_schema.STATISTICS
                        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name
                        """
                    ),
                    {"schema": table_schema, "table_name": table_name},
                ).scalar()
                foreign_keys_count = conn.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT CONSTRAINT_NAME)
                        FROM information_schema.KEY_COLUMN_USAGE
                        WHERE TABLE_SCHEMA = :schema
                          AND TABLE_NAME = :table_name
                          AND REFERENCED_TABLE_NAME IS NOT NULL
                        """
                    ),
                    {"schema": table_schema, "table_name": table_name},
                ).scalar()
                stats["indexes_count"] = _coerce_int(indexes_count) or 0
                stats["foreign_keys_count"] = _coerce_int(foreign_keys_count) or 0
        except SQLAlchemyError as exc:
            raise TargetDatabaseConnectionError("目标数据库元数据读取失败") from exc
        return stats

    def _load_postgresql_table_catalog_stats(self, schema: str | None, table_name: str) -> dict[str, Any]:
        assert self.engine is not None
        stats: dict[str, Any] = {}
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT c.reltuples::bigint AS row_count_estimate,
                               pg_total_relation_size(c.oid) AS total_size_bytes,
                               pg_relation_size(c.oid) AS data_size_bytes,
                               pg_indexes_size(c.oid) AS index_size_bytes,
                               obj_description(c.oid) AS comment,
                               c.relkind
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = :schema AND c.relname = :table_name
                        """
                    ),
                    {"schema": schema or "public", "table_name": table_name},
                ).mappings().first()
                if row:
                    stats.update(
                        {
                            "type": "view" if row.get("relkind") in {"v", "m"} else "table",
                            "comment": row.get("comment"),
                            "row_count_estimate": _coerce_int(row.get("row_count_estimate")),
                            "data_size_bytes": _coerce_int(row.get("data_size_bytes")),
                            "index_size_bytes": _coerce_int(row.get("index_size_bytes")),
                            "total_size_bytes": _coerce_int(row.get("total_size_bytes")),
                        }
                    )
                stats["indexes_count"] = _coerce_int(
                    conn.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM pg_indexes
                            WHERE schemaname = :schema AND tablename = :table_name
                            """
                        ),
                        {"schema": schema or "public", "table_name": table_name},
                    ).scalar()
                ) or 0
                stats["foreign_keys_count"] = _coerce_int(
                    conn.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.table_constraints
                            WHERE table_schema = :schema
                              AND table_name = :table_name
                              AND constraint_type = 'FOREIGN KEY'
                            """
                        ),
                        {"schema": schema or "public", "table_name": table_name},
                    ).scalar()
                ) or 0
        except SQLAlchemyError as exc:
            raise TargetDatabaseConnectionError("目标数据库元数据读取失败") from exc
        return stats

    def _preview_table(self, schema: str | None, table_name: str, limit: int) -> PreviewResult:
        self._assert_preview_object_allowed(schema, table_name)
        columns = self._load_columns(schema, table_name)
        if not columns:
            raise PreviewObjectNotAllowedError("preview 对象没有可读取字段")

        safe_table = table(table_name, *(column(col.name) for col in columns), schema=schema)
        safe_columns = [safe_table.c[col.name] for col in columns]
        stmt = select(*safe_columns).select_from(safe_table).limit(limit)

        started = time.monotonic()
        assert self.engine is not None
        try:
            with self.engine.connect() as conn:
                if self.db_type == "postgresql":
                    with conn.begin():
                        self._apply_session_timeout(conn)
                        result = conn.execute(stmt)
                        raw_rows = result.fetchmany(limit)
                else:
                    self._apply_session_timeout(conn)
                    result = conn.execute(stmt)
                    raw_rows = result.fetchmany(limit)
        except SQLAlchemyError as exc:
            raise TargetDatabaseConnectionError("目标数据库 preview 执行失败") from exc

        rows = [list(row) for row in raw_rows]
        return PreviewResult(
            columns=columns,
            rows=rows,
            limit=limit,
            truncated=len(rows) == limit,
            execution_time_ms=int((time.monotonic() - started) * 1000),
        )

    def _apply_session_timeout(self, conn: Any) -> None:
        timeout_ms = int(self.timeout_seconds * 1000)
        try:
            if self.db_type == "postgresql":
                conn.execute(text("SET LOCAL statement_timeout = :timeout_ms"), {"timeout_ms": timeout_ms})
            elif self.db_type == "mysql":
                conn.execute(text("SET SESSION MAX_EXECUTION_TIME=:timeout_ms"), {"timeout_ms": timeout_ms})
            elif self.db_type == "starrocks":
                conn.execute(text("SET query_timeout = :timeout_seconds"), {"timeout_seconds": int(self.timeout_seconds)})
        except SQLAlchemyError as exc:
            logger.warning(
                "Data Explorer session timeout setup failed for db_type=%s: %s",
                self.db_type,
                exc.__class__.__name__,
            )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
