"""Pydantic schemas for Database Data Explorer POC."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TableObjectType = Literal["table", "view"]
PermissionMode = Literal["connection_owner_summary"]


class ExplorerErrorResponse(BaseModel):
    error_code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ExplorerConnectionItem(BaseModel):
    id: int
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    owner_id: int
    is_active: bool
    last_tested_at: datetime | None = None
    last_test_success: bool | None = None
    explorer_supported: bool
    unsupported_reason: str | None = None


class ExplorerConnectionListResponse(BaseModel):
    items: list[ExplorerConnectionItem]
    total: int


class ExplorerConnectionDetail(BaseModel):
    id: int
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    is_active: bool
    last_tested_at: datetime | None = None
    last_test_success: bool | None = None


class ExplorerCapabilities(BaseModel):
    schemas: bool = True
    tables: bool = True
    columns: bool = True
    preview: bool = True
    permissions: Literal["read_only"] = "read_only"


class ExplorerConnectionSummary(BaseModel):
    schema_count: int | None = None
    table_count: int | None = None
    view_count: int | None = None


class ExplorerConnectionOverviewResponse(BaseModel):
    connection: ExplorerConnectionDetail
    capabilities: ExplorerCapabilities
    summary: ExplorerConnectionSummary


class ExplorerSchemaItem(BaseModel):
    name: str
    table_count: int | None = None
    view_count: int | None = None


class ExplorerSchemaListResponse(BaseModel):
    items: list[ExplorerSchemaItem]


class ExplorerTableItem(BaseModel):
    schema: str
    name: str
    type: TableObjectType
    comment: str | None = None
    row_count: int | None = None
    row_count_estimate: int | None = None
    column_count: int | None = None
    table_ref: str


class ExplorerTableListResponse(BaseModel):
    items: list[ExplorerTableItem]
    total: int
    limit: int
    offset: int


class ExplorerTableOverviewResponse(BaseModel):
    resource_id: str
    schema: str
    name: str
    type: TableObjectType
    comment: str | None = None
    primary_key: list[str] = Field(default_factory=list)
    column_count: int | None = None
    indexes_count: int | None = None
    foreign_keys_count: int | None = None
    row_count_estimate: int | None = None
    data_size_bytes: int | None = None
    index_size_bytes: int | None = None
    total_size_bytes: int | None = None
    created_at: datetime | None = None
    table_updated_at: datetime | None = None
    preview_available: bool = True


class ExplorerColumnItem(BaseModel):
    name: str
    data_type: str
    nullable: bool | None = None
    default: Any = None
    comment: str | None = None
    is_primary_key: bool = False
    is_indexed: bool = False
    semantic_role: Literal["identifier", "time", "measure", "flag", "dimension"] | None = None


class ExplorerColumnListResponse(BaseModel):
    items: list[ExplorerColumnItem]


class ExplorerPreviewColumn(BaseModel):
    name: str
    data_type: str


class ExplorerPreviewResponse(BaseModel):
    columns: list[ExplorerPreviewColumn]
    rows: list[list[Any]]
    limit: int
    truncated: bool
    execution_time_ms: int
    redaction_applied: bool


class ExplorerPermissionUser(BaseModel):
    id: int
    role: str
    is_owner: bool


class ExplorerPermissionConnection(BaseModel):
    owner_id: int
    owner_name: str | None = None


class ExplorerEffectiveActions(BaseModel):
    view_metadata: bool = True
    preview_rows: bool = True
    export: bool = False
    grant: bool = False


class ExplorerPermissionSummaryResponse(BaseModel):
    resource_id: str
    mode: PermissionMode = "connection_owner_summary"
    current_user: ExplorerPermissionUser
    connection: ExplorerPermissionConnection
    effective_actions: ExplorerEffectiveActions
    explanation: list[str]
