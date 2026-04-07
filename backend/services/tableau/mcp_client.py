"""
Tableau MCP 查询客户端（Stage 3 执行层）

PRD §5.5 契约实现：
- 约束 A：环境变量完整性（PAT 解密后注入）
- 约束 B：MCP ClientSession 长连接复用（单例模式）
- 约束 C：VizQL JSON 与字段元数据一致性校验
- 约束 D（新增 P0）：connection_id 贯穿上下文，禁止跨租户 client 缓存

MCP Server 通信：JSON-RPC 2.0 over HTTP
"""
import contextvars
import json
import logging
import threading
from typing import Any, Dict, List, Optional

import requests

from app.core.crypto import get_tableau_crypto
from services.common.settings import get_tableau_mcp_server_url, get_tableau_mcp_timeout
from services.tableau.models import TableauConnection, TableauAsset


class _CachedTableauConnection:
    """
    TableauConnection 脱管缓存对象。

    仅保存查询得到的必要属性（原始 Python 类型），不持有 SQLAlchemy Session 引用。
    用于在 Session 关闭后安全访问连接属性，防止 DetachedInstanceError。
    """

    __slots__ = (
        "id", "server_url", "site", "token_name", "token_encrypted",
        "is_active", "last_test_success",
    )

    def __init__(
        self,
        id: int,
        server_url: str,
        site: str,
        token_name: str,
        token_encrypted: str,
        is_active: bool,
        last_test_success: bool,
    ):
        self.id = id
        self.server_url = server_url
        self.site = site
        self.token_name = token_name
        self.token_encrypted = token_encrypted
        self.is_active = is_active
        self.last_test_success = last_test_success

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# connection_id 上下文变量（约束 D：跨协程传递租户上下文）
# ─────────────────────────────────────────────────────────────────────────────
_connection_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "tableau_mcp_connection_id", default=None
)


def set_mcp_connection_id(connection_id: int) -> None:
    """在当前上下文设置 connection_id（由调用方在发起 MCP 请求前调用）"""
    _connection_id_var.set(connection_id)


def get_mcp_connection_id() -> Optional[int]:
    """获取当前上下文的 connection_id"""
    return _connection_id_var.get()

# ─────────────────────────────────────────────────────────────────────────────
# 单例 Session 管理器（约束 B：长连接复用）
# ─────────────────────────────────────────────────────────────────────────────

_session_lock = threading.Lock()
_session_cache: Optional[requests.Session] = None


def _get_shared_session() -> requests.Session:
    """
    获取共享的 requests.Session（单例）。
    requests.Session 会自动维护 TCP 连接池和 Connection Reuse，
    避免每次请求都新建 TCP 连接。
    """
    global _session_cache
    if _session_cache is None:
        with _session_lock:
            if _session_cache is None:
                _session_cache = requests.Session()
                # 配置连接池参数
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=0,  # 重试由上层控制
                )
                _session_cache.mount("http://", adapter)
                _session_cache.mount("https://", adapter)
    return _session_cache


# ─────────────────────────────────────────────────────────────────────────────
# Tableau MCP Client
# ─────────────────────────────────────────────────────────────────────────────

class TableauMCPError(Exception):
    """Tableau MCP 查询异常"""
    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class TableauMCPClient:
    """
    Tableau MCP 查询客户端（per-connection_id 实例模式，约束 D P0 修复）。

    核心 invariant：每个 connection_id 对应唯一 client 实例，
    禁止跨租户共享（防止高并发下数据串签）。

    使用方式：
        client = get_tableau_mcp_client(connection_id=conn_id)
        result = client.query_datasource(datasource_luid, vizql_json, connection_id=conn_id, timeout=30)

    ⚡ 长连接复用（约束 B）：内部使用共享 Session，
    不会每次调用都新建 TCP 连接。
    ⚡ 租户隔离（约束 D）：client 按 connection_id 隔离。
    ⚡ 内存安全（P1）：_instances 和 _ds_connection_cache 均有最大容量限制，防止 OOM。
    """

    # 按 connection_id 隔离的 client 实例缓存（替代全局单例）
    _instances: Dict[int, "TableauMCPClient"] = {}
    _instances_lock = threading.Lock()
    _MAX_INSTANCES = 200  # P1 OOM 防护：限制最大实例数

    def __new__(cls, connection_id: int) -> "TableauMCPClient":
        # P1 OOM 防护：超过最大实例数时，清空最老的 half
        with cls._instances_lock:
            if len(cls._instances) >= cls._MAX_INSTANCES:
                # FIFO 清理：保留最新的 half
                keys_to_remove = list(cls._instances.keys())[: len(cls._instances) // 2]
                for k in keys_to_remove:
                    del cls._instances[k]
                logger.warning("TableauMCPClient 实例数超限，已清理 %d 个旧实例", len(keys_to_remove))
        if connection_id not in cls._instances:
            with cls._instances_lock:
                if connection_id not in cls._instances:
                    cls._instances[connection_id] = super().__new__(cls)
        return cls._instances[connection_id]

    def __init__(self, connection_id: int):
        if getattr(self, "_initialized", False) and getattr(self, "_connection_id", None) == connection_id:
            return
        self._initialized = True
        self._connection_id = connection_id
        self._session = _get_shared_session()
        # Cache key = (connection_id, datasource_luid)，防止跨租户串签
        # P1 OOM 防护：限制最大缓存条目数
        self._ds_connection_cache: Dict[str, "TableauConnection|_CachedTableauConnection"] = {}
        self._MAX_CACHE_SIZE = 500

    def _get_connection_by_luid(self, datasource_luid: str, connection_id: int) -> "TableauConnection|_CachedTableauConnection":
        """
        通过 datasource_luid 查找对应的 TableauConnection（带内存缓存，cache key 含 connection_id）。

        P0 修复：使用 try...finally 确保 Session 在查询全部完成后才关闭，
        并在关闭前将 conn 所需属性全部读取为原始类型（脱管对象安全访问）。
        """
        cache_key = f"{connection_id}:{datasource_luid}"
        if cache_key in self._ds_connection_cache:
            return self._ds_connection_cache[cache_key]

        # P1 合规修复：使用标准 SessionLocal 而非废弃的 TableauDatabase()
        from app.core.database import SessionLocal
        session = SessionLocal()
        conn = None
        try:
            # 精确匹配：必须同时满足 connection_id 和 datasource_luid
            asset = session.query(TableauAsset).filter(
                TableauAsset.datasource_luid == datasource_luid,
                TableauAsset.connection_id == connection_id,
                TableauAsset.is_deleted == False,
            ).first()

            if not asset:
                raise TableauMCPError(
                    code="NLQ_009",
                    message="数据源不存在或已删除或不属于该连接",
                    details={"datasource_luid": datasource_luid, "connection_id": connection_id},
                )

            conn = session.query(TableauConnection).filter(
                TableauConnection.id == connection_id,
            ).first()

            if not conn:
                raise TableauMCPError(
                    code="NLQ_009",
                    message="数据源关联的连接不存在",
                    details={"datasource_luid": datasource_luid, "connection_id": connection_id},
                )

            # P0 修复：在 session 关闭前，提前读取所有后续所需的属性，
            # 将 SQLAlchemy 托管对象转换为普通 Python 原始类型，
            # 避免脱管后访问触发 DetachedInstanceError。
            conn_attrs = {
                "id": conn.id,
                "server_url": conn.server_url,
                "site": conn.site,
                "token_name": conn.token_name,
                "token_encrypted": conn.token_encrypted,
                "is_active": conn.is_active,
                "last_test_success": conn.last_test_success,
            }
        finally:
            session.close()

        # P1 OOM 防护：缓存超过最大容量时，清空最老的 half
        if len(self._ds_connection_cache) >= self._MAX_CACHE_SIZE:
            keys_to_remove = list(self._ds_connection_cache.keys())[: len(self._ds_connection_cache) // 2]
            for k in keys_to_remove:
                del self._ds_connection_cache[k]
            logger.warning("连接缓存超限，已清理 %d 条旧缓存", len(keys_to_remove))

        # 重建为普通对象存入缓存（不再绑定到已关闭 session）
        cached_conn = _CachedTableauConnection(**conn_attrs)
        self._ds_connection_cache[cache_key] = cached_conn
        return cached_conn

    # ─────────────────────────────────────────────────────────────────────────
    # 公开 API
    # ─────────────────────────────────────────────────────────────────────────

    def query_datasource(
        self,
        datasource_luid: str,
        query: Dict[str, Any],
        limit: int = 1000,
        timeout: int = 30,
        connection_id: int = None,
    ) -> Dict[str, Any]:
        """
        通过 Tableau MCP 查询数据源（Stage 3 执行）。

        参数：
            datasource_luid: Tableau 数据源 LUID
            query: VizQL 查询 JSON（符合 PRD §5.5.2 格式）
            limit: 最大返回行数（默认 1000）
            timeout: 超时秒数（默认 30）
            connection_id: 租户连接 ID（必填，约束 D）

        返回：
            {"fields": [...], "rows": [[...], ...]}（符合 PRD §5.5.3 格式）

        异常：
            TableauMCPError: NLQ_006 / NLQ_007 / NLQ_009

        约束 A：环境变量从 TableauConnection 解密注入
        约束 B：Session 长连接复用
        约束 D：connection_id 必须传入，用于 cache key 隔离
        """
        if connection_id is None:
            raise TableauMCPError(
                code="NLQ_009",
                message="connection_id 为必填参数（MCP 查询禁止空上下文）",
                details={"datasource_luid": datasource_luid},
            )

        # P2 修复：捕获 ContextVar Token，确保请求结束后清理，防止线程污染
        token = _connection_id_var.set(connection_id)
        try:
            # 1. 获取连接信息（带缓存，cache key 含 connection_id）
            conn = self._get_connection_by_luid(datasource_luid, connection_id)

            # 2. 校验连接可用性（PRD §5.5.4）
            if not conn.is_active:
                raise TableauMCPError(
                    code="NLQ_009",
                    message="Tableau 连接已禁用",
                    details={"datasource_luid": datasource_luid},
                )
            if conn.last_test_success is False:
                raise TableauMCPError(
                    code="NLQ_009",
                    message="Tableau 连接测试失败，请联系管理员",
                    details={"datasource_luid": datasource_luid},
                )

            # 3. 解密 PAT（约束 A）
            pat_value = self._decrypt_pat(conn)
            env_vars = {
                "TABLEAU_SERVER_URL": conn.server_url,
                "TABLEAU_SITE": conn.site,
                "TABLEAU_PAT_NAME": conn.token_name,
                "TABLEAU_PAT_VALUE": pat_value,
            }

            # 4. 组装 MCP JSON-RPC 请求
            payload = self._build_jsonrpc_request(
                datasource_luid=datasource_luid,
                query=query,
                limit=limit,
                env_vars=env_vars,
            )

            # 5. 发送请求（约束 B：复用 Session）
            response = self._send_jsonrpc(payload, timeout=timeout)

            # 6. 解析响应
            return self._parse_jsonrpc_response(response)
        finally:
            _connection_id_var.reset(token)

    # ─────────────────────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────────────────────

    def _decrypt_pat(self, conn) -> str:
        """解密 PAT Secret（约束 A）"""
        try:
            crypto = get_tableau_crypto()
            return crypto.decrypt(conn.token_encrypted)
        except Exception as e:
            logger.error("PAT 解密失败: %s", e)
            raise TableauMCPError(
                code="NLQ_009",
                message="认证凭据解密失败",
                details={"connection_id": conn.id},
            )

    def _build_jsonrpc_request(
        self,
        datasource_luid: str,
        query: Dict[str, Any],
        limit: int,
        env_vars: Dict[str, str],
    ) -> dict:
        """组装 MCP JSON-RPC 2.0 请求"""
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "query-datasource",
            "params": {
                "datasourceLuid": datasource_luid,
                "query": query,
                "limit": limit,
                # 环境变量注入（约束 A）
                "env": env_vars,
            },
        }

    def _send_jsonrpc(self, payload: dict, timeout: int) -> dict:
        """
        发送 JSON-RPC 请求。

        重试策略（PRD §5.5.5）：
        - 网络错误 / 5xx：重试 1 次，间隔 1s
        - 4xx：直接返回，不重试
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        for attempt in range(2):
            try:
                resp = self._session.post(
                    f"{get_tableau_mcp_server_url()}/query-datasource",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
                if resp.status_code >= 500 and attempt == 0:
                    # 5xx：重试一次
                    import time
                    time.sleep(1)
                    continue
                # P1 修复：5xx 响应可能是 HTML 错误页，JSON 解析会崩溃
                try:
                    body = resp.json()
                except (ValueError, json.JSONDecodeError):
                    body = {}
                return {"status_code": resp.status_code, "body": body, "raw": resp.text}

            except requests.exceptions.Timeout:
                raise TableauMCPError(
                    code="NLQ_007",
                    message=f"查询超时（{timeout}s）",
                    details={"timeout": timeout},
                )
            except requests.exceptions.ConnectionError as e:
                if attempt == 0:
                    import time
                    time.sleep(1)
                    continue
                logger.error("MCP 连接失败: %s", e)
                raise TableauMCPError(
                    code="NLQ_006",
                    message="MCP 服务不可用",
                    details={"mcp_server_url": get_tableau_mcp_server_url()},
                )
            except Exception as e:
                logger.error("MCP 请求异常: %s", e)
                raise TableauMCPError(
                    code="NLQ_006",
                    message=f"MCP 请求失败: {str(e)}",
                    details={},
                )

        # 最后一次尝试（已经处理过 5xx 重试）
        try:
            body = resp.json()
        except (ValueError, json.JSONDecodeError):
            body = {}
        return {"status_code": resp.status_code, "body": body, "raw": resp.text}

    def _parse_jsonrpc_response(self, response: dict) -> dict:
        """解析 MCP JSON-RPC 响应"""
        status_code = response["status_code"]

        # 处理 HTTP 错误状态码
        if status_code == 400:
            body = response.get("body", {})
            error_msg = body.get("error", {}).get("message", "VizQL 语法错误")
            raise TableauMCPError(
                code="NLQ_006",
                message=f"VizQL 查询语法错误: {error_msg}",
                details={"body": body},
            )
        elif status_code == 403:
            raise TableauMCPError(
                code="NLQ_009",
                message="数据源访问被拒绝（无权限）",
                details={"status_code": 403},
            )
        elif status_code == 404:
            raise TableauMCPError(
                code="NLQ_009",
                message="数据源不存在",
                details={"status_code": 404},
            )
        elif status_code >= 400:
            raise TableauMCPError(
                code="NLQ_006",
                message=f"MCP 查询失败（HTTP {status_code}）",
                details={"status_code": status_code},
            )

        # 解析 JSON-RPC 响应体
        body = response.get("body", {})
        if "error" in body:
            err = body["error"]
            raise TableauMCPError(
                code=err.get("code", "NLQ_006"),
                message=err.get("message", "MCP 返回错误"),
                details=err.get("data", {}),
            )

        result = body.get("result", {})
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 模块级 per-connection_id 访问器（约束 D）
# ─────────────────────────────────────────────────────────────────────────────


def get_tableau_mcp_client(connection_id: int) -> TableauMCPClient:
    """
    获取指定 connection_id 的 TableauMCPClient 实例（约束 D P0 修复）。

    每个 connection_id 对应唯一的 client 实例，禁止跨租户共享。
    """
    return TableauMCPClient(connection_id=connection_id)
