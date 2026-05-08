"""轻量级审计服务 — 将敏感操作写入 bi_operation_logs

使用已有的 bi_operation_logs 表，不引入新表/迁移。
失败时只记录警告，不影响主链路。
"""
import logging
from typing import Any, Optional

from services.logs.logger import logger as op_logger

_log = logging.getLogger(__name__)


def log_action(
    user_id: int,
    username: str,
    action: str,
    resource_type: str,
    resource_id: Any,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
) -> None:
    """写入操作审计记录到 bi_operation_logs。

    Args:
        user_id:       操作人 ID
        username:      操作人用户名
        action:        动作名称，如 create / update / delete
        resource_type: 资源类型，如 user / datasource
        resource_id:   资源 ID
        before_state:  操作前快照（可选）
        after_state:   操作后快照（可选）
    """
    try:
        op_logger.log_operation(
            operation_type=f"audit.{action}",
            target=f"{resource_type}:{resource_id}",
            status="success",
            details={
                "before": before_state,
                "after": after_state,
            },
            operator=username,
            operator_id=user_id,
        )
    except Exception as exc:
        _log.warning("审计日志写入失败: %s", exc)
