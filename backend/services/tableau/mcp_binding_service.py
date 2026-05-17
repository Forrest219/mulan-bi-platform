"""Tableau connection to MCP Gateway binding service."""
from __future__ import annotations

import logging
from typing import Literal, Optional, TypedDict

import requests
from sqlalchemy.orm import Session

from services.common.settings import get_tableau_mcp_gateway_url, normalize_tableau_mcp_endpoint
from services.mcp.models import McpServer
from services.tableau.models import TableauConnection


logger = logging.getLogger(__name__)

BindingStatus = Literal["bound", "disabled", "unhealthy", "unbound"]
HealthStatus = Literal["healthy", "unhealthy", "unknown"]


class McpBindingResult(TypedDict):
    enabled: bool
    mcp_server_id: Optional[int]
    server_url: Optional[str]
    status: BindingStatus
    binding_status: BindingStatus
    health_status: HealthStatus
    message: str
    last_error: Optional[str]


def resolve_tableau_mcp_gateway_url() -> Optional[str]:
    return get_tableau_mcp_gateway_url()


class TableauMcpBindingService:
    def __init__(self, db: Session):
        self.db = db

    def get_binding_for_connection(
        self,
        *,
        connection_id: int,
        active_only: bool = False,
    ) -> Optional[McpServer]:
        query = self.db.query(McpServer).filter(
            McpServer.type == "tableau",
            McpServer.tableau_connection_id == connection_id,
        )
        if active_only:
            query = query.filter(McpServer.is_active == True)
        return query.order_by(
            McpServer.is_active.desc(),
            McpServer.updated_at.desc(),
            McpServer.id.desc(),
        ).first()

    def upsert_for_connection(
        self,
        *,
        connection: TableauConnection,
        enabled: bool,
        owner_id: int,
        health_check: bool = True,
        endpoint_override: Optional[str] = None,
    ) -> McpBindingResult:
        if not enabled:
            return self.disable_for_connection(
                connection_id=connection.id,
                reason="Agent access disabled",
            )

        gateway_url = normalize_tableau_mcp_endpoint(
            endpoint_override or resolve_tableau_mcp_gateway_url()
        ) or ""
        if not gateway_url:
            return self.disable_for_connection(
                connection_id=connection.id,
                reason="TABLEAU_MCP_GATEWAY_URL is not configured",
            )

        binding = self._ensure_binding(connection=connection, gateway_url=gateway_url)
        self.db.flush()

        if not health_check:
            binding.binding_status = "unbound"
            binding.health_status = "unknown"
            binding.last_binding_error = None
            connection.mcp_direct_enabled = True
            connection.mcp_server_url = gateway_url
            return self._result(
                binding,
                status="unbound",
                health_status="unknown",
                message="Tableau MCP Gateway binding pending health check",
                last_error=None,
            )

        return self._apply_health_result(
            connection=connection,
            binding=binding,
            ok_error=self._check_gateway_health(
                gateway_url,
                connection_id=connection.id,
                mcp_server_id=binding.id,
                user_id=owner_id,
            ),
        )

    def refresh_health_for_connection(
        self,
        *,
        connection_id: int,
        user_id: int,
    ) -> McpBindingResult:
        connection = self.db.query(TableauConnection).filter(TableauConnection.id == connection_id).first()
        binding = self.get_binding_for_connection(connection_id=connection_id)
        if connection is None or binding is None or not binding.is_active:
            return self.serialize_for_connection(connection_id)

        gateway_url = normalize_tableau_mcp_endpoint(
            binding.server_url or resolve_tableau_mcp_gateway_url()
        ) or ""
        if not gateway_url:
            return self.disable_for_connection(
                connection_id=connection_id,
                reason="TABLEAU_MCP_GATEWAY_URL is not configured",
            )
        binding.server_url = gateway_url

        return self._apply_health_result(
            connection=connection,
            binding=binding,
            ok_error=self._check_gateway_health(
                gateway_url,
                connection_id=connection.id,
                mcp_server_id=binding.id,
                user_id=user_id,
            ),
        )

    def _ensure_binding(self, *, connection: TableauConnection, gateway_url: str) -> McpServer:
        binding = self.get_binding_for_connection(connection_id=connection.id)
        if binding is None:
            binding = McpServer(
                name=self._binding_name(connection),
                type="tableau",
                server_url=gateway_url,
                description=f"Auto-bound Tableau MCP Gateway for {connection.name}",
                is_active=True,
                credentials={"tableau_connection_id": connection.id},
                tableau_connection_id=connection.id,
                binding_source="auto_tableau_connection",
                binding_status="unbound",
                health_status="unknown",
            )
            self.db.add(binding)
        else:
            binding.name = binding.name or self._binding_name(connection)
            binding.server_url = gateway_url
            binding.description = binding.description or f"Auto-bound Tableau MCP Gateway for {connection.name}"
            binding.is_active = True
            binding.tableau_connection_id = connection.id
            binding.binding_source = (
                binding.binding_source
                if binding.binding_source and binding.binding_source != "manual"
                else "auto_tableau_connection"
            )
            binding.credentials = self._strip_tableau_pat(binding.credentials)
            binding.credentials["tableau_connection_id"] = connection.id

        return binding

    def _apply_health_result(
        self,
        *,
        connection: TableauConnection,
        binding: McpServer,
        ok_error: tuple[bool, Optional[str]],
    ) -> McpBindingResult:
        ok, error = ok_error
        if ok:
            binding.binding_status = "bound"
            binding.health_status = "healthy"
            binding.last_binding_error = None
            connection.mcp_direct_enabled = True
            connection.mcp_server_url = binding.server_url
            return self._result(
                binding,
                status="bound",
                health_status="healthy",
                message="Tableau MCP Gateway binding is active",
                last_error=None,
            )

        binding.binding_status = "unhealthy"
        binding.health_status = "unhealthy"
        binding.last_binding_error = error
        connection.mcp_direct_enabled = True
        connection.mcp_server_url = binding.server_url
        return self._result(
            binding,
            status="unhealthy",
            health_status="unhealthy",
            message=error or "Tableau MCP Gateway health check failed",
            last_error=error,
        )

    def disable_for_connection(
        self,
        *,
        connection_id: int,
        reason: Optional[str] = None,
    ) -> McpBindingResult:
        binding = self.get_binding_for_connection(connection_id=connection_id)
        connection = self.db.query(TableauConnection).filter(TableauConnection.id == connection_id).first()
        self._disable_connection_agent(connection, binding)
        if binding is None:
            return self._result(
                None,
                status="disabled",
                health_status="unknown",
                message=reason or "Agent access disabled",
                last_error=reason,
            )
        binding.is_active = False
        binding.binding_status = "disabled"
        binding.health_status = "unknown"
        binding.last_binding_error = reason
        return self._result(
            binding,
            status="disabled",
            health_status="unknown",
            message=reason or "Agent access disabled",
            last_error=reason,
        )

    def serialize_for_connection(self, connection_id: int) -> McpBindingResult:
        binding = self.get_binding_for_connection(connection_id=connection_id)
        if binding is None:
            return self._result(
                None,
                status="disabled",
                health_status="unknown",
                message="Agent access disabled",
                last_error=None,
            )
        status = binding.binding_status or ("bound" if binding.is_active else "disabled")
        return self._result(
            binding,
            status=status,
            health_status=binding.health_status or "unknown",
            message=binding.last_binding_error or status,
            last_error=binding.last_binding_error,
        )

    @staticmethod
    def _binding_name(connection: TableauConnection) -> str:
        return f"tableau:{connection.id}:{connection.name}"[:128]

    @staticmethod
    def _strip_tableau_pat(credentials: Optional[dict]) -> dict:
        cleaned = dict(credentials or {})
        cleaned.pop("pat_value", None)
        cleaned.pop("token_value", None)
        cleaned.pop("token_secret", None)
        return cleaned

    @staticmethod
    def _disable_connection_agent(connection: Optional[TableauConnection], binding: Optional[McpServer]) -> None:
        if connection is not None:
            connection.mcp_direct_enabled = False
            if binding is None:
                connection.mcp_server_url = None

    @staticmethod
    def _check_gateway_health(
        gateway_url: str,
        *,
        connection_id: int,
        mcp_server_id: int,
        user_id: int,
    ) -> tuple[bool, Optional[str]]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mulan-bi-binding-health", "version": "1.0"},
            },
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-Mulan-Tableau-Connection-Id": str(connection_id),
            "X-Mulan-Mcp-Server-Id": str(mcp_server_id),
            "X-Mulan-User-Id": str(user_id),
            "X-Mulan-Trace-Id": f"binding-health-{connection_id}-{mcp_server_id}",
        }
        try:
            response = requests.post(gateway_url, json=payload, headers=headers, timeout=5)
        except Exception as exc:
            logger.warning("Tableau MCP Gateway health check failed: %s", exc)
            return False, f"TABLEAU_MCP_GATEWAY_URL health check failed: {type(exc).__name__}"

        if response.status_code >= 400:
            return False, f"TABLEAU_MCP_GATEWAY_URL health check failed: HTTP {response.status_code}"
        return True, None

    @staticmethod
    def _result(
        binding: Optional[McpServer],
        *,
        status: BindingStatus,
        health_status: HealthStatus,
        message: str,
        last_error: Optional[str],
    ) -> McpBindingResult:
        return {
            "enabled": status == "bound",
            "mcp_server_id": binding.id if binding is not None else None,
            "server_url": binding.server_url if binding is not None else None,
            "status": status,
            "binding_status": status,
            "health_status": health_status,
            "message": message,
            "last_error": last_error,
        }
