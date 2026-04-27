"""Data Agent Session Context — 丰富的会话级上下文管理

Spec: docs/specs/36-data-agent-architecture-spec.md §3.3 Session Context

提供会话级上下文隔离，包含：
- 用户信息
- 活跃数据源列表
- 对话历史摘要
- 工具执行结果缓存
- 上下文序列化支持

设计目标：
1. 每个会话独立的上下文实例，无跨会话泄漏
2. 上下文随工具调用链流转
3. 支持序列化以便持久化恢复
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class UserInfo:
    """当前用户上下文"""
    user_id: int
    username: str = ""
    role: str = "user"


@dataclass
class DatasourceInfo:
    """活跃数据源信息"""
    connection_id: int
    name: str = ""
    ds_type: str = ""
    is_active: bool = True


@dataclass
class ToolExecutionRecord:
    """工具执行记录（上下文内缓存）"""
    tool_name: str
    params: Dict[str, Any]
    result_summary: str
    success: bool
    execution_time_ms: int
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


@dataclass
class AgentSessionContext:
    """丰富的会话级上下文 — 贯穿整个工具调用链

    每个 agent_stream 请求创建一个实例，确保隔离。

    Attributes:
        session_id: 会话 UUID
        trace_id: 追踪 ID
        user: 当前用户信息
        connection_id: 主连接 ID（可选）
        active_datasources: 可用数据源列表
        conversation_history: 对话历史摘要（最近几轮）
        tool_results: 工具执行结果缓存
        variables: 自由 KV 存储（工具间传递中间数据）
    """
    session_id: str
    trace_id: str
    user: UserInfo
    connection_id: Optional[int] = None
    active_datasources: List[DatasourceInfo] = field(default_factory=list)
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    tool_results: List[ToolExecutionRecord] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

    # ── 工具结果管理 ──────────────────────────────────────────────

    def record_tool_execution(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result_summary: str,
        success: bool,
        execution_time_ms: int,
    ) -> None:
        """记录工具执行结果到上下文"""
        self.tool_results.append(ToolExecutionRecord(
            tool_name=tool_name,
            params=params,
            result_summary=result_summary[:500],  # 截断保护
            success=success,
            execution_time_ms=execution_time_ms,
        ))

    def get_last_tool_result(self, tool_name: Optional[str] = None) -> Optional[ToolExecutionRecord]:
        """获取最近一次工具执行结果（可选按工具名筛选）"""
        if not self.tool_results:
            return None
        if tool_name:
            for record in reversed(self.tool_results):
                if record.tool_name == tool_name:
                    return record
            return None
        return self.tool_results[-1]

    # ── 变量存储（工具间传递中间数据）─────────────────────────────

    def set_variable(self, key: str, value: Any) -> None:
        """设置上下文变量"""
        self.variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """获取上下文变量"""
        return self.variables.get(key, default)

    # ── 对话历史 ─────────────────────────────────────────────────

    def add_conversation_turn(self, role: str, content: str) -> None:
        """添加一轮对话到历史"""
        self.conversation_history.append({
            "role": role,
            "content": content[:1000],  # 截断保护
        })
        # 保留最近 20 轮
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

    # ── 序列化 / 反序列化 ────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict（可 JSON 持久化）"""
        return {
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "user": {
                "user_id": self.user.user_id,
                "username": self.user.username,
                "role": self.user.role,
            },
            "connection_id": self.connection_id,
            "active_datasources": [
                {
                    "connection_id": ds.connection_id,
                    "name": ds.name,
                    "ds_type": ds.ds_type,
                    "is_active": ds.is_active,
                }
                for ds in self.active_datasources
            ],
            "conversation_history": self.conversation_history,
            "tool_results": [
                {
                    "tool_name": r.tool_name,
                    "params": r.params,
                    "result_summary": r.result_summary,
                    "success": r.success,
                    "execution_time_ms": r.execution_time_ms,
                    "timestamp": r.timestamp,
                }
                for r in self.tool_results
            ],
            "variables": self.variables,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSessionContext":
        """从 dict 反序列化"""
        user_data = data.get("user", {})
        user = UserInfo(
            user_id=user_data.get("user_id", 0),
            username=user_data.get("username", ""),
            role=user_data.get("role", "user"),
        )
        ctx = cls(
            session_id=data.get("session_id", ""),
            trace_id=data.get("trace_id", ""),
            user=user,
            connection_id=data.get("connection_id"),
            created_at=data.get("created_at", ""),
        )
        # 恢复数据源列表
        for ds_data in data.get("active_datasources", []):
            ctx.active_datasources.append(DatasourceInfo(
                connection_id=ds_data.get("connection_id", 0),
                name=ds_data.get("name", ""),
                ds_type=ds_data.get("ds_type", ""),
                is_active=ds_data.get("is_active", True),
            ))
        # 恢复对话历史
        ctx.conversation_history = data.get("conversation_history", [])
        # 恢复工具结果
        for r_data in data.get("tool_results", []):
            ctx.tool_results.append(ToolExecutionRecord(
                tool_name=r_data.get("tool_name", ""),
                params=r_data.get("params", {}),
                result_summary=r_data.get("result_summary", ""),
                success=r_data.get("success", False),
                execution_time_ms=r_data.get("execution_time_ms", 0),
                timestamp=r_data.get("timestamp", ""),
            ))
        # 恢复变量
        ctx.variables = data.get("variables", {})
        return ctx

    @classmethod
    def from_json(cls, json_str: str) -> "AgentSessionContext":
        """从 JSON 字符串反序列化"""
        return cls.from_dict(json.loads(json_str))


def build_session_context(
    session_id: str,
    trace_id: str,
    current_user: Dict[str, Any],
    connection_id: Optional[int] = None,
    db=None,
) -> AgentSessionContext:
    """工厂函数 — 从请求参数构建完整的 AgentSessionContext

    Args:
        session_id: 会话 UUID
        trace_id: 追踪 ID
        current_user: 当前用户 dict（来自 get_current_user）
        connection_id: 可选主连接 ID
        db: 可选 SQLAlchemy Session（用于查询活跃数据源）

    Returns:
        AgentSessionContext 实例
    """
    user = UserInfo(
        user_id=current_user.get("id", 0),
        username=current_user.get("username", ""),
        role=current_user.get("role", "user"),
    )

    ctx = AgentSessionContext(
        session_id=session_id,
        trace_id=trace_id,
        user=user,
        connection_id=connection_id,
    )

    # 查询用户可访问的活跃数据源
    if db is not None:
        try:
            from services.datasources.models import DataSource
            query = db.query(DataSource).filter(DataSource.is_active == True)  # noqa: E712
            role = current_user.get("role", "user")
            if role not in ("admin", "data_admin"):
                query = query.filter(DataSource.owner_id == current_user.get("id"))
            datasources = query.limit(50).all()
            for ds in datasources:
                ctx.active_datasources.append(DatasourceInfo(
                    connection_id=ds.id,
                    name=getattr(ds, "name", ""),
                    ds_type=getattr(ds, "ds_type", ""),
                    is_active=True,
                ))
        except Exception as e:
            logger.warning("构建上下文时查询数据源失败: %s", e)

    return ctx
