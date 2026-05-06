"""
官方 @tableau/mcp-server stdio 子进程管理器

架构：
  Gateway 启动时创建 ONE 持久 subprocess（@tableau/mcp-server via npm）
  Gateway 完成 MCP initialize 握手后，所有 HTTP session 共享该 subprocess
  tools/list / tools/call 请求通过 asyncio 队列串行化后发送到 stdin
  stdout 读取循环按 JSON-RPC id 将响应路由到对应的等待 Future
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_GATEWAY_DIR = os.path.dirname(__file__)
# 优先使用本地 node_modules 内的二进制（npm install 后存在）
_LOCAL_BIN = os.path.join(_GATEWAY_DIR, "node_modules", ".bin", "tableau-mcp-server")


class TableauMCPProxy:
    """
    包装一个持久的 @tableau/mcp-server 子进程。

    线程安全性：通过 asyncio.Lock 串行化所有 tools/ 调用，
    确保同一时刻只有一个请求在 stdin/stdout 上飞行。
    """

    MCP_VERSION = "2025-06-18"

    def __init__(self, tableau_server: str, site_name: str, pat_name: str, pat_value: str):
        self._env = {
            **os.environ,
            "SERVER": tableau_server,
            "SITE_NAME": site_name,
            "PAT_NAME": pat_name,
            "PAT_VALUE": pat_value,
        }
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._pending: Dict[int, asyncio.Future] = {}
        self._id_seq = 0
        self._reader_task: Optional[asyncio.Task] = None
        self._capabilities: Dict = {}
        self._ready = False

    # ── public interface ───────────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        return self._ready and self._proc is not None and self._proc.returncode is None

    @property
    def capabilities(self) -> Dict:
        return self._capabilities

    async def start(self) -> None:
        """Spawn subprocess and complete MCP initialize / notifications/initialized."""
        cmd = self._build_cmd()
        logger.info("Spawning Tableau MCP server: %s", " ".join(cmd))
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
            cwd=_GATEWAY_DIR,
            limit=4 * 1024 * 1024,  # 4 MB — tools/list responses can be large
        )
        self._reader_task = asyncio.create_task(self._read_loop(), name="mcp-reader")
        asyncio.create_task(self._drain_stderr(), name="mcp-stderr")

        # MCP initialize handshake (60s budget for npm cold-start)
        resp = await self._rpc("initialize", {
            "protocolVersion": self.MCP_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "tableau-mcp-gateway", "version": "1.0.0"},
        }, timeout=120)

        if "error" in resp:
            raise RuntimeError(f"MCP initialize failed: {resp['error']}")

        self._capabilities = resp.get("result", {}).get("capabilities", {})

        # notifications/initialized (fire-and-forget)
        await self._notify("notifications/initialized", {})

        self._ready = True
        logger.info("Tableau MCP proxy ready. capabilities=%s", list(self._capabilities.keys()))

    async def call(self, method: str, params: Any = None, timeout: int = 60) -> Dict:
        """Serialize a JSON-RPC call through the subprocess. Returns full response dict."""
        async with self._lock:
            return await self._rpc(method, params, timeout=timeout)

    async def stop(self) -> None:
        self._ready = False
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()
        self._proc = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("MCP proxy stopped"))
        self._pending.clear()

    # ── internal ───────────────────────────────────────────────────────────────

    def _build_cmd(self):
        if os.path.exists(_LOCAL_BIN):
            return [_LOCAL_BIN]
        # fall back to npx (will use cache or download)
        return ["npx", "-y", "@tableau/mcp-server@latest"]

    def _next_id(self) -> int:
        self._id_seq += 1
        return self._id_seq

    async def _write(self, payload: Dict) -> None:
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def _rpc(self, method: str, params: Any = None, timeout: int = 60) -> Dict:
        req_id = self._next_id()
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[req_id] = fut

        await self._write(payload)
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise

    async def _notify(self, method: str, params: Any = None) -> None:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        await self._write(payload)

    async def _read_loop(self) -> None:
        """Background task: read stdout lines and dispatch to pending Futures."""
        assert self._proc and self._proc.stdout
        while True:
            try:
                raw = await self._proc.stdout.readline()
            except Exception as exc:
                logger.warning("MCP stdout read error: %s", exc)
                break
            if not raw:
                break
            line = raw.strip()
            if not line or not line.startswith(b"{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            req_id = msg.get("id")
            if req_id is not None:
                fut = self._pending.pop(req_id, None)
                if fut and not fut.done():
                    fut.set_result(msg)

        logger.warning("MCP subprocess stdout closed — proxy no longer ready")
        self._ready = False
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("MCP subprocess stdout closed"))
        self._pending.clear()

    async def _drain_stderr(self) -> None:
        """Forward subprocess stderr to our logger (non-blocking)."""
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            logger.debug("[mcp-server] %s", line.decode(errors="replace").rstrip())


import contextlib  # noqa: E402 – after class definition to avoid circular
