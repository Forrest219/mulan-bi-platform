"""
Tableau MCP 查询客户端（Stage 3 执行层）— T-R1 重写

PRD §5.5 契约实现：
- 约束 A：环境变量完整性（PAT 解密后注入）→ 移至 MCP server 进程 env（已由官方 server 持有）
- 约束 B：MCP ClientSession 长连接复用（单例模式）→ 重写为 streamable-http + session-id 管理
- 约束 C：VizQL JSON 与字段元数据一致性校验
- 约束 D（新增 P0）：connection_id 贯穿上下文，禁止跨租户 client 缓存

MCP Server 通信：标准 MCP Streamable-HTTP over JSON-RPC 2.0
协议参考：https://modelcontextprotocol.io/specification/2025-06-18
工具实现：@tableau/mcp-server@1.18.1

T-R1 变更摘要：
- 删除自定义 REST 传输（`POST /query-datasource` + `env` 注入）
- 改为标准 MCP 传输：`initialize` → `notifications/initialized` → `tools/call`
- 新增模块级 MCP session 生命周期管理（session-id header、过期重建、DELETE 释放）
- 新增 SSE 解析（`event: message\ndata: {...}`）
- 保留：per-connection_id 实例缓存、contextvars 隔离、OOM 防护、idle 清理、错误码映射
"""
import contextvars
import json
import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

from app.core.crypto import get_tableau_crypto
from services.common.settings import (
    get_tableau_mcp_server_url,
    get_tableau_mcp_protocol_version,
)
from services.tableau.models import TableauConnection, TableauAsset


class _CachedTableauConnection:
    """
    TableauConnection 脱管缓存对象。

    仅保存查询得到的必要属性（原始 Python 类型），不持有 SQLAlchemy Session 引用。
    用于在 Session 关闭后安全访问连接属性，防止 DetachedInstanceError。
    """

    __slots__ = (
        "id", "server_url", "site", "token_name", "token_encrypted",
        "is_active", "last_test_success", "mcp_direct_enabled", "mcp_server_url",
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
        mcp_direct_enabled: bool = False,
        mcp_server_url: str = None,
    ):
        self.id = id
        self.server_url = server_url
        self.site = site
        self.token_name = token_name
        self.token_encrypted = token_encrypted
        self.is_active = is_active
        self.last_test_success = last_test_success
        self.mcp_direct_enabled = mcp_direct_enabled
        self.mcp_server_url = mcp_server_url


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
# 模块级 HTTP Session 管理（约束 B：连接池复用）
# ─────────────────────────────────────────────────────────────────────────────

_http_session_lock = threading.Lock()
_http_session: Optional[requests.Session] = None


def _get_http_session() -> requests.Session:
    """获取共享的 requests.Session（单例）。"""
    global _http_session
    if _http_session is None:
        with _http_session_lock:
            if _http_session is None:
                s = requests.Session()
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=0,  # 重试由上层控制
                )
                s.mount("http://", adapter)
                s.mount("https://", adapter)
                _http_session = s
    return _http_session


# ─────────────────────────────────────────────────────────────────────────────
# 模块级 MCP Session 状态（进程级共享，MVP 单 Tableau Site）
# ─────────────────────────────────────────────────────────────────────────────

class _MCPSessionState:
    """
    MCP session 生命周期状态。

    MVP 约束：所有 connection_id 共享同一个 MCP server 进程，
    因此 session 是进程级共享资源（非 per-connection_id）。
    多租户场景（P2+）改造成 {site → _MCPSessionState} 映射。
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.session_id: Optional[str] = None
        self.last_activity: float = 0.0
        self.last_used: float = time.monotonic()  # LRU 驱逐用（P1）
        self.protocol_version: str = "2025-06-18"
        self._initialized = False

    def reset(self) -> None:
        with self.lock:
            self.session_id = None
            self.last_activity = 0.0
            self._initialized = False


# ─────────────────────────────────────────────────────────────────────────────
# 多站点 MCP Session 状态（P0 改造：per-site 隔离）
# ─────────────────────────────────────────────────────────────────────────────

_mcp_session_states: Dict[str, _MCPSessionState] = {}
_mcp_session_states_lock = threading.Lock()

# 向后兼容别名：原有模块级单例，指向默认站点状态（懒创建）
# 内部函数通过 _get_or_create_session_state 获取正确实例
_mcp_session_state = _MCPSessionState()  # 保留用于向后兼容（_invalidate_session 等）


def _get_site_key(conn) -> str:
    """返回站点唯一键：{server_url}|{site}"""
    server_url = getattr(conn, "server_url", "") or ""
    site = getattr(conn, "site", "") or ""
    return f"{server_url}|{site}"


def _get_or_create_session_state(site_key: str, _max_sites: int = 50) -> _MCPSessionState:
    """
    获取或创建指定 site_key 的 _MCPSessionState，并实现 LRU 驱逐（P1）。

    参数：
        site_key: 由 _get_site_key(conn) 返回的字符串
        _max_sites: 最大站点数，达到上限时驱逐最久未访问的站点（默认 50）

    线程安全：全部操作在 _mcp_session_states_lock 内进行。
    """
    with _mcp_session_states_lock:
        now = time.monotonic()

        # LRU 驱逐：当字典 size >= _max_sites 且 site_key 不在字典中时，驱逐最久未访问的站点
        if _max_sites > 0 and site_key not in _mcp_session_states and len(_mcp_session_states) >= _max_sites:
            # 找到 last_used 最小的（最久未访问）
            lru_key = min(_mcp_session_states, key=lambda k: _mcp_session_states[k].last_used)
            lru_state = _mcp_session_states.pop(lru_key)
            logger.info(
                "_get_or_create_session_state: LRU 驱逐 site_key=%s (last_used=%.1fs ago)",
                lru_key,
                now - lru_state.last_used,
            )
            # 释放 MCP session（非阻塞，驱逐过程中不持有 lru_state.lock）
            try:
                _invalidate_session(session_state=lru_state)
            except Exception as e:
                logger.warning("LRU 驱逐时释放 session 失败（忽略）: %s", e)

        if site_key not in _mcp_session_states:
            _mcp_session_states[site_key] = _MCPSessionState()
            logger.debug("_get_or_create_session_state: 创建新 session_state, site_key=%s", site_key)

        state = _mcp_session_states[site_key]
        state.last_used = now  # 每次访问更新 LRU 时间戳
        return state


# ─────────────────────────────────────────────────────────────────────────────
# MCP Session 管理函数
# ─────────────────────────────────────────────────────────────────────────────

_jsonrpc_id_counter = 0
_id_lock = threading.Lock()


def _next_id() -> int:
    """生成自增 JSON-RPC id（线程安全）。"""
    global _jsonrpc_id_counter
    with _id_lock:
        _jsonrpc_id_counter += 1
        return _jsonrpc_id_counter


def _build_headers(
    with_session: bool = True,
    session_state: Optional[_MCPSessionState] = None,
    jwt_token: Optional[str] = None,
) -> Dict[str, str]:
    """
    构建 MCP HTTP 请求头。

    参数：
        with_session: 是否附加 mcp-session-id
        session_state: 指定 session 状态实例（默认使用全局 _mcp_session_state）
        jwt_token: Tableau Connected Apps JWT（非 None 时注入 Authorization: Bearer，
                   以用户身份发起请求，替代 MCP server 全局 PAT）
    """
    state = session_state if session_state is not None else _mcp_session_state
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": state.protocol_version,
    }
    if with_session and state.session_id:
        headers["mcp-session-id"] = state.session_id
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"
    return headers


def _parse_sse(response_text: str) -> Dict[str, Any]:
    """
    解析 SSE 响应体。

    MCP streamable-http 响应格式：
        event: message
        data: {"jsonrpc":"2.0","id":1,"result":{...}}

    规则：
        1. 按行分割
        2. 找 "data: " 开头的行（注意空格）
        3. 剥前缀，json.loads
        4. 多 data 行时用 \\n 连接（MCP 允许多行；Tableau server 目前单行足够）
    """
    lines = response_text.split("\n")
    data_lines = [
        line[6:] for line in lines
        if line.startswith("data: ")
    ]
    if not data_lines:
        raise TableauMCPError(
            code="NLQ_006",
            message="MCP SSE 响应无 data 字段",
            details={"raw": response_text[:500]},
        )
    payload = "\n".join(data_lines)
    return json.loads(payload)


def _post_mcp(
    payload: Dict[str, Any],
    method: str,
    timeout: int = 30,
    expect_sse: bool = True,
    session_state: Optional[_MCPSessionState] = None,
    base_url: Optional[str] = None,
    jwt_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    发送 MCP JSON-RPC 请求，返回解析后的响应体。

    参数：
        method: 用于日志的 MCP method 名（如 "initialize"）
        timeout: 请求超时秒数
        expect_sse: 是否解析 SSE 响应（False 用于 initialize 握手）
        session_state: 指定 session 状态实例（默认使用全局 _mcp_session_state）
        base_url: MCP server URL（优先用参数值，fallback 到全局配置）
        jwt_token: Tableau Connected Apps JWT（非 None 时以用户身份发请求，替代全局 PAT）

    重试策略：
        - 网络错误 / 5xx：重试 1 次，间隔 1s
        - 4xx：不重试
        - session 过期（HTTP 400 + "No valid session ID"）：由调用方处理（_ensure_session）
    """
    url = base_url if base_url else get_tableau_mcp_server_url()
    headers = _build_headers(with_session=True, session_state=session_state, jwt_token=jwt_token)
    last_error: Optional[Exception] = None

    for attempt in range(2):
        try:
            resp = _get_http_session().post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            # Session 过期检测：HTTP 400 + "No valid session ID"
            if resp.status_code == 400 and "No valid session ID" in resp.text:
                # 抛出特殊标记，让 _ensure_session 处理
                raise _SessionExpiredError("Session expired or invalid")

            if resp.status_code >= 500 and attempt == 0:
                time.sleep(1)
                continue
            if resp.status_code >= 400:
                raise TableauMCPError(
                    code="NLQ_006",
                    message=f"MCP 请求失败（HTTP {resp.status_code}）",
                    details={"method": method, "status_code": resp.status_code},
                )

            if expect_sse:
                return _parse_sse(resp.text)
            else:
                # initialize 响应也是 SSE，但格式更简单
                try:
                    return _parse_sse(resp.text)
                except (json.JSONDecodeError, TableauMCPError):
                    # 某些 server 实现在 initialize 成功时返回空或纯文本
                    logger.debug("initialize 响应非标准 SSE: %s", resp.text[:200])
                    return {}

        except _SessionExpiredError:
            raise  # 不重试，直接让调用方处理
        except requests.exceptions.Timeout:
            raise TableauMCPError(
                code="NLQ_007",
                message=f"MCP 查询超时（{timeout}s）",
                details={"method": method, "timeout": timeout},
            )
        except TableauMCPError:
            raise  # 已构造好，直接透传
        except Exception as e:
            last_error = e
            if attempt == 0:
                time.sleep(1)
                continue
            logger.error("MCP 请求异常（%s）: %s", method, e)

    # 两次尝试均失败
    raise TableauMCPError(
        code="NLQ_006",
        message=f"MCP 服务不可用（{method}）",
        details={"method": method, "error": str(last_error)},
    )


class _SessionExpiredError(Exception):
    """Session 过期标记（不在外层重试，由 _ensure_session 内部重建）"""
    pass


def _ensure_session(
    timeout: int = 30,
    site_key: Optional[str] = None,
    base_url: Optional[str] = None,
    session_state: Optional[_MCPSessionState] = None,
    jwt_token: Optional[str] = None,
) -> str:
    """
    确保 MCP session 已建立。

    流程：
        1. 若 session 已活跃（last_activity < 5min），直接返回 session_id
        2. 若未初始化或过期，发起 initialize + notifications/initialized
        3. 收到 session 过期 HTTP 400，清空 session_id 后重建

    参数：
        timeout: 超时秒数
        site_key: 站点唯一键（多站点改造，P0 新增）
        base_url: MCP Server URL（优先用参数值，fallback 到全局配置）
        session_state: 指定 session 状态实例（默认使用全局 _mcp_session_state）
        jwt_token: Tableau Connected Apps JWT（非 None 时以用户身份发起握手，替代全局 PAT）

    返回：
        有效的 session_id

    线程安全（自旋锁保护）。
    """
    state = session_state if session_state is not None else _mcp_session_state
    protocol_ver = get_tableau_mcp_protocol_version()
    now = time.monotonic()
    idle_timeout = 300  # 5 分钟，与 _IDLE_TIMEOUT 保持一致
    effective_url = base_url if base_url else get_tableau_mcp_server_url()

    with state.lock:
        # 检查活跃 session
        if (
            state.session_id
            and state._initialized
            and (now - state.last_activity) < idle_timeout
        ):
            return state.session_id

        # 重置状态，触发完整初始化（inline 而非调用 reset() 避免重入锁死锁）
        state.session_id = None
        state.last_activity = 0.0
        state._initialized = False
        state.protocol_version = protocol_ver

    headers_base = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_ver,
    }
    if jwt_token:
        headers_base["Authorization"] = f"Bearer {jwt_token}"

    # Step 1: initialize
    init_payload = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "initialize",
        "params": {
            "protocolVersion": protocol_ver,
            "capabilities": {},
            "clientInfo": {
                "name": "mulan-bi-mcp-client",
                "version": "1.0.0",
            },
        },
    }

    resp = _get_http_session().post(
        effective_url,
        json=init_payload,
        headers=headers_base,
        timeout=timeout,
    )

    if resp.status_code == 400 and "No valid session ID" in resp.text:
        raise TableauMCPError(
            code="NLQ_006",
            message="MCP initialize 失败：session 初始化被拒绝",
            details={"status_code": resp.status_code, "body": resp.text[:200]},
        )

    if resp.status_code >= 400:
        raise TableauMCPError(
            code="NLQ_006",
            message=f"MCP initialize 失败（HTTP {resp.status_code}）",
            details={"status_code": resp.status_code},
        )

    # 抽取 session_id 从响应 header
    session_id = None
    for k, v in resp.headers.items():
        if k.lower() == "mcp-session-id":
            session_id = v
            break

    if not session_id:
        # 某些实现可能把 session_id 放 body 里
        try:
            body = json.loads(resp.text)
            session_id = body.get("sessionId") or body.get("session_id")
        except (json.JSONDecodeError, Exception):
            pass

    if not session_id:
        raise TableauMCPError(
            code="NLQ_006",
            message="MCP initialize 成功但响应中无 session-id",
            details={"body": resp.text[:500]},
        )

    # Step 2: notifications/initialized（告知 server 端握手完成）
    notif_payload = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "notifications/initialized",
        "params": {},
    }
    notif_headers = {
        **headers_base,
        "mcp-session-id": session_id,
    }
    # notifications/initialized 期望 202 Accepted，server 不返回 body
    try:
        notif_resp = _get_http_session().post(
            effective_url,
            json=notif_payload,
            headers=notif_headers,
            timeout=timeout,
        )
        logger.debug("notifications/initialized 响应: %d %s", notif_resp.status_code, notif_resp.text[:200])
    except Exception as e:
        logger.warning("notifications/initialized 失败（不影响主流程）: %s", e)

    # 写入状态
    with state.lock:
        state.session_id = session_id
        state.last_activity = time.monotonic()
        state._initialized = True

    site_info = f" site_key={site_key}" if site_key else ""
    logger.info("MCP session 建立成功，session_id=%s%s", session_id[:16] + "...", site_info)
    return session_id


def _invalidate_session(
    session_state: Optional[_MCPSessionState] = None,
    base_url: Optional[str] = None,
) -> None:
    """
    主动释放 MCP session（发 DELETE，然后清状态）。

    参数：
        session_state: 指定 session 状态实例（默认使用全局 _mcp_session_state）
        base_url: MCP Server URL（优先用参数值，fallback 到全局配置）
    """
    state = session_state if session_state is not None else _mcp_session_state
    session_id = state.session_id
    if not session_id:
        state.reset()
        return

    effective_url = base_url if base_url else get_tableau_mcp_server_url()
    headers = _build_headers(with_session=True, session_state=state)

    try:
        resp = _get_http_session().delete(
            effective_url,
            headers=headers,
            timeout=10,
        )
        logger.debug("MCP DELETE session 响应: %d %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("MCP DELETE session 失败（非致命）: %s", e)
    finally:
        state.reset()


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
    Tableau MCP 查询客户端（per-user session 模式，T-R1 架构决策）。

    核心 invariant：每个 (username, connection_id) 组合对应唯一 client 实例，
    禁止跨用户共享（防止高并发下数据串签）。LRU 容量 50，与 Spec 14 §V2 保持一致。

    使用方式：
        client = get_tableau_mcp_client(username="alice", connection_id=conn_id)
        result = client.query_datasource(datasource_luid, vizql_json, connection_id=conn_id, timeout=30)

    T-R1 变更：传输层从自定义 REST 改为标准 MCP streamable-http。
    MCP session 是进程级共享资源（所有用户共用，按 site_key 隔离）。
    client 对象按 (username, connection_id) 隔离，确保 _ds_connection_cache 不跨用户混用。
    """

    # 按 (username, connection_id) 隔离的 client 实例缓存（LRU 容量 50）
    _instances: Dict[tuple, "TableauMCPClient"] = {}
    _instances_lock = threading.Lock()
    _MAX_INSTANCES = 50   # per-user LRU 容量，与 Spec 14 §V2 保持一致
    _IDLE_TIMEOUT = 300   # 5 分钟空闲超时
    _last_access: Dict[tuple, float] = {}

    @classmethod
    def cleanup_idle(cls) -> int:
        """清理空闲超过 _IDLE_TIMEOUT 的实例。返回清理数量。"""
        now = time.monotonic()
        removed = 0
        with cls._instances_lock:
            expired = [
                key for key, ts in cls._last_access.items()
                if now - ts > cls._IDLE_TIMEOUT
            ]
            for key in expired:
                cls._instances.pop(key, None)
                cls._last_access.pop(key, None)
                removed += 1
        if removed:
            logger.info("cleanup_idle: 清理 %d 个空闲 MCP client 实例", removed)
        return removed

    @classmethod
    def invalidate(cls, connection_id: int, username: Optional[str] = None) -> None:
        """
        主动失效指定连接的 client 实例。

        若指定 username，只清除该用户的实例；否则清除该 connection_id 下所有用户实例。
        """
        with cls._instances_lock:
            if username is not None:
                key = (username, connection_id)
                cls._instances.pop(key, None)
                cls._last_access.pop(key, None)
            else:
                # 清除该 connection_id 下所有用户实例
                keys_to_remove = [k for k in cls._instances if k[1] == connection_id]
                for k in keys_to_remove:
                    cls._instances.pop(k, None)
                    cls._last_access.pop(k, None)

    def __new__(cls, connection_id: int, username: str = "") -> "TableauMCPClient":
        cache_key = (username, connection_id)
        with cls._instances_lock:
            now = time.monotonic()
            # 空闲清理
            expired = [
                k for k, ts in cls._last_access.items()
                if now - ts > cls._IDLE_TIMEOUT
            ]
            for k in expired:
                cls._instances.pop(k, None)
                cls._last_access.pop(k, None)
            if expired:
                logger.info("__new__: 清理 %d 个空闲实例", len(expired))

            # LRU 驱逐：超过容量时驱逐最久未访问的实例
            if len(cls._instances) >= cls._MAX_INSTANCES and cache_key not in cls._instances:
                lru_key = min(cls._last_access, key=cls._last_access.__getitem__)
                cls._instances.pop(lru_key, None)
                cls._last_access.pop(lru_key, None)
                logger.info(
                    "__new__: LRU 驱逐 key=%s (username=%s, connection_id=%s)",
                    lru_key, lru_key[0], lru_key[1],
                )

            if cache_key not in cls._instances:
                cls._instances[cache_key] = super().__new__(cls)
            cls._last_access[cache_key] = now
        return cls._instances[cache_key]

    def __init__(self, connection_id: int, username: str = ""):
        cache_key = (username, connection_id)
        if (
            getattr(self, "_initialized", False)
            and getattr(self, "_cache_key", None) == cache_key
        ):
            return
        self._initialized = True
        self._cache_key = cache_key
        self._connection_id = connection_id
        self._username = username
        self._session = _get_http_session()
        self._ds_connection_cache: Dict[str, "TableauConnection|_CachedTableauConnection"] = {}
        self._MAX_CACHE_SIZE = 500

    def _get_connection_by_luid(
        self, datasource_luid: str, connection_id: int,
    ) -> "TableauConnection|_CachedTableauConnection":
        """通过 datasource_luid 查找对应的 TableauConnection（带内存缓存）。"""
        cache_key = f"{connection_id}:{datasource_luid}"
        if cache_key in self._ds_connection_cache:
            return self._ds_connection_cache[cache_key]

        from app.core.database import SessionLocal
        session = SessionLocal()
        conn = None
        try:
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

            conn_attrs = {
                "id": conn.id,
                "server_url": conn.server_url,
                "site": conn.site,
                "token_name": conn.token_name,
                "token_encrypted": conn.token_encrypted,
                "is_active": conn.is_active,
                "last_test_success": conn.last_test_success,
                "mcp_direct_enabled": getattr(conn, "mcp_direct_enabled", False),
                "mcp_server_url": getattr(conn, "mcp_server_url", None),
            }
        finally:
            session.close()

        if len(self._ds_connection_cache) >= self._MAX_CACHE_SIZE:
            keys_to_remove = list(self._ds_connection_cache.keys())[: len(self._ds_connection_cache) // 2]
            for k in keys_to_remove:
                del self._ds_connection_cache[k]
            logger.warning("连接缓存超限，已清理 %d 条旧缓存", len(keys_to_remove))

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
        jwt_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        通过 Tableau MCP 查询数据源（标准 MCP tools/call）。

        参数：
            datasource_luid: Tableau 数据源 LUID
            query: VizQL 查询 JSON（符合 PRD §5.5.2 格式）
            limit: 最大返回行数（默认 1000）
            timeout: 超时秒数（默认 30）
            connection_id: 租户连接 ID（必填，约束 D）
            jwt_token: Tableau Connected Apps JWT（非 None 时以用户身份发请求，
                       注入 Authorization: Bearer header，替代全局 PAT）

        返回：
            {"fields": [...], "rows": [[...], ...]}（符合 PRD §5.5.3 格式）

        异常：
            TableauMCPError: NLQ_006 / NLQ_007 / NLQ_009 / MCP_010

        T-R1 变更：调用标准 MCP tools/call 接口，session 生命周期由模块级管理。
        PAT 不再通过 env 注入（由 MCP server 进程持有）。
        """
        if connection_id is None:
            raise TableauMCPError(
                code="NLQ_009",
                message="connection_id 为必填参数（MCP 查询禁止空上下文）",
                details={"datasource_luid": datasource_luid},
            )

        token = _connection_id_var.set(connection_id)
        try:
            conn = self._get_connection_by_luid(datasource_luid, connection_id)

            # 校验连接可用性
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

            # 校验 V2 直连开关
            if not getattr(conn, "mcp_direct_enabled", False):
                raise TableauMCPError(
                    code="MCP_010",
                    message="连接未开启 V2 直连模式，请使用 V1 API",
                    details={"connection_id": connection_id},
                )

            # 多站点 session 路由（P0 改造）
            site_key = _get_site_key(conn)
            session_state = _get_or_create_session_state(site_key)
            # base_url：优先 conn.mcp_server_url，fallback 到全局配置
            effective_base_url = getattr(conn, "mcp_server_url", None) or None

            # 组装 MCP tools/call 请求（limit 在 arguments 顶层，verified by tools/list）
            payload = self._build_jsonrpc_request(
                datasource_luid=datasource_luid,
                query=query,
                limit=limit,
            )

            # 发送并处理响应（含 session 过期自动重建）
            response = self._send_jsonrpc(
                payload,
                timeout=timeout,
                site_key=site_key,
                session_state=session_state,
                base_url=effective_base_url,
                jwt_token=jwt_token,
            )

            return self._parse_jsonrpc_response(response)
        finally:
            _connection_id_var.reset(token)

    def list_datasources(
        self,
        limit: int = 50,
        timeout: int = 30,
        connection_id: Optional[int] = None,
        jwt_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        通过 Tableau MCP 列出可用的数据源（用于动态数据源发现）。

        当本地 TableauAsset 表为空时，NLQ 路由层调用此方法通过 MCP 动态发现数据源。

        参数：
            limit: 最大返回条数（默认 50）
            timeout: 超时秒数（默认 30）
            connection_id: 指定 Tableau 连接 ID（None 时取第一条活跃连接，向后兼容）
            jwt_token: Tableau Connected Apps JWT（非 None 时以用户身份发请求，替代全局 PAT）

        返回：
            {"datasources": [{"luid": "...", "name": "..."}, ...]}
        """
        from services.tableau.models import TableauConnection as _TableauConnection

        db = TableauDatabase()
        session = db.session
        try:
            query_filter = session.query(_TableauConnection).filter(
                _TableauConnection.is_active == True,
            )
            if connection_id is not None:
                query_filter = query_filter.filter(_TableauConnection.id == connection_id)
            conn_record = query_filter.order_by(_TableauConnection.id.asc()).first()

            if not conn_record:
                raise TableauMCPError(
                    code="NLQ_009",
                    message="无活跃的 Tableau 连接",
                    details={"connection_id": connection_id},
                )
        finally:
            session.close()

        token = _connection_id_var.set(conn_record.id)
        try:
            site_key = _get_site_key(conn_record)
            session_state = _get_or_create_session_state(site_key)
            effective_base_url = getattr(conn_record, "mcp_server_url", None) or None

            # 尝试调用 list_datasources 工具
            payload = {
                "jsonrpc": "2.0",
                "id": _next_id(),
                "method": "tools/call",
                "params": {
                    "name": "list_datasources",
                    "arguments": {"limit": limit},
                },
            }

            response = self._send_jsonrpc(
                payload,
                timeout=timeout,
                site_key=site_key,
                session_state=session_state,
                base_url=effective_base_url,
                jwt_token=jwt_token,
            )

            parsed = self._parse_jsonrpc_response(response)
            # 标准化返回格式
            content = parsed.get("content", [])
            text = _extract_text(content)
            if text:
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and "datasources" in data:
                        return data
                except json.JSONDecodeError:
                    pass
            # 如果解析失败，返回原始内容
            return {"datasources": [], "raw": parsed}
        finally:
            _connection_id_var.reset(token)

    def get_datasource_metadata(self, datasource_luid: str, timeout: int = 30) -> Dict[str, Any]:
        """
        通过 Tableau MCP 获取数据源的字段元数据（用于 NLQ 动态数据源发现）。

        当本地 TableauAsset 表无数据时，NLQ 路由层先调用 list_datasources 发现数据源，
        再调用此方法获取字段信息，构建 LLM prompt。

        返回：
            {"fields": [{"name": "...", "dataType": "...", "role": "..."}, ...]}
        """
        from services.tableau.models import TableauConnection as _TableauConnection

        db = TableauDatabase()
        session = db.session
        try:
            conn_record = session.query(_TableauConnection).filter(
                _TableauConnection.is_active == True,
            ).order_by(_TableauConnection.id.asc()).first()

            if not conn_record:
                raise TableauMCPError(
                    code="NLQ_009",
                    message="无活跃的 Tableau 连接",
                    details={},
                )
        finally:
            session.close()

        token = _connection_id_var.set(conn_record.id)
        try:
            site_key = _get_site_key(conn_record)
            session_state = _get_or_create_session_state(site_key)
            effective_base_url = getattr(conn_record, "mcp_server_url", None) or None

            # 调用 get-datasource-metadata 工具
            payload = {
                "jsonrpc": "2.0",
                "id": _next_id(),
                "method": "tools/call",
                "params": {
                    "name": "get-datasource-metadata",
                    "arguments": {"datasourceLuid": datasource_luid},
                },
            }

            response = self._send_jsonrpc(
                payload,
                timeout=timeout,
                site_key=site_key,
                session_state=session_state,
                base_url=effective_base_url,
            )

            parsed = self._parse_jsonrpc_response(response)
            content = parsed.get("content", [])
            text = _extract_text(content)
            if text:
                try:
                    data = json.loads(text)
                    return data
                except json.JSONDecodeError:
                    pass
            return {"fields": [], "raw": parsed}
        finally:
            _connection_id_var.reset(token)

    # ─────────────────────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────────────────────

    def _decrypt_pat(self, conn) -> str:
        """解密 PAT Secret（为多租户预留，本次 MVP 不调用）。"""
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
    ) -> dict:
        """
        组装 MCP tools/call JSON-RPC 请求。

        T-R1：使用标准 MCP method "tools/call"，
        替代旧版自定义 REST "query-datasource"。
        注意：PAT 不再通过 env 字段注入，由 MCP server 进程 env 持有。
        """
        return {
            "jsonrpc": "2.0",
            "id": _next_id(),
            "method": "tools/call",
            "params": {
                "name": "query-datasource",
                "arguments": {
                    "datasourceLuid": datasource_luid,
                    "query": query,
                    "limit": limit,
                },
            },
        }

    def _send_jsonrpc(
        self,
        payload: dict,
        timeout: int,
        site_key: Optional[str] = None,
        session_state: Optional[_MCPSessionState] = None,
        base_url: Optional[str] = None,
        jwt_token: Optional[str] = None,
    ) -> dict:
        """
        发送 MCP JSON-RPC 请求（内部处理 session 生命周期）。

        参数：
            payload: JSON-RPC 请求体
            timeout: 超时秒数
            site_key: 站点唯一键（多站点改造，P0 新增）
            session_state: 指定 session 状态实例（默认使用全局 _mcp_session_state）
            base_url: MCP Server URL（优先用参数值，fallback 到全局配置）
            jwt_token: Tableau Connected Apps JWT（非 None 时以用户身份发请求，替代全局 PAT）

        重试策略：
            - 网络错误 / 5xx：重试 1 次，间隔 1s
            - 4xx：不重试
            - session 过期：自动重建 session + 重试 1 次（不计入外层重试）
        """
        state = session_state if session_state is not None else _mcp_session_state
        method = payload.get("method", "unknown")

        for attempt in range(2):
            try:
                # 确保 session 已建立（懒加载）
                _ensure_session(timeout=timeout, site_key=site_key, base_url=base_url, session_state=state, jwt_token=jwt_token)

                # 更新最后活跃时间（每次成功建立 session 后）
                with state.lock:
                    state.last_activity = time.monotonic()

                return _post_mcp(payload, method=method, timeout=timeout, expect_sse=True, session_state=state, base_url=base_url, jwt_token=jwt_token)

            except _SessionExpiredError:
                # Session 过期：清空并重建，不计入外层重试
                logger.warning("MCP session 过期，尝试重建: %s", method)
                state.reset()
                _ensure_session(timeout=timeout, site_key=site_key, base_url=base_url, session_state=state, jwt_token=jwt_token)
                with state.lock:
                    state.last_activity = time.monotonic()
                # 重试 1 次（这次用新 session）
                return _post_mcp(payload, method=method, timeout=timeout, expect_sse=True, session_state=state, base_url=base_url, jwt_token=jwt_token)

            except TableauMCPError:
                raise  # 已构造好，直接透传

    def _parse_jsonrpc_response(self, body: dict) -> dict:
        """
        解析 MCP tools/call JSON-RPC 响应。

        MCP 协议下 query-datasource 的响应结构：
            {
              "jsonrpc": "2.0",
              "id": N,
              "result": {
                "content": [{"type": "text", "text": "{\"fields\":[...],\"rows\":[[...]]}"}],
                "isError": false
              }
            }

        映射到 PRD §5.5.3 契约：
            - content[0].text 是 Tableau 返回的 JSON 字符串（fields + rows）
            - 解析该 JSON 返回 {"fields": [...], "rows": [[...], ...]}
        """
        if "error" in body:
            err = body["error"]
            raise TableauMCPError(
                code=_map_mcp_error(err.get("code")),
                message=err.get("message", "MCP 返回错误"),
                details=err.get("data", {}),
            )

        result = body.get("result", {})

        # tools/call 的工具级错误走 isError + content
        if result.get("isError"):
            error_text = _extract_text(result.get("content", []))
            raise TableauMCPError(
                code="NLQ_006",
                message=f"MCP 工具执行失败: {error_text[:200]}",
                details={"tool": "query-datasource", "raw": error_text[:500]},
            )

        content = result.get("content", [])
        text_payload = _extract_text(content)

        try:
            data = json.loads(text_payload)
        except json.JSONDecodeError as e:
            raise TableauMCPError(
                code="NLQ_006",
                message="query-datasource 返回非 JSON 文本",
                details={"raw": text_payload[:500], "json_error": str(e)},
            )

        # data 期望结构 {"fields": [...], "rows": [[...]]}
        if not isinstance(data, dict):
            raise TableauMCPError(
                code="NLQ_006",
                message="query-datasource 返回值不是对象",
                details={"type": type(data).__name__},
            )
        return data


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _extract_text(content: list) -> str:
    """从 MCP content[] 数组中提取 text 类型的值（拼接，兼容多段）。"""
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "".join(parts)


def _map_mcp_error(code: Any) -> str:
    """
    将 MCP 错误码映射为 NLQ 系列错误码。

    规则：
        - Tableau/LLM 相关错误 → NLQ_006
        - 权限/不存在 → NLQ_009
        - 其他 → NLQ_006
    """
    if code is None:
        return "NLQ_006"
    code_str = str(code)
    # 常见 VizQL 错误码
    if code_str in ("forbidden", "unauthorized") or code == 403:
        return "NLQ_009"
    if code_str in ("not_found", "notexists") or code == 404:
        return "NLQ_009"
    # Tableau VizQL 特定错误
    if code_str.startswith("VIZQL_") or code_str.startswith("VIZQL-"):
        return "NLQ_006"
    return "NLQ_006"


# ─────────────────────────────────────────────────────────────────────────────
# 模块级 per-connection_id 访问器（约束 D）
# ─────────────────────────────────────────────────────────────────────────────

def get_tableau_mcp_client(
    connection_id: int,
    username: str = "",
) -> TableauMCPClient:
    """
    获取指定 (username, connection_id) 的 TableauMCPClient 实例（T-R1 per-user session）。

    每个 (username, connection_id) 组合对应唯一 client 实例，禁止跨用户共享。
    LRU 容量 50，符合 Spec 14 §V2 规范。

    参数：
        connection_id: Tableau 连接 ID（租户隔离）
        username: 当前用户名（用户隔离，空字符串表示匿名/系统调用）
    """
    return TableauMCPClient(connection_id=connection_id, username=username)
