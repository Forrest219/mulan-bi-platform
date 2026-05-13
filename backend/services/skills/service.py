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

from services.data_agent.factory import create_engine
from services.auth.models import User
from services.logs.models import OperationLog
from services.skills.models import AgentSkill, AgentSkillVersion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 白名单：factory.py 中 register 的所有工具名（v1 硬编码）
# Spec §3.5: skill_key 必须属于静态 ToolRegistry 已注册的工具
# ---------------------------------------------------------------------------
def _create_static_registry():
    """Build the static ToolRegistry without DB skill overrides."""
    _, registry = create_engine()
    return registry


STATIC_SKILL_KEYS: frozenset = frozenset(_create_static_registry().list_tool_names())

# ---------------------------------------------------------------------------
# Dispatch 缓存 — TTLCache(maxsize=100, ttl=10s)
# Spec §6.5: 单进程内存缓存，版本切换时主动失效
# ---------------------------------------------------------------------------
_dispatch_cache: TTLCache = TTLCache(maxsize=100, ttl=10)
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


def _log_skill_operation(
    db: Session,
    *,
    operation_type: str,
    target: str,
    operator_id: Optional[int],
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Write bi_operation_logs for skill mutations.

    The log is best-effort and enclosed in a SAVEPOINT so logging failures do
    not poison the caller's transaction.
    """
    try:
        with db.begin_nested():
            db.add(
                OperationLog(
                    operator=f"user:{operator_id}" if operator_id else "anonymous",
                    operator_id=operator_id,
                    operation_type=operation_type,
                    target=target,
                    status="success",
                    details=details or {},
                )
            )
            db.flush()
    except Exception as exc:
        logger.warning("skill 操作日志写入失败: %s", exc)


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

    _log_skill_operation(
        db,
        operation_type="skill_version_rollback"
        if action == "rollback"
        else "skill_version_publish",
        target=f"skill:{skill.skill_key}:version:{target_ver.version_number}",
        operator_id=actor_id,
        details={
            "skill_id": str(skill.id),
            "skill_key": skill.skill_key,
            "from_version": from_version,
            "to_version": target_ver.version_number,
            "action": action,
        },
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


def get_active_skill_version(db: Session, skill_key: str) -> Dict[str, Any]:
    """查询 skill 当前 active version 配置，供 deterministic route 做只读感知。

    skill 不存在或无 active version 时返回可判定状态，不抛业务异常。
    """
    skill = db.query(AgentSkill).filter(AgentSkill.skill_key == skill_key).first()
    if not skill:
        return {
            "is_configured": False,
            "is_enabled": False,
            "version_id": None,
            "version_number": None,
            "description": None,
            "input_schema": None,
        }

    active_ver = (
        db.query(AgentSkillVersion)
        .filter(
            AgentSkillVersion.skill_id == skill.id,
            AgentSkillVersion.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not active_ver:
        return {
            "is_configured": True,
            "is_enabled": skill.is_enabled,
            "version_id": None,
            "version_number": None,
            "description": None,
            "input_schema": None,
        }

    return {
        "is_configured": True,
        "is_enabled": skill.is_enabled,
        "version_id": str(active_ver.id),
        "version_number": active_ver.version_number,
        "description": active_ver.description,
        "input_schema": active_ver.input_schema,
    }


def list_registered_tools(db: Session) -> Dict[str, Any]:
    """Return static ToolRegistry metadata with DB configuration markers.

    This is intentionally read-only: it only inspects ToolRegistry and existing
    agent_skills / active versions, and never creates missing skill rows.
    """
    registry = _create_static_registry()
    registry_tools = registry.list_tools()
    keys = [tool.name for tool in registry_tools]

    configured_rows = (
        db.query(AgentSkill, AgentSkillVersion)
        .outerjoin(
            AgentSkillVersion,
            (AgentSkillVersion.skill_id == AgentSkill.id)
            & (AgentSkillVersion.is_active == True),  # noqa: E712
        )
        .filter(AgentSkill.skill_key.in_(keys))
        .all()
    )
    configured_by_key = {skill.skill_key: (skill, active_ver) for skill, active_ver in configured_rows}

    tools = []
    for tool in registry_tools:
        skill, active_ver = configured_by_key.get(tool.name, (None, None))
        tools.append(
            {
                "skill_key": tool.name,
                "name": skill.name if skill else tool.name,
                "description": tool.description,
                "default_description": tool.description,
                "input_schema": tool.parameters_schema,
                "default_parameters_schema": tool.parameters_schema,
                "category": tool.metadata.category,
                "code_ref": tool.__class__.__name__,
                "configured": skill is not None,
                "skill_id": str(skill.id) if skill else None,
                "active_version_id": str(active_ver.id) if active_ver else None,
                "active_version_number": active_ver.version_number if active_ver else None,
            }
        )

    return {"tools": tools, "total": len(tools)}


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

    _log_skill_operation(
        db,
        operation_type="skill_create",
        target=f"skill:{skill.skill_key}",
        operator_id=created_by_id,
        details={
            "skill_id": str(skill.id),
            "skill_key": skill.skill_key,
            "active_version_number": version.version_number,
        },
    )

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

    _log_skill_operation(
        db,
        operation_type="skill_version_publish",
        target=f"skill:{skill.skill_key}:version:{new_ver}",
        operator_id=created_by_id,
        details={
            "skill_id": str(skill.id),
            "skill_key": skill.skill_key,
            "from_version": prev_version_number,
            "to_version": new_ver,
        },
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

    rows = (
        db.query(AgentSkillVersion, User.display_name, User.username)
        .outerjoin(User, User.id == AgentSkillVersion.created_by)
        .filter(AgentSkillVersion.skill_id == skill_id)
        .order_by(AgentSkillVersion.created_at.desc())
        .all()
    )

    result = skill.to_dict()
    result["versions"] = []
    for version, display_name, username in rows:
        item = version.to_dict()
        item["created_by_name"] = display_name or username
        result["versions"].append(item)
    return result


def patch_skill(
    db: Session,
    *,
    skill_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    updated_by_id: Optional[int] = None,
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

    _log_skill_operation(
        db,
        operation_type="skill_update",
        target=f"skill:{skill.skill_key}",
        operator_id=updated_by_id,
        details={
            "skill_id": str(skill.id),
            "skill_key": skill.skill_key,
            "updated_fields": [
                field
                for field, value in {
                    "name": name,
                    "description": description,
                    "category": category,
                    "is_enabled": is_enabled,
                }.items()
                if value is not None
            ],
        },
    )

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
