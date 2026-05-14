#!/usr/bin/env python3
"""Seed Data Agent Skill MD contracts into Skills Center as reviewable versions.

The Skills Center currently manages executable ReAct tools. Data Agent Planning
and Rendering Skill MD files are prompt contracts, so this script mirrors them
onto existing whitelisted tool skills as inactive `md-v1` versions for review.

Usage:
    cd backend && python scripts/seed_skill_md_contracts.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://mulan:mulan@localhost:5432/mulan_bi"

from app.core.database import SessionLocal
from services.data_agent.skill_prompt_loader import SkillPromptLoader
from services.auth.models import User  # noqa: F401 - registers auth_users FK target
from services.skills.models import AgentSkill, AgentSkillVersion


MD_VERSION = "md-v1"

PLANNING_SKILL_KEYS = [
    "customer_record",
    "trend_condition",
    "all_period_condition",
    "set_difference",
    "ranking",
]

ROOT_CAUSE_SKILL_KEYS = ["root_cause"]
RENDERING_SKILL_KEYS = ["answer_renderer"]


CATALOG_TARGETS = [
    {
        "skill_key": "query",
        "name": "自然语言查询",
        "category": "query",
        "admin_description": "Data Agent 通用规划 Skill MD 镜像：记录 customer_record/trend_condition/all_period_condition/set_difference/ranking。",
        "code_ref": "QueryTool + DataAgentPlanningSkillLoader",
        "kind": "planning",
        "prompt_keys": PLANNING_SKILL_KEYS,
    },
    {
        "skill_key": "root_cause_analysis",
        "name": "根因分析",
        "category": "analysis",
        "admin_description": "Data Agent 归因规划 Skill MD 镜像：记录 root_cause。",
        "code_ref": "RootCauseAnalysisTool + DataAgentPlanningSkillLoader",
        "kind": "planning",
        "prompt_keys": ROOT_CAUSE_SKILL_KEYS,
    },
    {
        "skill_key": "report_generation",
        "name": "报告生成",
        "category": "generation",
        "admin_description": "Data Agent 回答渲染 Skill MD 镜像：记录 answer_renderer。",
        "code_ref": "ReportGenerationTool + DataAgentRenderingSkillLoader",
        "kind": "rendering",
        "prompt_keys": RENDERING_SKILL_KEYS,
    },
]


def seed() -> None:
    loader = SkillPromptLoader()
    db = SessionLocal()
    try:
        created = 0
        updated = 0

        for target in CATALOG_TARGETS:
            skill = _get_or_create_skill(db, target)
            description, input_schema = _build_version_payload(loader, target)

            version = (
                db.query(AgentSkillVersion)
                .filter(
                    AgentSkillVersion.skill_id == skill.id,
                    AgentSkillVersion.version_number == MD_VERSION,
                )
                .first()
            )
            if version:
                version.description = description
                version.input_schema = input_schema
                version.endpoint_type = "static"
                version.code_ref = target["code_ref"]
                version.change_notes = "同步 Data Agent Skill MD prompt contracts（未激活，不覆盖当前运行时工具描述）。"
                version.is_active = False
                updated += 1
            else:
                db.add(
                    AgentSkillVersion(
                        skill_id=skill.id,
                        version_number=MD_VERSION,
                        description=description,
                        input_schema=input_schema,
                        endpoint_type="static",
                        code_ref=target["code_ref"],
                        change_notes="同步 Data Agent Skill MD prompt contracts（未激活，不覆盖当前运行时工具描述）。",
                        is_active=False,
                    )
                )
                created += 1

        db.commit()
        print(
            "[seed_skill_md_contracts] 完成："
            f"创建 {created} 个 md-v1 版本，更新 {updated} 个 md-v1 版本。"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _get_or_create_skill(db, target: dict) -> AgentSkill:
    skill = (
        db.query(AgentSkill)
        .filter(AgentSkill.skill_key == target["skill_key"])
        .first()
    )
    if skill:
        if skill.description != target["admin_description"]:
            skill.description = target["admin_description"]
        if skill.category != target["category"]:
            skill.category = target["category"]
        return skill

    skill = AgentSkill(
        skill_key=target["skill_key"],
        name=target["name"],
        description=target["admin_description"],
        category=target["category"],
        is_enabled=True,
    )
    db.add(skill)
    db.flush()
    return skill


def _build_version_payload(
    loader: SkillPromptLoader,
    target: dict,
) -> tuple[str, dict]:
    loaded = []
    for prompt_key in target["prompt_keys"]:
        if target["kind"] == "planning":
            result = loader.load_planning(prompt_key)
        else:
            result = loader.load_rendering(prompt_key)

        if not result.ok:
            raise RuntimeError(f"Failed to load {target['kind']} skill {prompt_key}: {result.error}")
        loaded.append(result)

    description_parts = [
        "【Data Agent Skill MD Mirror】",
        "这是 Skill MD prompt contract 的技能中心镜像，用于审阅和版本追踪。",
        "当前版本默认不激活，避免覆盖正在运行的 ReAct Tool description。",
        "",
    ]
    for result in loaded:
        description_parts.extend(
            [
                f"## {result.skill_key}",
                f"- kind: {result.kind}",
                f"- version: {result.version}",
                f"- checksum: {result.checksum}",
                f"- source_path: {result.source_path}",
                "",
                result.content or "",
                "",
            ]
        )

    input_schema = {
        "type": "object",
        "properties": {
            "skill_md_keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "此技能中心版本镜像的 Skill MD keys。",
                "default": [result.skill_key for result in loaded],
            },
            "skill_md_checksums": {
                "type": "object",
                "description": "Skill MD 内容 checksum，用于审阅和运行时观测。",
                "default": {result.skill_key: result.checksum for result in loaded},
            },
        },
        "required": [],
    }
    return "\n".join(description_parts), input_schema


if __name__ == "__main__":
    seed()
