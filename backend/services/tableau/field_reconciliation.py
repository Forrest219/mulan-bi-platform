"""Reconcile Tableau catalog fields with MCP queryable fields."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from services.tableau.mcp_metadata_fields import (
    extract_mcp_field_metadata,
    extract_queryable_fields_from_metadata,
    field_display_name,
    normalize_field_name,
)
from services.tableau.models import TableauAsset, TableauDatasourceField

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 1000


@dataclass(frozen=True)
class TableauFieldReconciliationResult:
    asset_id: int
    datasource_luid: str
    catalog_field_count: int
    queryable_field_count: int
    catalog_only_count: int
    mcp_only_fields: list[str]
    mcp_checked_at: datetime
    mcp_status: str
    mcp_last_error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "datasource_luid": self.datasource_luid,
            "catalog_field_count": self.catalog_field_count,
            "queryable_field_count": self.queryable_field_count,
            "catalog_only_count": self.catalog_only_count,
            "mcp_only_fields": self.mcp_only_fields,
            "mcp_checked_at": self.mcp_checked_at.isoformat(),
            "mcp_status": self.mcp_status,
            "mcp_last_error": self.mcp_last_error,
        }


def queryability_status(field: TableauDatasourceField) -> str:
    last_error = getattr(field, "mcp_last_error", None)
    if isinstance(last_error, str) and last_error:
        return "error"
    checked_at = getattr(field, "mcp_checked_at", None)
    if not isinstance(getattr(field, "mcp_queryable", None), bool) and not hasattr(checked_at, "isoformat"):
        return "unknown"
    if getattr(field, "mcp_queryable", None) is True:
        return "queryable"
    if getattr(field, "mcp_queryable", None) is False:
        return "catalog_only"
    return "unknown"


def summarize_field_capabilities(fields: list[TableauDatasourceField]) -> dict[str, Any]:
    catalog_count = len(fields or [])
    queryable_count = sum(1 for field in fields if getattr(field, "mcp_queryable", None) is True)
    catalog_only_count = sum(1 for field in fields if queryability_status(field) == "catalog_only")
    checked_values = [
        value
        for field in fields
        if hasattr((value := getattr(field, "mcp_checked_at", None)), "isoformat")
    ]
    error_values = [
        value
        for field in fields
        if isinstance((value := getattr(field, "mcp_last_error", None)), str) and value
    ]
    if error_values:
        mcp_status = "error"
    elif not checked_values:
        mcp_status = "unknown"
    elif catalog_only_count > 0:
        mcp_status = "partial"
    else:
        mcp_status = "ok"
    latest_checked_at = max(checked_values) if checked_values else None
    return {
        "field_count": catalog_count,
        "catalog_field_count": catalog_count,
        "queryable_field_count": queryable_count,
        "catalog_only_count": catalog_only_count,
        "mcp_checked_at": latest_checked_at.isoformat() if latest_checked_at else None,
        "mcp_status": mcp_status,
        "mcp_last_error": error_values[0] if error_values else None,
    }


class TableauFieldReconciliationService:
    def __init__(self, db: Session):
        self.db = db

    def reconcile_asset(
        self,
        *,
        asset_id: int,
        connection_id: Optional[int] = None,
        datasource_luid: Optional[str] = None,
        metadata: Any = None,
    ) -> TableauFieldReconciliationResult:
        asset = self.db.query(TableauAsset).filter(TableauAsset.id == asset_id).first()
        if not asset:
            raise ValueError(f"Tableau asset not found: {asset_id}")
        effective_connection_id = connection_id or asset.connection_id
        effective_luid = str(datasource_luid or asset.tableau_id or "").strip()
        if not effective_luid:
            raise ValueError(f"Tableau asset has no datasource LUID: {asset_id}")

        fields = self._catalog_fields(asset_id=asset_id, datasource_luid=effective_luid)
        checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            if metadata is None:
                from services.tableau.mcp_client import get_tableau_mcp_client

                metadata = get_tableau_mcp_client(connection_id=effective_connection_id).get_datasource_metadata(
                    effective_luid,
                    timeout=20,
                )
            return self._save_success(
                asset_id=asset_id,
                datasource_luid=effective_luid,
                fields=fields,
                metadata=metadata,
                checked_at=checked_at,
            )
        except Exception as exc:
            logger.warning(
                "Tableau MCP field reconciliation failed: asset_id=%s datasource_luid=%s error=%s",
                asset_id,
                effective_luid,
                exc,
            )
            return self._save_error(
                asset_id=asset_id,
                datasource_luid=effective_luid,
                fields=fields,
                checked_at=checked_at,
                error=str(exc),
            )

    def _catalog_fields(self, *, asset_id: int, datasource_luid: str) -> list[TableauDatasourceField]:
        return (
            self.db.query(TableauDatasourceField)
            .filter(
                TableauDatasourceField.asset_id == asset_id,
                TableauDatasourceField.datasource_luid == datasource_luid,
            )
            .order_by(TableauDatasourceField.role, TableauDatasourceField.field_name)
            .all()
        )

    def _save_success(
        self,
        *,
        asset_id: int,
        datasource_luid: str,
        fields: list[TableauDatasourceField],
        metadata: Any,
        checked_at: datetime,
    ) -> TableauFieldReconciliationResult:
        mcp_metadata = extract_mcp_field_metadata(metadata)
        queryable_names = extract_queryable_fields_from_metadata(metadata)
        queryable_by_normalized = {
            normalize_field_name(name): item
            for item in mcp_metadata
            if (name := field_display_name(item))
        }
        queryable_name_by_normalized = {
            normalize_field_name(name): name
            for name in queryable_names
        }
        matched: set[str] = set()

        for field in fields:
            names = [
                getattr(field, "field_name", None),
                getattr(field, "field_caption", None),
            ]
            matched_key = next(
                (
                    normalize_field_name(name)
                    for name in names
                    if normalize_field_name(name) in queryable_by_normalized
                ),
                None,
            )
            field.mcp_checked_at = checked_at
            field.mcp_last_error = None
            if matched_key:
                payload = queryable_by_normalized[matched_key]
                field.mcp_queryable = True
                field.mcp_field_name = str(payload.get("name") or payload.get("fieldName") or queryable_name_by_normalized.get(matched_key) or "")
                field.mcp_field_caption = str(payload.get("fieldCaption") or payload.get("caption") or field_display_name(payload) or "")
                matched.add(matched_key)
            else:
                field.mcp_queryable = False
                field.mcp_field_name = None
                field.mcp_field_caption = None

        self.db.commit()
        mcp_only = [
            queryable_name_by_normalized[key]
            for key in queryable_name_by_normalized
            if key not in matched
        ]
        catalog_only_count = sum(1 for field in fields if getattr(field, "mcp_queryable", None) is False)
        status = "ok" if catalog_only_count == 0 else "partial"
        return TableauFieldReconciliationResult(
            asset_id=asset_id,
            datasource_luid=datasource_luid,
            catalog_field_count=len(fields),
            queryable_field_count=sum(1 for field in fields if getattr(field, "mcp_queryable", None) is True),
            catalog_only_count=catalog_only_count,
            mcp_only_fields=mcp_only,
            mcp_checked_at=checked_at,
            mcp_status=status,
        )

    def _save_error(
        self,
        *,
        asset_id: int,
        datasource_luid: str,
        fields: list[TableauDatasourceField],
        checked_at: datetime,
        error: str,
    ) -> TableauFieldReconciliationResult:
        message = (error or "MCP metadata reconciliation failed")[:MAX_ERROR_LENGTH]
        for field in fields:
            field.mcp_checked_at = checked_at
            field.mcp_last_error = message
        self.db.commit()
        return TableauFieldReconciliationResult(
            asset_id=asset_id,
            datasource_luid=datasource_luid,
            catalog_field_count=len(fields),
            queryable_field_count=sum(1 for field in fields if getattr(field, "mcp_queryable", None) is True),
            catalog_only_count=sum(1 for field in fields if getattr(field, "mcp_queryable", None) is False),
            mcp_only_fields=[],
            mcp_checked_at=checked_at,
            mcp_status="error",
            mcp_last_error=message,
        )
