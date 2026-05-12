"""
Tableau MCP Gateway — HTTP-to-stdio bridge

端口   : 3927 (GATEWAY_PORT 覆盖)
端点   : POST   /tableau-mcp   MCP JSON-RPC 主入口
         DELETE /tableau-mcp   释放 HTTP session
         GET    /healthz        健康检查

MCP 协议流程（对 HTTP 客户端）：
  1. POST initialize  → 200 + mcp-session-id header + SSE body
  2. POST notifications/initialized → 202 (子进程已在启动时握手完毕，此处仅 ack)
  3. POST tools/list  → 200 + SSE body  (转发给子进程)
  4. POST tools/call  → 200 + SSE body  (转发给子进程)
  5. DELETE           → 200            (释放 HTTP session)

session 过期条件 : 超过 SESSION_TTL (5 min) 未活动
子进程         : ONE 持久 @tableau/mcp-server 进程，所有 session 共享
"""
import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-06-18"
SESSION_TTL = 300  # 5 min idle timeout
DEFAULT_TOOL_TIMEOUT = int(os.environ.get("GATEWAY_TOOL_TIMEOUT", "55"))
MAX_TOOL_TIMEOUT = int(os.environ.get("GATEWAY_MAX_TOOL_TIMEOUT", "300"))
MULAN_MCP_TIMEOUT_HEADER = "x-mulan-mcp-timeout"

# GATEWAY_CONFIG_ID: 指定加载哪条 mcp_servers 记录（多站点部署时通过环境变量区分）
_CONFIG_ID: Optional[int] = int(os.environ["GATEWAY_CONFIG_ID"]) if os.environ.get("GATEWAY_CONFIG_ID") else None

# ── module-level state ─────────────────────────────────────────────────────────

_proxy: Optional["TableauMCPProxy"] = None  # type: ignore[name-defined]
_sessions: Dict[str, float] = {}  # session_id → last_activity (monotonic)


# ── lifespan: start/stop the persistent subprocess ────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _proxy
    from db import get_active_tableau_config
    from proxy import TableauMCPProxy

    cfg = get_active_tableau_config(_CONFIG_ID)
    if cfg:
        _proxy = TableauMCPProxy(
            tableau_server=cfg["tableau_server"],
            site_name=cfg["site_name"],
            pat_name=cfg["pat_name"],
            pat_value=cfg["pat_value"],
        )
        try:
            await _proxy.start()
        except Exception:
            logger.exception("Failed to start Tableau MCP proxy — running in degraded mode")
            _proxy = None
    else:
        logger.warning("No active Tableau config in DB — running in degraded mode")

    yield

    if _proxy:
        await _proxy.stop()


app = FastAPI(title="Tableau MCP Gateway", version="1.0.0", lifespan=_lifespan,
              docs_url=None, redoc_url=None)


# ── session helpers ────────────────────────────────────────────────────────────

def _touch(sid: str) -> None:
    _sessions[sid] = time.monotonic()


def _valid(sid: str) -> bool:
    t = _sessions.get(sid)
    if t is None:
        return False
    if time.monotonic() - t > SESSION_TTL:
        _sessions.pop(sid, None)
        return False
    return True


def _gc() -> None:
    now = time.monotonic()
    for k in [k for k, v in list(_sessions.items()) if now - v > SESSION_TTL]:
        _sessions.pop(k, None)


def _tool_timeout_from_request(request: Request) -> int:
    """Use the backend's remaining HTTP timeout budget when provided."""
    raw = request.headers.get(MULAN_MCP_TIMEOUT_HEADER)
    if not raw:
        return DEFAULT_TOOL_TIMEOUT
    try:
        parsed = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_TOOL_TIMEOUT
    return max(1, min(parsed, MAX_TOOL_TIMEOUT))


# ── SSE response helpers ───────────────────────────────────────────────────────

def _sse(data: Dict[str, Any],
         extra_headers: Optional[Dict[str, str]] = None) -> Response:
    body = "event: message\ndata: " + json.dumps(data) + "\n\n"
    hdrs = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
    if extra_headers:
        hdrs.update(extra_headers)
    return Response(content=body, media_type="text/event-stream", headers=hdrs)


def _ok(req_id: Any, result: Any,
        extra_headers: Optional[Dict[str, str]] = None) -> Response:
    return _sse({"jsonrpc": "2.0", "id": req_id, "result": result}, extra_headers)


def _err(req_id: Any, code: int, msg: str) -> Response:
    return _sse({"jsonrpc": "2.0", "id": req_id,
                 "error": {"code": code, "message": msg}})


# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/healthz")
async def healthz():
    return {
        "status": "ok" if (_proxy and _proxy.ready) else "degraded",
        "proxy_ready": bool(_proxy and _proxy.ready),
        "active_sessions": len(_sessions),
    }


@app.post("/tableau-mcp")
async def mcp_post(request: Request) -> Response:
    _gc()
    try:
        body = await request.json()
    except Exception:
        return _err(None, -32700, "Parse error: invalid JSON")

    method: str = body.get("method", "")
    req_id = body.get("id")

    # ── initialize: create HTTP session, return cached capabilities ────────────
    if method == "initialize":
        if not _proxy or not _proxy.ready:
            return _err(req_id, -32603, "Tableau MCP proxy not ready — check /healthz")
        sid = str(uuid.uuid4())
        _touch(sid)
        logger.info("New MCP session %s", sid)
        return _ok(
            req_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": _proxy.capabilities,
                "serverInfo": {"name": "tableau-mcp-gateway", "version": "1.0.0"},
            },
            extra_headers={"mcp-session-id": sid},
        )

    # ── notifications/initialized: ack only (subprocess already initialized) ──
    if method == "notifications/initialized":
        sid = request.headers.get("mcp-session-id", "")
        if sid and _valid(sid):
            _touch(sid)
        return Response(status_code=202)

    # ── all other methods require a valid session ──────────────────────────────
    sid = request.headers.get("mcp-session-id", "")
    if not sid or not _valid(sid):
        return Response(content="No valid session ID", status_code=400)
    _touch(sid)

    if not _proxy or not _proxy.ready:
        return _err(req_id, -32603, "Tableau MCP proxy not ready")

    # ── tools/list, tools/call: proxy to subprocess ────────────────────────────
    if method in ("tools/list", "tools/call"):
        params = body.get("params")
        tool_timeout = _tool_timeout_from_request(request)
        try:
            resp = await _proxy.call(method, params, timeout=tool_timeout)
        except asyncio.TimeoutError:
            return _err(req_id, -32000, f"Request timed out after {tool_timeout}s ({method})")
        except Exception as exc:
            return _err(req_id, -32000, str(exc))

        if "result" in resp:
            return _ok(req_id, resp["result"])
        if "error" in resp:
            e = resp["error"]
            return _err(req_id, e.get("code", -32000), e.get("message", "unknown"))

    return _err(req_id, -32601, f"Method not found: {method}")


@app.delete("/tableau-mcp")
async def mcp_delete(request: Request) -> Response:
    sid = request.headers.get("mcp-session-id", "")
    _sessions.pop(sid, None)
    return Response(status_code=200)


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("GATEWAY_PORT", "3927"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
