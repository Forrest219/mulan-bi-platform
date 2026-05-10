"""从 DB 加载活跃版本，覆盖 ToolRegistry 的 description + parameters_schema。

Spec: docs/specs/agents_skills.md §6

注意：本项目使用同步 SQLAlchemy Session（非 AsyncSession），
      SkillLoader 相应使用同步查询，但对外保持 async 接口（内部无 await）
      以便 factory.py 统一用 await 调用。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

if TYPE_CHECKING:
    from services.data_agent.tool_base import ToolRegistry

logger = logging.getLogger(__name__)


class SkillLoader:
    """从 DB 加载活跃版本，覆盖 ToolRegistry 的 description + parameters_schema。

    仅覆盖 meta，不替换 execute()。DB 无对应记录时保留静态类属性（fallback）。
    """

    async def load_and_override(
        self,
        registry: "ToolRegistry",
        db: Any,
    ) -> dict[str, str]:
        """
        查询 agent_skills + agent_skill_versions WHERE is_active=true AND is_enabled=true。
        对 registry 中存在的 skill_key 覆盖 description + parameters_schema。
        返回 {skill_key: version_id_str} 供 ReActEngine 写入步骤记录。

        db 接受同步 SQLAlchemy Session（项目当前架构）。
        出现任何异常均 graceful degradation，不影响 agent 正常运行。
        """
        # 延迟 import 防止循环依赖（services/skills 依赖本文件所在包）
        try:
            from services.skills.models import AgentSkill, AgentSkillVersion
        except ImportError:
            # skills 模块尚未安装时 graceful degradation，agent 照常运行（fallback 到静态 meta）
            return {}

        try:
            stmt = (
                select(
                    AgentSkill.skill_key,
                    AgentSkillVersion.description,
                    AgentSkillVersion.input_schema,
                    AgentSkillVersion.id.label("version_id"),
                )
                .join(
                    AgentSkillVersion,
                    (AgentSkillVersion.skill_id == AgentSkill.id)
                    & (AgentSkillVersion.is_active.is_(True)),
                )
                .where(AgentSkill.is_enabled.is_(True))
            )
            rows = db.execute(stmt).fetchall()
        except Exception as exc:
            # DB 查询失败时 graceful degradation（如表尚未创建、连接异常等）
            logger.debug("SkillLoader: DB query failed, using static meta. reason=%s", exc)
            return {}

        version_map: dict[str, str] = {}
        for row in rows:
            skill_key, description, input_schema, version_id = row
            if registry.has(skill_key):
                registry.override_meta(skill_key, description, input_schema)
                version_map[skill_key] = str(version_id)
        return version_map
