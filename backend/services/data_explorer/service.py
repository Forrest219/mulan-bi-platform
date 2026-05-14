"""Database Data Explorer POC service orchestration."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.crypto import get_datasource_crypto
from app.core.errors import MulanError
from services.auth.models import User
from services.datasources.models import DataSource
from services.data_explorer.schemas import (
    ExplorerCapabilities,
    ExplorerColumnItem,
    ExplorerColumnListResponse,
    ExplorerConnectionDetail,
    ExplorerConnectionItem,
    ExplorerConnectionListResponse,
    ExplorerConnectionOverviewResponse,
    ExplorerConnectionSummary,
    ExplorerEffectiveActions,
    ExplorerPermissionConnection,
    ExplorerPermissionSummaryResponse,
    ExplorerPermissionUser,
    ExplorerPreviewColumn,
    ExplorerPreviewResponse,
    ExplorerSchemaItem,
    ExplorerSchemaListResponse,
    ExplorerTableItem,
    ExplorerTableListResponse,
    ExplorerTableOverviewResponse,
)

logger = logging.getLogger(__name__)

SUPPORTED_DB_TYPES = {"postgresql", "mysql", "starrocks"}
ADMIN_ROLES = {"admin", "data_admin"}


class DEXError:
    """Factory for standard Data Explorer errors."""

    @staticmethod
    def invalid_request(detail: dict[str, Any] | None = None) -> MulanError:
        return MulanError("DEX_001", "Data Explorer 请求无效。", 400, detail)

    @staticmethod
    def connection_not_found() -> MulanError:
        return MulanError("DEX_002", "连接不存在。", 404)

    @staticmethod
    def connection_inactive() -> MulanError:
        return MulanError("DEX_003", "连接未启用。", 400)

    @staticmethod
    def unsupported_db_type(db_type: str | None = None) -> MulanError:
        detail = {"db_type": db_type} if db_type else None
        return MulanError("DEX_004", "当前数据库类型暂不支持 Data Explorer 浏览。", 422, detail)

    @staticmethod
    def access_denied() -> MulanError:
        return MulanError("DEX_005", "无权限访问连接。", 403)

    @staticmethod
    def metadata_timeout(detail: dict[str, Any] | None = None) -> MulanError:
        return MulanError("DEX_006", "元数据读取超时。", 504, detail)

    @staticmethod
    def preview_timeout(detail: dict[str, Any] | None = None) -> MulanError:
        return MulanError("DEX_007", "Preview 超时。", 504, detail)

    @staticmethod
    def connector_init_failed(detail: dict[str, Any] | None = None) -> MulanError:
        return MulanError("DEX_008", "Explorer connector 初始化失败。", 500, detail)

    @staticmethod
    def preview_not_allowed(detail: dict[str, Any] | None = None) -> MulanError:
        return MulanError("DEX_009", "不允许预览该对象。", 400, detail)

    @staticmethod
    def target_connection_failed(detail: dict[str, Any] | None = None) -> MulanError:
        return MulanError("DEX_010", "目标数据库连接失败。", 502, detail)


def _is_admin_like(user: dict[str, Any]) -> bool:
    return user.get("role") in ADMIN_ROLES


def _is_supported(db_type: str | None) -> bool:
    return (db_type or "").lower() in SUPPORTED_DB_TYPES


def _unsupported_reason(db_type: str | None) -> str | None:
    if _is_supported(db_type):
        return None
    return f"{db_type or 'unknown'} 暂不支持 Data Explorer 浏览"


def _connection_item(connection: DataSource) -> ExplorerConnectionItem:
    db_type = (connection.db_type or "").lower()
    return ExplorerConnectionItem(
        id=connection.id,
        name=connection.name,
        db_type=db_type,
        host=connection.host,
        port=connection.port,
        database_name=connection.database_name,
        owner_id=connection.owner_id,
        is_active=bool(connection.is_active),
        last_tested_at=connection.last_tested_at,
        last_test_success=connection.last_test_success,
        explorer_supported=_is_supported(db_type),
        unsupported_reason=_unsupported_reason(db_type),
    )


def _connection_detail(connection: DataSource) -> ExplorerConnectionDetail:
    return ExplorerConnectionDetail(
        id=connection.id,
        name=connection.name,
        db_type=(connection.db_type or "").lower(),
        host=connection.host,
        port=connection.port,
        database_name=connection.database_name,
        username=connection.username,
        is_active=bool(connection.is_active),
        last_tested_at=connection.last_tested_at,
        last_test_success=connection.last_test_success,
    )


def _coerce_items(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Iterable) and not isinstance(payload, (str, bytes, dict)):
        return list(payload)
    return []


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return {key: val for key, val in vars(value).items() if not key.startswith("_")}
    return dict(value)


def _connection_config(connection: DataSource) -> dict[str, Any]:
    password = ""
    if connection.password_encrypted:
        password = get_datasource_crypto().decrypt(connection.password_encrypted)
    return {
        "db_type": connection.db_type,
        "host": connection.host,
        "port": connection.port,
        "database_name": connection.database_name,
        "username": connection.username,
        "password": password,
        "extra_config": connection.extra_config or {},
    }


def _connector_for(connection: DataSource) -> Any:
    """Create a connector using the interface owned by connector.py."""
    try:
        from services.data_explorer import connector as connector_module
    except ImportError as exc:
        raise DEXError.connector_init_failed({"missing_interface": "connector"}) from exc

    try:
        factory = getattr(connector_module, "create_explorer_connector", None)
        if factory is not None:
            return factory(connection)
        connector_cls = getattr(connector_module, "DataExplorerConnector")
        return connector_cls(_connection_config(connection))
    except MulanError:
        raise
    except Exception as exc:
        logger.exception("DEX connector initialization failed for connection_id=%s", connection.id)
        raise DEXError.connector_init_failed({"connection_id": connection.id}) from exc


def _close_connector(connector: Any) -> None:
    close = getattr(connector, "close", None)
    if callable(close):
        close()


def _encode_table_ref(schema: str, table: str) -> str:
    """Expected interface: encode_table_ref(schema, table)."""
    try:
        from services.data_explorer.table_ref import encode_table_ref
    except ImportError as exc:
        raise DEXError.connector_init_failed({"missing_interface": "encode_table_ref"}) from exc
    return encode_table_ref(schema, table)


def _decode_table_ref(table_ref: str) -> tuple[str, str]:
    """Expected interface: decode_table_ref(table_ref) -> (schema, table)."""
    try:
        from services.data_explorer.table_ref import TableRefError, decode_table_ref
    except ImportError as exc:
        raise DEXError.connector_init_failed({"missing_interface": "decode_table_ref"}) from exc

    try:
        schema, table = decode_table_ref(table_ref)
    except (TableRefError, ValueError) as exc:
        raise DEXError.invalid_request({"table_ref": "invalid"}) from exc

    if not schema or not table:
        raise DEXError.invalid_request({"table_ref": "schema and table are required"})
    return schema, table


def _apply_preview_redaction(columns: list[dict[str, Any]], rows: list[list[Any]]) -> tuple[list[list[Any]], bool]:
    """Apply redaction using the interface owned by redaction.py."""
    try:
        from services.data_explorer import redaction as redaction_module
    except ImportError as exc:
        raise DEXError.connector_init_failed({"missing_interface": "redaction"}) from exc

    apply_preview_redaction = getattr(
        redaction_module,
        "apply_preview_redaction",
        getattr(redaction_module, "redact_preview", None),
    )
    if apply_preview_redaction is None:
        raise DEXError.connector_init_failed({"missing_interface": "redact_preview"})
    result = apply_preview_redaction(columns, rows)
    if isinstance(result, tuple):
        redacted_rows, applied = result
        return redacted_rows, bool(applied)
    if isinstance(result, dict):
        return result.get("rows", rows), bool(result.get("redaction_applied"))
    return rows, False


def map_connector_error(exc: Exception, *, preview: bool = False) -> MulanError:
    code = getattr(exc, "error_code", None) or getattr(exc, "code", None)
    if isinstance(exc, MulanError):
        return exc
    if code in {"DEX_001", "DEX_002", "DEX_003", "DEX_004", "DEX_005", "DEX_006", "DEX_007", "DEX_008", "DEX_009", "DEX_010"}:
        status_by_code = {
            "DEX_001": 400,
            "DEX_002": 404,
            "DEX_003": 400,
            "DEX_004": 422,
            "DEX_005": 403,
            "DEX_006": 504,
            "DEX_007": 504,
            "DEX_008": 500,
            "DEX_009": 400,
            "DEX_010": 502,
        }
        return MulanError(
            code,
            getattr(exc, "message", str(exc)),
            getattr(exc, "status_code", status_by_code[code]),
            getattr(exc, "detail", None),
        )
    name = exc.__class__.__name__.lower()
    if "timeout" in name:
        return DEXError.preview_timeout() if preview else DEXError.metadata_timeout()
    if "unsupported" in name:
        return DEXError.unsupported_db_type()
    if "notfound" in name or "not_found" in name:
        return DEXError.invalid_request({"object": "not_found"})
    if "preview" in name and "not" in name:
        return DEXError.preview_not_allowed()
    if "connection" in name or "connect" in name:
        return DEXError.target_connection_failed()
    return DEXError.connector_init_failed()


def resolve_explorer_connection(connection_id: int, current_user: dict[str, Any], db: Session) -> DataSource:
    connection = db.query(DataSource).filter(DataSource.id == connection_id).first()
    if connection is None:
        raise DEXError.connection_not_found()
    if not connection.is_active:
        raise DEXError.connection_inactive()
    if not _is_supported(connection.db_type):
        raise DEXError.unsupported_db_type(connection.db_type)
    if not _is_admin_like(current_user) and connection.owner_id != current_user.get("id"):
        raise DEXError.access_denied()
    return connection


class DataExplorerService:
    def list_connections(self, current_user: dict[str, Any], db: Session) -> ExplorerConnectionListResponse:
        query = db.query(DataSource).filter(DataSource.is_active == True)  # noqa: E712
        if not _is_admin_like(current_user):
            query = query.filter(DataSource.owner_id == current_user.get("id"))
        connections = query.order_by(DataSource.created_at.desc()).all()
        items = [_connection_item(connection) for connection in connections]
        return ExplorerConnectionListResponse(items=items, total=len(items))

    def get_connection_overview(
        self,
        connection_id: int,
        current_user: dict[str, Any],
        db: Session,
    ) -> ExplorerConnectionOverviewResponse:
        connection = resolve_explorer_connection(connection_id, current_user, db)
        summary = ExplorerConnectionSummary()
        connector = None
        try:
            connector = _connector_for(connection)
            summary_fn = getattr(connector, "get_connection_summary", None)
            if callable(summary_fn):
                raw_summary = summary_fn()
                summary = ExplorerConnectionSummary(**(raw_summary or {}))
        except Exception:
            logger.warning("DEX overview summary failed for connection_id=%s", connection.id, exc_info=True)
        finally:
            _close_connector(connector)
        return ExplorerConnectionOverviewResponse(
            connection=_connection_detail(connection),
            capabilities=ExplorerCapabilities(),
            summary=summary,
        )

    def list_schemas(
        self,
        connection_id: int,
        current_user: dict[str, Any],
        db: Session,
    ) -> ExplorerSchemaListResponse:
        connection = resolve_explorer_connection(connection_id, current_user, db)
        connector = None
        try:
            connector = _connector_for(connection)
            raw_items = _coerce_items(connector.list_schemas())
            items = []
            for raw_item in raw_items:
                item = dict(raw_item) if isinstance(raw_item, dict) else {"name": str(raw_item)}
                if item.get("table_count") is None and item.get("view_count") is None:
                    tables = _coerce_items(connector.list_tables(schema=item["name"], include_views=True))
                    table_count = 0
                    view_count = 0
                    for raw_table in tables:
                        table_item = _to_dict(raw_table)
                        object_type = table_item.get("type") or table_item.get("object_type")
                        if object_type == "view":
                            view_count += 1
                        else:
                            table_count += 1
                    item["table_count"] = table_count
                    item["view_count"] = view_count
                items.append(ExplorerSchemaItem(**item))
            return ExplorerSchemaListResponse(items=items)
        except Exception as exc:
            raise map_connector_error(exc) from exc
        finally:
            _close_connector(connector)

    def list_tables(
        self,
        connection_id: int,
        current_user: dict[str, Any],
        db: Session,
        *,
        schema: str | None,
        q: str | None,
        object_type: str,
        limit: int,
        offset: int,
    ) -> ExplorerTableListResponse:
        if limit < 1 or limit > 500 or offset < 0:
            raise DEXError.invalid_request({"limit": limit, "offset": offset})
        if object_type not in {"table", "view", "all"}:
            raise DEXError.invalid_request({"type": object_type})

        connection = resolve_explorer_connection(connection_id, current_user, db)
        connector = None
        try:
            connector = _connector_for(connection)
            try:
                payload = connector.list_tables(
                    schema=schema,
                    q=q,
                    object_type=object_type,
                    limit=limit,
                    offset=offset,
                )
            except TypeError:
                payload = connector.list_tables(schema=schema, include_views=object_type in {"view", "all"})
            raw_items = _coerce_items(payload)
            filtered_items = []
            for raw_item in raw_items:
                item = _to_dict(raw_item)
                if "object_type" in item and "type" not in item:
                    item["type"] = item.pop("object_type")
                item["schema"] = item.get("schema") or schema or connection.database_name
                if object_type != "all" and item.get("type") != object_type:
                    continue
                if q and q.casefold() not in str(item.get("name", "")).casefold():
                    continue
                filtered_items.append(item)

            total = len(filtered_items)
            page_items = filtered_items[offset : offset + limit]
            items = []
            for item in page_items:
                item.setdefault("table_ref", _encode_table_ref(item["schema"], item["name"]))
                if item.get("type") == "view":
                    item["row_count"] = None
                    item["row_count_estimate"] = None
                items.append(ExplorerTableItem(**item))
            return ExplorerTableListResponse(items=items, total=total, limit=limit, offset=offset)
        except Exception as exc:
            raise map_connector_error(exc) from exc
        finally:
            _close_connector(connector)

    def get_table_overview(
        self,
        connection_id: int,
        table_ref: str,
        current_user: dict[str, Any],
        db: Session,
    ) -> ExplorerTableOverviewResponse:
        connection = resolve_explorer_connection(connection_id, current_user, db)
        schema, table = _decode_table_ref(table_ref)
        connector = None
        try:
            connector = _connector_for(connection)
            overview_fn = getattr(connector, "get_table_overview", None)
            if callable(overview_fn):
                payload = _to_dict(overview_fn(schema, table))
            else:
                tables = [_to_dict(item) for item in _coerce_items(connector.list_tables(schema=schema, include_views=True))]
                match = next((item for item in tables if item.get("name") == table), None)
                if match is None:
                    raise DEXError.preview_not_allowed({"table": table})
                columns = [_to_dict(item) for item in _coerce_items(connector.list_columns(schema, table))]
                payload = {
                    "schema": schema,
                    "name": table,
                    "type": match.get("type") or match.get("object_type"),
                    "comment": match.get("comment"),
                    "primary_key": [],
                    "column_count": len(columns),
                    "indexes_count": None,
                    "foreign_keys_count": None,
                    "preview_available": True,
                }
        except Exception as exc:
            raise map_connector_error(exc) from exc
        finally:
            _close_connector(connector)
        payload.setdefault("resource_id", f"dbtable:{connection_id}.{schema}.{table}")
        payload.setdefault("schema", schema)
        payload.setdefault("name", table)
        return ExplorerTableOverviewResponse(**payload)

    def list_columns(
        self,
        connection_id: int,
        table_ref: str,
        current_user: dict[str, Any],
        db: Session,
    ) -> ExplorerColumnListResponse:
        connection = resolve_explorer_connection(connection_id, current_user, db)
        schema, table = _decode_table_ref(table_ref)
        connector = None
        try:
            connector = _connector_for(connection)
            items = [ExplorerColumnItem(**_to_dict(item)) for item in _coerce_items(connector.list_columns(schema, table))]
            return ExplorerColumnListResponse(items=items)
        except Exception as exc:
            raise map_connector_error(exc) from exc
        finally:
            _close_connector(connector)

    def preview_table(
        self,
        connection_id: int,
        table_ref: str,
        current_user: dict[str, Any],
        db: Session,
        *,
        limit: int,
    ) -> ExplorerPreviewResponse:
        if limit < 1 or limit > 100:
            raise DEXError.invalid_request({"limit": "must be between 1 and 100"})
        connection = resolve_explorer_connection(connection_id, current_user, db)
        schema, table = _decode_table_ref(table_ref)
        connector = None
        try:
            connector = _connector_for(connection)
            payload = _to_dict(connector.preview_table(schema, table, limit=limit))
            columns = [_to_dict(column) for column in payload.get("columns", [])]
            rows = payload.get("rows", [])
            rows, redaction_applied = _apply_preview_redaction(columns, rows)
            return ExplorerPreviewResponse(
                columns=[ExplorerPreviewColumn(**column) for column in columns],
                rows=rows,
                limit=payload.get("limit", limit),
                truncated=bool(payload.get("truncated", False)),
                execution_time_ms=int(payload.get("execution_time_ms", 0)),
                redaction_applied=redaction_applied or bool(payload.get("redaction_applied", False)),
            )
        except Exception as exc:
            raise map_connector_error(exc, preview=True) from exc
        finally:
            _close_connector(connector)

    def get_permissions(
        self,
        connection_id: int,
        table_ref: str,
        current_user: dict[str, Any],
        db: Session,
    ) -> ExplorerPermissionSummaryResponse:
        connection = resolve_explorer_connection(connection_id, current_user, db)
        schema, table = _decode_table_ref(table_ref)
        connector = None
        try:
            connector = _connector_for(connection)
            connector.list_columns(schema, table)
        except Exception as exc:
            raise map_connector_error(exc) from exc
        finally:
            _close_connector(connector)

        owner = db.query(User).filter(User.id == connection.owner_id).first()
        is_owner = connection.owner_id == current_user.get("id")
        return ExplorerPermissionSummaryResponse(
            resource_id=f"dbtable:{connection_id}.{schema}.{table}",
            current_user=ExplorerPermissionUser(
                id=current_user["id"],
                role=current_user["role"],
                is_owner=is_owner,
            ),
            connection=ExplorerPermissionConnection(
                owner_id=connection.owner_id,
                owner_name=getattr(owner, "username", None),
            ),
            effective_actions=ExplorerEffectiveActions(),
            explanation=[
                "P0 权限来自数据库连接访问权。",
                "当前用户是连接 owner 或具备 admin/data_admin 角色，因此可以浏览 metadata 和 preview。",
                "P0 不支持对象级 grant/revoke。",
            ],
        )


data_explorer_service = DataExplorerService()
