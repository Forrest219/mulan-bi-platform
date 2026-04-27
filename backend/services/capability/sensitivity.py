"""Capability Sensitivity Gate — 敏感度门禁

对应 spec §5.3 — 从 nlq_service.is_datasource_sensitivity_blocked 迁移。
检查 principal × capability × params 是否触犯敏感度策略。
违规 raise CapabilitySensitivityBlocked(code='CAP_003')。
"""
from __future__ import annotations

import logging

from app.core.database import SessionLocal
from sqlalchemy import text

from .errors import CapabilitySensitivityBlocked
from .registry import CapabilityDefinition

logger = logging.getLogger(__name__)


def check(principal: dict, cap_def: CapabilityDefinition, params: dict) -> None:
    """
    检查敏感度门禁。

    Args:
        principal: {id, role} 字典
        cap_def: 能力定义（用于获取 guards.sensitivity_block）
        params: 请求参数

    Raises:
        CapabilitySensitivityBlocked: 当 sensitivity_block 匹配时
    """
    # 如果 capability 没有配置 sensitivity_block，直接放行
    if not cap_def.guards.sensitivity_block:
        return

    # 获取当前用户在目标 datasource 上的敏感度级别
    datasource_id = params.get("datasource_id")
    if datasource_id is None:
        return  # 没有 datasource_id 字段，跳过检查

    sensitivity = _get_datasource_sensitivity(datasource_id)
    if sensitivity is None:
        return  # 未标记敏感度，放行

    blocked_levels = set(cap_def.guards.sensitivity_block)
    if sensitivity in blocked_levels:
        logger.warning(
            "Sensitivity blocked: user=%d role=%s datasource=%s sensitivity=%s (blocked=%s)",
            principal.get("id"),
            principal.get("role"),
            datasource_id,
            sensitivity,
            blocked_levels,
        )
        raise CapabilitySensitivityBlocked(
            f"Datasource {datasource_id} has sensitivity '{sensitivity}', "
            f"which is blocked for capability '{cap_def.name}'"
        )


def _get_datasource_sensitivity(datasource_id: int) -> str | None:
    """
    查询数据源的敏感度级别。

    Returns:
        'public' | 'internal' | 'high' | 'confidential' | None
    """
    db = SessionLocal()
    try:
        result = db.execute(
            text(
                "SELECT sensitivity FROM bi_datasources WHERE id = :id"
            ),
            {"id": datasource_id},
        )
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.warning("Failed to query datasource sensitivity for id=%d: %s", datasource_id, e)
        return None
    finally:
        db.close()
