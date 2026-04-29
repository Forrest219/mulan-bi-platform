"""
MCP→Tableau 反向同步处理器

Spec 32 v1.1: 当 MCP 配置变更时自动更新 tableau_connections

架构红线：
- 本模块不得 import app/api
- 反向同步只 UPDATE，禁止 INSERT
- emit_event 必须在 commit 之后
- name 字段不可更新
- token_encrypted 必须经 Fernet 加密
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

from sqlalchemy.orm import Session

from app.core.crypto import get_tableau_crypto
from services.events import emit_event
from services.events.constants import (
    BrgErrorCode,
    BRG_ERROR_MESSAGES,
    MCP_SERVER_CHANGED,
    MCP_SERVER_DELETED,
    SOURCE_MODULE_MCP,
    SOURCE_MODULE_TABLEAU,
    TABLEAU_CONNECTION_DEACTIVATED_BY_MCP_DELETE,
    TABLEAU_CONNECTION_RENAMED,
    TABLEAU_CONNECTION_SYNC_SKIPPED,
    TABLEAU_CONNECTION_SYNCED_FROM_MCP,
)
from services.tableau.models import TableauDatabase

logger = logging.getLogger(__name__)


# === 错误码常量（供外部使用）===
BRG_004 = BrgErrorCode.REVERSE_SYNC_NOT_FOUND
BRG_005 = BrgErrorCode.REVERSE_SYNC_FERNET_FAILED
BRG_006 = BrgErrorCode.REVERSE_SYNC_OCC_CONFLICT
BRG_007 = BrgErrorCode.REVERSE_SYNC_NOT_SUBSCRIBED


@dataclass
class SyncReport:
    """反向同步结果报告"""
    mcp_id: int
    target_connection_id: Optional[int]
    fields_synced: List[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None
    elapsed_ms: int = 0


class ReverseSyncHandler:
    """
    MCP→Tableau 反向同步处理器

    订阅 mcp.server.changed 和 mcp.server.deleted 事件，
    自动同步更新对应的 tableau_connections 记录。
    """

    # 类级事件订阅标记（启动自检用）
    _subscribed: bool = False

    def __init__(self):
        self._event_handlers: Dict[str, Callable] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        """注册事件处理器"""
        self._event_handlers = {
            MCP_SERVER_CHANGED: self.on_mcp_changed,
            MCP_SERVER_DELETED: self.on_mcp_deleted,
        }
        ReverseSyncHandler._subscribed = True

    def on_mcp_changed(
        self,
        db: Session,
        mcp_id: int,
        change_type: str,
        fields_changed: List[str],
        mcp_name: Optional[str] = None,
        mcp_snapshot: Optional[Dict[str, Any]] = None,
        actor_id: Optional[int] = None,
    ) -> SyncReport:
        """
        处理 MCP Server 变更事件

        Args:
            db: SQLAlchemy Session
            mcp_id: MCP Server ID
            change_type: 'update' | 'activate' | 'deactivate'
            fields_changed: 变更字段列表
            mcp_name: MCP Server 名称（用于定位 tableau_connection）
            mcp_snapshot: 变更后的完整快照
            actor_id: 操作者 ID

        Returns:
            SyncReport: 同步结果报告
        """
        start_time = time.monotonic()
        report = SyncReport(mcp_id=mcp_id, target_connection_id=None)

        if not mcp_name:
            report.skipped = True
            report.skip_reason = "mcp_name missing"
            report.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(
                "ReverseSync: mcp_id=%d missing mcp_name, skipped", mcp_id
            )
            return report

        # 字段映射：mcp_servers.credentials → tableau_connections
        update_fields: Dict[str, Any] = {}

        if mcp_snapshot:
            creds = mcp_snapshot.get("credentials") or {}

            # pat_value → token_encrypted（需要 Fernet 加密）
            if "pat_value" in fields_changed or "credentials" in fields_changed:
                pat_value = creds.get("pat_value")
                if pat_value:
                    try:
                        fernet = get_tableau_crypto()
                        token_encrypted = fernet.encrypt(pat_value)
                        update_fields["token_encrypted"] = token_encrypted
                    except Exception as e:
                        logger.error(
                            "ReverseSync: Fernet encryption failed for mcp_id=%d: %s",
                            mcp_id,
                            e,
                        )
                        # BRG_005: Fernet 加密失败，但其他字段照常更新
                        # 不抛出异常，记录错误码
                        pass

            # tableau_server → server_url
            if "tableau_server" in fields_changed or "credentials" in fields_changed:
                server_url = creds.get("tableau_server")
                if server_url:
                    update_fields["server_url"] = server_url

            # site_name → site
            if "site_name" in fields_changed or "credentials" in fields_changed:
                site_name = creds.get("site_name")
                if site_name is not None:
                    update_fields["site"] = site_name

            # pat_name → token_name
            if "pat_name" in fields_changed or "credentials" in fields_changed:
                pat_name = creds.get("pat_name")
                if pat_name:
                    update_fields["token_name"] = pat_name

        # is_active 变更
        if "is_active" in fields_changed:
            if mcp_snapshot:
                update_fields["is_active"] = mcp_snapshot.get("is_active", True)

        # name 变更特殊处理：不更新 tableau_connections.name
        # 触发"旧停+新建"流程（由正向桥接处理）
        if "name" in fields_changed:
            # 找到旧名对应的连接，标记为 inactive
            old_name = mcp_snapshot.get("old_name") if mcp_snapshot else None
            new_name = mcp_snapshot.get("name") if mcp_snapshot else None

            if old_name and new_name and old_name != new_name:
                # 标记旧连接 inactive（如果存在）
                tableau_db = TableauDatabase()
                old_conn = tableau_db.get_connection_by_name_and_type(old_name, "mcp")
                if old_conn:
                    old_conn.is_active = False
                    db.commit()

                    # 发送重命名事件
                    emit_event(
                        db=db,
                        event_type=TABLEAU_CONNECTION_RENAMED,
                        source_module=SOURCE_MODULE_TABLEAU,
                        payload={
                            "mcp_id": mcp_id,
                            "old_name": old_name,
                            "new_name": new_name,
                            "old_connection_id": old_conn.id,
                        },
                        actor_id=actor_id,
                    )
                    logger.info(
                        "ReverseSync: marked old connection '%s' inactive for rename to '%s'",
                        old_name,
                        new_name,
                    )
                # 新名连接由正向桥接创建
                report.skipped = True
                report.skip_reason = "name_changed_pending_bridge"
                report.elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return report

        if not update_fields:
            report.skipped = True
            report.skip_reason = "no_syncable_fields"
            report.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return report

        # 执行更新（带 OCC 重试）
        max_retries = 3
        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                tableau_db = TableauDatabase(session=db)
                changed, connection = tableau_db.update_connection_from_mcp(
                    db=db,
                    name=mcp_name,
                    fields=update_fields,
                    actor_id=actor_id,
                )

                if not connection:
                    # BRG_004: 找不到对应连接
                    report.skipped = True
                    report.skip_reason = BRG_ERROR_MESSAGES[BRG_004]
                    report.elapsed_ms = int((time.monotonic() - start_time) * 1000)

                    # 发送 sync_skipped 事件（不抛异常）
                    emit_event(
                        db=db,
                        event_type=TABLEAU_CONNECTION_SYNC_SKIPPED,
                        source_module=SOURCE_MODULE_TABLEAU,
                        payload={
                            "mcp_id": mcp_id,
                            "reason": report.skip_reason,
                            "error_code": BRG_004,
                        },
                        actor_id=actor_id,
                    )
                    logger.warning(
                        "ReverseSync: connection not found for mcp_name='%s', mcp_id=%d",
                        mcp_name,
                        mcp_id,
                    )
                    return report

                if changed:
                    # 发送 synced_from_mcp 事件（commit 后）
                    emit_event(
                        db=db,
                        event_type=TABLEAU_CONNECTION_SYNCED_FROM_MCP,
                        source_module=SOURCE_MODULE_TABLEAU,
                        payload={
                            "mcp_id": mcp_id,
                            "connection_id": connection.id,
                            "fields_synced": list(update_fields.keys()),
                        },
                        actor_id=actor_id,
                    )
                    logger.info(
                        "ReverseSync: synced %d fields from mcp_id=%d to connection_id=%d",
                        len(update_fields),
                        mcp_id,
                        connection.id,
                    )

                report.target_connection_id = connection.id
                report.fields_synced = list(update_fields.keys())
                report.elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return report

            except Exception as e:
                retry_count += 1
                last_error = e
                logger.warning(
                    "ReverseSync: UPDATE conflict (attempt %d/%d) for mcp_id=%d: %s",
                    retry_count,
                    max_retries,
                    mcp_id,
                    e,
                )
                # OCC 冲突时回滚并重试
                db.rollback()

        # BRG_006: OCC 冲突重试耗尽
        logger.error(
            "ReverseSync: OCC conflict exhausted for mcp_id=%d after %d retries",
            mcp_id,
            max_retries,
        )
        report.skipped = True
        report.skip_reason = BRG_ERROR_MESSAGES[BRG_006]
        report.elapsed_ms = int((time.monotonic() - start_time) * 1000)

        emit_event(
            db=db,
            event_type=TABLEAU_CONNECTION_SYNC_SKIPPED,
            source_module=SOURCE_MODULE_TABLEAU,
            payload={
                "mcp_id": mcp_id,
                "reason": report.skip_reason,
                "error_code": BRG_006,
            },
            actor_id=actor_id,
        )
        return report

    def on_mcp_deleted(
        self,
        db: Session,
        mcp_id: int,
        snapshot: Dict[str, Any],
        actor_id: Optional[int] = None,
    ) -> SyncReport:
        """
        处理 MCP Server 删除事件

        将对应的 tableau_connections 标记为：
        - is_active = False
        - auto_sync_enabled = False

        保留记录以维护历史 sync log。

        Args:
            db: SQLAlchemy Session
            mcp_id: MCP Server ID
            snapshot: 删除前的 MCP Server 快照
            actor_id: 操作者 ID

        Returns:
            SyncReport: 同步结果报告
        """
        start_time = time.monotonic()
        report = SyncReport(mcp_id=mcp_id, target_connection_id=None)

        mcp_name = snapshot.get("name")
        if not mcp_name:
            report.skipped = True
            report.skip_reason = "snapshot missing name"
            report.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return report

        # 查找对应连接
        tableau_db = TableauDatabase(session=db)
        connection = tableau_db.get_connection_by_name_and_type(mcp_name, "mcp")

        if not connection:
            report.skipped = True
            report.skip_reason = BRG_ERROR_MESSAGES[BRG_004]
            report.elapsed_ms = int((time.monotonic() - start_time) * 1000)

            emit_event(
                db=db,
                event_type=TABLEAU_CONNECTION_SYNC_SKIPPED,
                source_module=SOURCE_MODULE_TABLEAU,
                payload={
                    "mcp_id": mcp_id,
                    "reason": report.skip_reason,
                    "error_code": BRG_004,
                },
                actor_id=actor_id,
            )
            logger.warning(
                "ReverseSync: connection not found for deleted mcp_name='%s'",
                mcp_name,
            )
            return report

        # 标记为 inactive + 禁用同步
        connection.is_active = False
        connection.auto_sync_enabled = False
        db.commit()

        report.target_connection_id = connection.id
        report.fields_synced = ["is_active", "auto_sync_enabled"]
        report.elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # 发送 deactivated 事件
        emit_event(
            db=db,
            event_type=TABLEAU_CONNECTION_DEACTIVATED_BY_MCP_DELETE,
            source_module=SOURCE_MODULE_TABLEAU,
            payload={
                "mcp_id": mcp_id,
                "connection_id": connection.id,
                "connection_name": mcp_name,
            },
            actor_id=actor_id,
        )
        logger.info(
            "ReverseSync: deactivated connection_id=%d due to mcp_id=%d deletion",
            connection.id,
            mcp_id,
        )
        return report

    @classmethod
    def _assert_event_subscriptions(cls) -> None:
        """
        启动自检：确保 ReverseSyncHandler 已订阅事件总线

        若未订阅，抛出 BRG_007 错误。

        Raises:
            RuntimeError: 未订阅事件总线
        """
        if not cls._subscribed:
            error_msg = BRG_ERROR_MESSAGES[BRG_007]
            logger.error("ReverseSyncHandler startup check failed: %s", error_msg)
            raise RuntimeError(f"BRG_007: {error_msg}")
        logger.info("ReverseSyncHandler event subscription check passed")


# 模块级单例（延迟初始化）
_handler_instance: Optional[ReverseSyncHandler] = None


def get_reverse_sync_handler() -> ReverseSyncHandler:
    """获取反向同步处理器单例"""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = ReverseSyncHandler()
    return _handler_instance


def assert_reverse_sync_ready() -> None:
    """启动时调用，验证反向同步处理器已就绪"""
    handler = get_reverse_sync_handler()
    ReverseSyncHandler._assert_event_subscriptions()
