"""Database Data Explorer POC API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_roles
from services.data_explorer.schemas import (
    ExplorerColumnListResponse,
    ExplorerConnectionListResponse,
    ExplorerConnectionOverviewResponse,
    ExplorerErrorResponse,
    ExplorerPermissionSummaryResponse,
    ExplorerPreviewResponse,
    ExplorerSchemaListResponse,
    ExplorerTableListResponse,
    ExplorerTableOverviewResponse,
)
from services.data_explorer.service import data_explorer_service

DEX_ERROR_RESPONSES = {
    400: {"model": ExplorerErrorResponse, "description": "DEX_001 / DEX_003 / DEX_009"},
    403: {"model": ExplorerErrorResponse, "description": "DEX_005"},
    404: {"model": ExplorerErrorResponse, "description": "DEX_002"},
    422: {"model": ExplorerErrorResponse, "description": "DEX_004"},
    500: {"model": ExplorerErrorResponse, "description": "DEX_008"},
    502: {"model": ExplorerErrorResponse, "description": "DEX_010"},
    504: {"model": ExplorerErrorResponse, "description": "DEX_006 / DEX_007"},
}

router = APIRouter(responses=DEX_ERROR_RESPONSES)

_ANALYST_PLUS = ["admin", "data_admin", "analyst"]


@router.get("/connections", response_model=ExplorerConnectionListResponse)
async def list_connections(
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    return data_explorer_service.list_connections(current_user, db)


@router.get("/connections/{connection_id}/overview", response_model=ExplorerConnectionOverviewResponse)
async def get_connection_overview(
    connection_id: int,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    return data_explorer_service.get_connection_overview(connection_id, current_user, db)


@router.get("/connections/{connection_id}/schemas", response_model=ExplorerSchemaListResponse)
async def list_schemas(
    connection_id: int,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    return data_explorer_service.list_schemas(connection_id, current_user, db)


@router.get("/connections/{connection_id}/tables", response_model=ExplorerTableListResponse)
async def list_tables(
    connection_id: int,
    schema: str | None = Query(default=None),
    q: str | None = Query(default=None),
    type: str = Query(default="all", pattern="^(table|view|all)$"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    return data_explorer_service.list_tables(
        connection_id,
        current_user,
        db,
        schema=schema,
        q=q,
        object_type=type,
        limit=limit,
        offset=offset,
    )


@router.get("/connections/{connection_id}/tables/{table_ref}/overview", response_model=ExplorerTableOverviewResponse)
async def get_table_overview(
    connection_id: int,
    table_ref: str,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    return data_explorer_service.get_table_overview(connection_id, table_ref, current_user, db)


@router.get("/connections/{connection_id}/tables/{table_ref}/columns", response_model=ExplorerColumnListResponse)
async def list_columns(
    connection_id: int,
    table_ref: str,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    return data_explorer_service.list_columns(connection_id, table_ref, current_user, db)


@router.get("/connections/{connection_id}/tables/{table_ref}/preview", response_model=ExplorerPreviewResponse)
async def preview_table(
    connection_id: int,
    table_ref: str,
    limit: int = Query(default=100, ge=1, le=100),
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    return data_explorer_service.preview_table(connection_id, table_ref, current_user, db, limit=limit)


@router.get("/connections/{connection_id}/tables/{table_ref}/permissions", response_model=ExplorerPermissionSummaryResponse)
async def get_permissions(
    connection_id: int,
    table_ref: str,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    return data_explorer_service.get_permissions(connection_id, table_ref, current_user, db)
