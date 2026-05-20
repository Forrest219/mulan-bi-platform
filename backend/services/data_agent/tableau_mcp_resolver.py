"""Datasource resolver for the Tableau MCP mainline."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Optional

from services.data_agent.tool_base import ToolContext

logger = logging.getLogger(__name__)

DatasourceAssetLoader = Callable[[int], Sequence[Mapping[str, Any]]]
ConnectionAccessChecker = Callable[[int, Optional[int], Optional[str]], bool]
DatasourceConnectionChecker = Callable[[str, int], bool]


class DatasourceCandidateResolver:
    """Resolve Tableau datasource candidates within one accessible connection."""

    def __init__(
        self,
        *,
        datasource_asset_loader: DatasourceAssetLoader | None = None,
        connection_access_checker: ConnectionAccessChecker | None = None,
        datasource_connection_checker: DatasourceConnectionChecker | None = None,
    ) -> None:
        self._datasource_asset_loader = datasource_asset_loader
        self._connection_access_checker = connection_access_checker
        self._datasource_connection_checker = datasource_connection_checker

    def resolve(
        self,
        question: str,
        context: ToolContext | Mapping[str, Any] | None = None,
        *,
        connection_id: int | None = None,
        user_id: int | None = None,
        user_role: str | None = None,
        max_candidates: int = 5,
    ) -> list[dict[str, Any]]:
        """Return exact candidates first, otherwise contains candidates, capped at 5 by default."""
        resolved_connection_id = _coerce_int(connection_id if connection_id is not None else _context_value(context, "connection_id"))
        resolved_user_id = _coerce_int(user_id if user_id is not None else _context_value(context, "user_id"))
        resolved_user_role = str(user_role if user_role is not None else (_context_value(context, "user_role") or "")).strip() or None
        if resolved_connection_id is None:
            return []
        if not self.connection_is_accessible(
            resolved_connection_id,
            user_id=resolved_user_id,
            user_role=resolved_user_role,
        ):
            return []

        assets = [self._asset_candidate(item) for item in self.load_datasource_assets(resolved_connection_id)]
        if not assets:
            return []

        question_norm = normalize_candidate_text(question)
        mentions = [item for item in datasource_mentions(question) if not is_generic_datasource_mention(item)]
        mention_norms = {normalize_candidate_text(item) for item in mentions if normalize_candidate_text(item)}

        exact: list[dict[str, Any]] = []
        contains: list[dict[str, Any]] = []
        for asset in assets:
            name_norm = normalize_candidate_text(asset.get("name"))
            if not name_norm:
                continue
            if name_norm in mention_norms:
                exact.append(asset)
                continue
            if name_norm in question_norm or any(norm and (norm in name_norm or name_norm in norm) for norm in mention_norms):
                contains.append(asset)

        limit = max(0, int(max_candidates or 0))
        selected = exact or contains
        return selected[:limit]

    def connection_is_accessible(
        self,
        connection_id: int | None,
        *,
        user_id: int | None = None,
        user_role: str | None = None,
    ) -> bool:
        """Return whether the current user can use a Tableau connection."""
        resolved_connection_id = _coerce_int(connection_id)
        if resolved_connection_id is None:
            return False
        if self._connection_access_checker is not None:
            return bool(self._connection_access_checker(resolved_connection_id, user_id, user_role))

        try:
            from app.core.database import SessionLocal
            from services.tableau.models import TableauConnection

            session = SessionLocal()
            try:
                connection = session.query(TableauConnection).filter(TableauConnection.id == resolved_connection_id).first()
                if not connection:
                    return False
                if user_role == "admin":
                    return True
                return user_id is not None and getattr(connection, "owner_id", None) == user_id
            finally:
                session.close()
        except Exception:
            logger.debug("tableau connection access check failed", exc_info=True)
            return False

    def datasource_belongs_to_connection(self, datasource_luid: str | None, connection_id: int | None) -> bool:
        """Return whether a datasource LUID belongs to the requested connection."""
        resolved_connection_id = _coerce_int(connection_id)
        resolved_luid = str(datasource_luid or "").strip()
        if not resolved_luid or resolved_connection_id is None:
            return False
        if self._datasource_connection_checker is not None:
            return bool(self._datasource_connection_checker(resolved_luid, resolved_connection_id))

        try:
            from app.core.database import SessionLocal
            from services.tableau.models import TableauAsset

            session = SessionLocal()
            try:
                return (
                    session.query(TableauAsset)
                    .filter(
                        TableauAsset.connection_id == resolved_connection_id,
                        TableauAsset.asset_type == "datasource",
                        TableauAsset.tableau_id == resolved_luid,
                        TableauAsset.is_deleted == False,  # noqa: E712
                    )
                    .first()
                    is not None
                )
            finally:
                session.close()
        except Exception:
            logger.debug("tableau datasource ownership check failed", exc_info=True)
            return False

    def load_datasource_assets(self, connection_id: int) -> list[Mapping[str, Any]]:
        """Load datasource assets scoped to one Tableau connection."""
        if self._datasource_asset_loader is not None:
            return list(self._datasource_asset_loader(connection_id))

        try:
            from app.core.database import SessionLocal
            from services.tableau.models import TableauAsset

            session = SessionLocal()
            try:
                rows = (
                    session.query(TableauAsset)
                    .filter(
                        TableauAsset.connection_id == connection_id,
                        TableauAsset.asset_type == "datasource",
                        TableauAsset.is_deleted == False,  # noqa: E712
                    )
                    .order_by(TableauAsset.synced_at.desc())
                    .all()
                )
                return [self._asset_candidate(row) for row in rows]
            finally:
                session.close()
        except Exception:
            logger.debug("tableau datasource candidate lookup failed", exc_info=True)
            return []

    @staticmethod
    def _asset_candidate(row: Any) -> dict[str, Any]:
        if isinstance(row, Mapping):
            datasource_luid = row.get("datasource_luid") or row.get("luid") or row.get("tableau_id")
            return {
                "asset_id": row.get("asset_id") or row.get("id"),
                "connection_id": row.get("connection_id"),
                "datasource_luid": datasource_luid,
                "luid": datasource_luid,
                "name": row.get("name"),
                "project_name": row.get("project_name"),
                "description": row.get("description"),
                "field_count": row.get("field_count"),
                "synced_at": _serialize_datetime(row.get("synced_at")),
            }

        datasource_luid = getattr(row, "tableau_id", None)
        return {
            "asset_id": getattr(row, "id", None),
            "connection_id": getattr(row, "connection_id", None),
            "datasource_luid": datasource_luid,
            "luid": datasource_luid,
            "name": getattr(row, "name", None),
            "project_name": getattr(row, "project_name", None),
            "description": getattr(row, "description", None),
            "field_count": getattr(row, "field_count", None),
            "synced_at": _serialize_datetime(getattr(row, "synced_at", None)),
        }


def datasource_mentions(question: str) -> list[str]:
    """Extract explicit datasource mentions using the current mainline MVP patterns."""
    text = str(question or "").strip()
    mentions: list[str] = []
    patterns = (
        r"介绍\s*(.+?数据源)",
        r"说明\s*(.+?数据源)",
        r"(.+?数据源).{0,8}(字段|元数据|表结构|数据结构)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1).strip(" ，。！？?：:")
            if value:
                mentions.append(value)
    if not mentions:
        mentions.append(text)
    return mentions


def normalize_candidate_text(value: Any) -> str:
    """Normalize datasource names for deterministic exact/contains matching."""
    return re.sub(r"[\s，。！？?：:、,.;；（）()【】\[\]\"'`]+", "", str(value or "")).casefold()


def is_generic_datasource_mention(value: str) -> bool:
    normalized = normalize_candidate_text(value)
    generic = {"", "数据源", "数据资产", "介绍数据源", "说明数据源", "字段", "元数据"}
    return normalized in generic or len(normalized) < 2


def _context_value(context: ToolContext | Mapping[str, Any] | None, key: str) -> Any:
    if context is None:
        return None
    if isinstance(context, Mapping):
        return context.get(key)
    return getattr(context, key, None)


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serialize_datetime(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
