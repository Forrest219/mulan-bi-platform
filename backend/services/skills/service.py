"""
Skills Service — 技能中心核心业务逻辑

Spec: docs/specs/agents_skills.md §4 / §5 / §6.5
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import jsonpatch
import jsonschema
from cachetools import TTLCache
from sqlalchemy import update
from sqlalchemy.orm import Session

from services.skills.models import AgentSkill, AgentSkillVersion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 白名单：factory.py 中 register 的所有工具名（v1 硬编码）
# Spec §3.5: skill_key 必须属于静态 ToolRegistry 已注册的工具
# ---------------------------------------------------------------------------
STATIC_SKILL_KEYS: frozenset = frozenset([
    "query",
    "schema",
    "metrics",
    "causation",
    "chart",
    "report_generation",
    "proactive_insight",
    "data_comparison",
    "trend_analysis",
    "correlation_discovery",
    "segmentation_analysis",
    "funnel_analysis",
    "cohort_analysis",
    "root_cause_analysis",
])

# ---------------------------------------------------------------------------
# Dispatch 缓存 — TTLCache(maxsize=100, ttl=60s)
# Spec §6.5: 单进程内存缓存，版本切换时主动失效
# ---------------------------------------------------------------------------
_dispatch_cache: TTLCache = TTLCache(maxsize=100, ttl=60)
DISPATCH_CACHE_KEY = "dispatch:all"


def _invalidate_dispatch_cache() -> None:
    """主动失效 dispatch 缓存。版本发布/回滚后调用。"""
    _dispatch_cache.pop(DISPATCH_CACHE_KEY, None)


def _validate_input_schema(input_schema: Any) -> None:
    """用 jsonschema.Draft7Validator.check_schema() 校验 input_schema 是否为合法 JSON Schema。

    Raises:
        ValueError: 非法 schema，含错误描述
    """
    try:
        jsonschema.Draft7Validator.check_schema(input_schema)
    except jsonschema.SchemaError as e:
        raise ValueError(f"input_schema 不合法：{e.message}") from e


def _emit_skill_event(
    db: Session,
    *,
    skill_key: str,
    from_version: Optional[str],
    to_version: str,
    action: str,
    actor_id: Optional[int],
) -> None:
    """向 bi_events 写入 skill_version_activated 审计事件。

    Spec §9.3: 版本发布和回滚操作写入 bi_events（Append-Only）。
    静默失败不影响主流程。
    """
    try:
        from services.events.event_service import emit_event
        emit_event(
            db=db,
            event_type="skill_version_activated",
            source_module="skills",
            payload={
                "skill_key": skill_key,
                "from_version": from_version,
                "to_version": to_version,
                "action": action,
            },
            actor_id=actor_id,
        )
    except Exception as exc:
        logger.warning("skill 审计事件写入失败: %s", exc)


# ---------------------------------------------------------------------------
# 原子版本切换（publish 和 rollback 共用）
# ---------------------------------------------------------------------------

def _atomic_activate_version(
    db: Session,
    *,
    skill_id: str,
    target_version_id: str,
    actor_id: Optional[int] = None,
    action: str = "publish",
) -> Dict[str, Any]:
    """原子切换活跃版本。

    1. SELECT FOR UPDATE 锁定 skill 行（防并发双写）
    2. 旧活跃版本 → is_active=False
    3. 目标版本 → is_active=True
    4. 失效 dispatch 缓存
    5. 写入审计事件

    Returns:
        {"skill_key": str, "from_version": str|None, "to_version": str, "activated_at": datetime}

    Raises:
        ValueError: 目标版本不属于该 skill
    """
    # 行级锁
    skill = (
        db.query(AgentSkill)
        .filter(AgentSkill.id == skill_id)
        .with_for_update()
        .first()
    )
    if not skill:
        raise LookupError(f"技能不存在: {skill_id}")

    # 查询目标版本，验证归属
    target_ver = (
        db.query(AgentSkillVersion)
        .filter(
            AgentSkillVersion.id == target_version_id,
            AgentSkillVersion.skill_id == skill_id,
        )
        .first()
    )
    if not target_ver:
        raise LookupError(f"版本不存在或不属于该技能: {target_version_id}")

    # 旧活跃版本
    old_active = (
        db.query(AgentSkillVersion)
        .filter(
            AgentSkillVersion.skill_id == skill_id,
            AgentSkillVersion.is_active == True,  # noqa: E712
        )
        .first()
    )
    from_version = old_active.version_number if old_active else None

    # 旧活跃 → 非活跃
    if old_active and old_active.id != target_ver.id:
        db.execute(
            update(AgentSkillVersion)
            .where(
                AgentSkillVersion.skill_id == skill_id,
                AgentSkillVersion.is_active == True,  # noqa: E712
            )
            .values(is_active=False)
        )

    # 目标版本 → 活跃
    target_ver.is_active = True

    # 更新 skill 的 updated_at
    skill.updated_at = datetime.utcnow()

    db.flush()

    # 失效缓存
    _invalidate_dispatch_cache()

    # 审计
    _emit_skill_event(
        db,
        skill_key=skill.skill_key,
        from_version=from_version,
        to_version=target_ver.version_number,
        action=action,
        actor_id=actor_id,
    )

    return {
        "skill_key": skill.skill_key,
        "from_version": from_version,
        "to_version": target_ver.version_number,
        "activated_at": datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# Public Service API
# ---------------------------------------------------------------------------


def create_skill(
    db: Session,
    *,
    skill_key: str,
    name: str,
    description: Optional[str],
    category: str,
    initial_version: Dict[str, Any],
    created_by_id: Optional[int] = None,
) -> Dict[str, Any]:
    """创建新技能（含 v1 版本原子写入）。

    Spec §4.1 业务规则:
    - skill_key 全局唯一；冲突 409 SKILLS_001
    - skill_key 必须在白名单；不在则 400 SKILLS_006
    - endpoint_type v1 只允许 'static'；其他 400 SKILLS_005
    - input_schema 校验；非法 400 SKILLS_003
    """
    # 白名单校验
    if skill_key not in STATIC_SKILL_KEYS:
        raise ValueError(f"SKILLS_006:skill_key '{skill_key}' 不在已注册工具列表中")

    # endpoint_type 校验
    ep_type = initial_version.get("endpoint_type", "static")
    if ep_type != "static":
        raise ValueError(f"SKILLS_005:v1 不支持 endpoint_type='{ep_type}'，当前仅支持 'static'")

    # input_schema 校验
    input_schema = initial_version.get("input_schema", {})
    try:
        _validate_input_schema(input_schema)
    except ValueError as e:
        raise ValueError(f"SKILLS_003:{e}") from e

    # 唯一性检查
    existing = db.query(AgentSkill).filter(AgentSkill.skill_key == skill_key).first()
    if existing:
        raise ValueError(f"SKILLS_001:skill_key '{skill_key}' 已存在")

    # 创建 skill
    skill = AgentSkill(
        skill_key=skill_key,
        name=name,
        description=description,
        category=category,
        is_enabled=True,
        created_by=created_by_id,
    )
    db.add(skill)
    db.flush()  # 获取 skill.id

    # 创建 v1 版本，is_active=True
    version = AgentSkillVersion(
        skill_id=skill.id,
        version_number="v1",
        description=initial_version["description"],
        input_schema=input_schema,
        endpoint_type=ep_type,
        code_ref=initial_version.get("code_ref"),
        change_notes=initial_version.get("change_notes", "初始版本"),
        is_active=True,
        created_by=created_by_id,
    )
    db.add(version)
    db.flush()

    # 失效缓存
    _invalidate_dispatch_cache()

    return {
        "id": str(skill.id),
        "skill_key": skill.skill_key,
        "name": skill.name,
        "category": skill.category,
        "is_enabled": skill.is_enabled,
        "active_version": {
            "id": str(version.id),
            "version_number": version.version_number,
            "is_active": True,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        },
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
    }


def publish_version(
    db: Session,
    *,
    skill_id: str,
    description: str,
    input_schema: Dict[str, Any],
    endpoint_type: str = "static",
    code_ref: Optional[str] = None,
    change_notes: Optional[str] = None,
    created_by_id: Optional[int] = None,
) -> Dict[str, Any]:
    """发布新版本（自动将旧版本设为非活跃）。

    Spec §4.2: FOR UPDATE + 原子切换 + cache invalidate + bi_events 写入。
    """
    # endpoint_type 校验
    if endpoint_type != "static":
        raise ValueError(f"SKILLS_005:v1 不支持 endpoint_type='{endpoint_type}'，当前仅支持 'static'")

    # input_schema 校验
    try:
        _validate_input_schema(input_schema)
    except ValueError as e:
        raise ValueError(f"SKILLS_003:{e}") from e

    # 行级锁 + 获取 skill
    skill = (
        db.query(AgentSkill)
        .filter(AgentSkill.id == skill_id)
        .with_for_update()
        .first()
    )
    if not skill:
        raise LookupError(f"SKILLS_004:技能不存在: {skill_id}")

    # 计算新版本号：取所有版本的数字序号最大值 + 1（避免字符串比较 v9 > v10 的问题）
    version_rows = (
        db.query(AgentSkillVersion.version_number)
        .filter(AgentSkillVersion.skill_id == skill_id)
        .all()
    )
    if not version_rows:
        new_ver = "v1"
    else:
        nums = [
            int(row[0][1:])
            for row in version_rows
            if row[0].startswith("v") and row[0][1:].isdigit()
        ]
        new_ver = f"v{max(nums) + 1}" if nums else "v1"

    # 旧活跃 → 非活跃
    prev_active = (
        db.query(AgentSkillVersion)
        .filter(
            AgentSkillVersion.skill_id == skill_id,
            AgentSkillVersion.is_active == True,  # noqa: E712
        )
        .first()
    )
    prev_version_number = prev_active.version_number if prev_active else None

    db.execute(
        update(AgentSkillVersion)
        .where(
            AgentSkillVersion.skill_id == skill_id,
            AgentSkillVersion.is_active == True,  # noqa: E712
        )
        .values(is_active=False)
    )

    # 插入新版本 is_active=True
    new_version = AgentSkillVersion(
        skill_id=skill_id,
        version_number=new_ver,
        description=description,
        input_schema=input_schema,
        endpoint_type=endpoint_type,
        code_ref=code_ref,
        change_notes=change_notes,
        is_active=True,
        created_by=created_by_id,
    )
    db.add(new_version)

    # 更新 skill updated_at
    skill.updated_at = datetime.utcnow()

    db.flush()

    # 失效缓存
    _invalidate_dispatch_cache()

    # 审计
    _emit_skill_event(
        db,
        skill_key=skill.skill_key,
        from_version=prev_version_number,
        to_version=new_ver,
        action="publish",
        actor_id=created_by_id,
    )

    return {
        "id": str(new_version.id),
        "skill_id": str(skill.id),
        "version_number": new_ver,
        "is_active": True,
        "previous_active_version": prev_version_number,
        "created_at": new_version.created_at.isoformat() if new_version.created_at else None,
    }


def rollback_version(
    db: Session,
    *,
    skill_id: str,
    version_id: str,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """回滚到指定版本（不创建新版本行，直接重新激活历史版本）。

    Spec §4.3: 回滚与发布共用同一原子切换逻辑。
    """
    try:
        result = _atomic_activate_version(
            db,
            skill_id=skill_id,
            target_version_id=version_id,
            actor_id=user_id,
            action="rollback",
        )
    except LookupError as e:
        msg = str(e)
        if "版本不存在" in msg:
            raise LookupError(f"SKILLS_002:{msg}") from e
        raise LookupError(f"SKILLS_004:{msg}") from e

    return {
        "skill_id": skill_id,
        "rolled_back_to": result["to_version"],
        "previous_active": result["from_version"],
        "activated_at": result["activated_at"].isoformat(),
    }


def list_skills(
    db: Session,
    *,
    category: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """技能列表（含 active_version）。

    Spec §4.5 GET /api/skills
    """
    query = db.query(AgentSkill)

    if category:
        query = query.filter(AgentSkill.category == category)
    if is_enabled is not None:
        query = query.filter(AgentSkill.is_enabled == is_enabled)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            (AgentSkill.name.ilike(pattern)) | (AgentSkill.skill_key.ilike(pattern))
        )

    total = query.count()
    skills = query.order_by(AgentSkill.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for skill in skills:
        active_ver = (
            db.query(AgentSkillVersion)
            .filter(
                AgentSkillVersion.skill_id == skill.id,
                AgentSkillVersion.is_active == True,  # noqa: E712
            )
            .first()
        )
        item = skill.to_dict()
        item["active_version"] = (
            {
                "version_number": active_ver.version_number,
                "updated_at": active_ver.created_at.isoformat() if active_ver.created_at else None,
            }
            if active_ver
            else None
        )
        items.append(item)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_skill(db: Session, *, skill_id: str) -> Dict[str, Any]:
    """技能详情（含所有版本列表）。

    Spec §4.5 GET /api/skills/{id}
    """
    skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
    if not skill:
        raise LookupError(f"SKILLS_004:技能不存在: {skill_id}")

    versions = (
        db.query(AgentSkillVersion)
        .filter(AgentSkillVersion.skill_id == skill_id)
        .order_by(AgentSkillVersion.created_at.desc())
        .all()
    )

    result = skill.to_dict()
    result["versions"] = [v.to_dict() for v in versions]
    return result


def patch_skill(
    db: Session,
    *,
    skill_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    is_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """更新技能基本信息（白名单字段）。

    Spec §4.5 PATCH /api/skills/{id}
    只允许更新 name / description / category / is_enabled。
    skill_key 不可变。
    """
    skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
    if not skill:
        raise LookupError(f"SKILLS_004:技能不存在: {skill_id}")

    if name is not None:
        skill.name = name
    if description is not None:
        skill.description = description
    if category is not None:
        skill.category = category
    if is_enabled is not None:
        skill.is_enabled = is_enabled
        _invalidate_dispatch_cache()

    skill.updated_at = datetime.utcnow()
    db.flush()

    return skill.to_dict()


def get_dispatch(db: Session, *, category: Optional[str] = None, skill_keys: Optional[str] = None) -> Dict[str, Any]:
    """批量查询当前生效的技能定义（供 LLM 调用）。

    Spec §4.4: 仅缓存全量结果，category/skill_keys 在内存过滤。
    """
    # 尝试命中缓存
    cached = _dispatch_cache.get(DISPATCH_CACHE_KEY)
    if cached is None:
        # 冷启动：DB 查询
        rows = (
            db.query(
                AgentSkill.skill_key,
                AgentSkill.name,
                AgentSkillVersion.description,
                AgentSkillVersion.input_schema,
                AgentSkillVersion.version_number,
                AgentSkillVersion.id.label("version_id"),
                AgentSkill.category,
            )
            .join(
                AgentSkillVersion,
                (AgentSkillVersion.skill_id == AgentSkill.id)
                & (AgentSkillVersion.is_active == True),  # noqa: E712
            )
            .filter(AgentSkill.is_enabled == True)  # noqa: E712
            .all()
        )
        tools = [
            {
                "skill_key": row.skill_key,
                "name": row.name,
                "description": row.description,
                "input_schema": row.input_schema,
                "version_number": row.version_number,
                "version_id": str(row.version_id),
                "category": row.category,
            }
            for row in rows
        ]
        cached = tools
        _dispatch_cache[DISPATCH_CACHE_KEY] = cached

    # 内存过滤
    filtered = cached
    if category:
        filtered = [t for t in filtered if t.get("category") == category]
    if skill_keys:
        keys_set = {k.strip() for k in skill_keys.split(",")}
        filtered = [t for t in filtered if t.get("skill_key") in keys_set]

    return {
        "tools": filtered,
        "total": len(cached),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


def get_diff(
    db: Session,
    *,
    skill_id: str,
    v_id1: str,
    v_id2: str,
) -> Dict[str, Any]:
    """对比两个版本的 input_schema 差异（RFC 6902 JSON Patch）。

    Spec §4.5 GET /api/skills/{id}/versions/{v_id}/diff/{v_id2}
    """
    ver1 = (
        db.query(AgentSkillVersion)
        .filter(AgentSkillVersion.id == v_id1, AgentSkillVersion.skill_id == skill_id)
        .first()
    )
    ver2 = (
        db.query(AgentSkillVersion)
        .filter(AgentSkillVersion.id == v_id2, AgentSkillVersion.skill_id == skill_id)
        .first()
    )
    if not ver1:
        raise LookupError(f"SKILLS_002:版本不存在或不属于该技能: {v_id1}")
    if not ver2:
        raise LookupError(f"SKILLS_002:版本不存在或不属于该技能: {v_id2}")

    patch = jsonpatch.make_patch(ver1.input_schema, ver2.input_schema)

    return {
        "from_version": ver1.version_number,
        "to_version": ver2.version_number,
        "description_changed": ver1.description != ver2.description,
        "schema_patch": list(patch),
    }
