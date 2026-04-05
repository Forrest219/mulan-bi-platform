"""
规则配置 API — 持久化到 PostgreSQL
"""
import logging
from typing import Optional

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request

from app.core.dependencies import get_current_user, require_roles
from services.rules.models import RuleConfigDatabase
from services.logs.logger import logger as audit_logger

logger = logging.getLogger(__name__)
router = APIRouter()

# 默认规则种子数据（首次启动写入数据库）
DEFAULT_RULES_SEED = [
    {"rule_id": "RULE_001", "name": "表命名规范", "level": "HIGH", "category": "Naming", "db_type": "MySQL",
     "description": "表名必须以小写字母开头，支持小写字母、数字、下划线",
     "suggestion": "表名格式：dim_xxx, fact_xxx, ods_xxx"},
    {"rule_id": "RULE_002", "name": "字段必须有注释", "level": "HIGH", "category": "Structure", "db_type": "MySQL",
     "description": "所有字段必须包含 COMMENT 注释说明",
     "suggestion": "为每个字段添加清晰的 COMMENT 说明"},
    {"rule_id": "RULE_003", "name": "金额字段类型", "level": "MEDIUM", "category": "Type", "db_type": "MySQL",
     "description": "金额相关字段必须使用 DECIMAL 类型，避免精度问题",
     "suggestion": "使用 DECIMAL(18,2) 等明确精度"},
    {"rule_id": "RULE_004", "name": "必须包含 create_time", "level": "HIGH", "category": "Audit", "db_type": "MySQL",
     "description": "表必须包含 create_time 字段记录创建时间",
     "suggestion": "添加 create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"},
    {"rule_id": "RULE_005", "name": "必须包含 update_time", "level": "HIGH", "category": "Audit", "db_type": "MySQL",
     "description": "表必须包含 update_time 字段记录更新时间",
     "suggestion": "添加 update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
    {"rule_id": "RULE_006", "name": "主键规范", "level": "HIGH", "category": "Structure", "db_type": "MySQL",
     "description": "表必须包含主键",
     "suggestion": "使用 BIGINT AUTO_INCREMENT 作为主键"},
    {"rule_id": "RULE_007", "name": "索引数量限制", "level": "MEDIUM", "category": "Index", "db_type": "MySQL",
     "description": "单表索引数量不超过 10 个",
     "suggestion": "保留必要的索引，删除冗余索引"},
    {"rule_id": "RULE_008", "name": "字段命名规范", "level": "MEDIUM", "category": "Naming", "db_type": "MySQL",
     "description": "字段名必须以小写字母开头，支持小写字母、数字、下划线",
     "suggestion": "使用下划线分隔：user_name, create_time"},
    {"rule_id": "RULE_009", "name": "软删除字段", "level": "LOW", "category": "Audit", "db_type": "MySQL",
     "description": "业务表建议包含 is_deleted 字段支持软删除",
     "suggestion": "添加 is_deleted TINYINT(1) DEFAULT 0"},
    {"rule_id": "RULE_010", "name": "表注释规范", "level": "MEDIUM", "category": "Structure", "db_type": "MySQL",
     "description": "表必须包含 COMMENT 注释说明表用途",
     "suggestion": "使用 COMMENT='表用途说明'"},
    {"rule_id": "RULE_011", "name": "SQL Server 主键规范", "level": "HIGH", "category": "Structure", "db_type": "SQL Server",
     "description": "SQL Server 表必须包含主键",
     "suggestion": "使用 INT IDENTITY(1,1) 或 BIGINT IDENTITY 作为主键"},
    {"rule_id": "RULE_012", "name": "SQL Server 注释规范", "level": "MEDIUM", "category": "Structure", "db_type": "SQL Server",
     "description": "SQL Server 表和字段使用 EXTENDED PROPERTY 存储注释",
     "suggestion": "使用 sp_addextendedproperty 存储注释"},
]

# 初始化 seed
try:
    _rule_db = RuleConfigDatabase()
    _rule_db.seed_defaults(DEFAULT_RULES_SEED)
except Exception as e:
    logger.warning("规则 seed 失败（数据库可能未就绪）: %s", e)


class ValidationRule(BaseModel):
    id: str
    name: str
    level: str
    category: str
    description: str
    suggestion: str
    db_type: str
    built_in: bool = True
    status: str = "enabled"


@router.get("/")
async def get_rules(
    request: Request,
    category: Optional[str] = None,
    level: Optional[str] = None,
    db_type: Optional[str] = None,
    status: Optional[str] = None
):
    """获取规则列表"""
    get_current_user(request)
    rule_db = RuleConfigDatabase()
    all_rules = rule_db.get_all()

    rules = [r.to_dict() for r in all_rules]

    if category and category != "ALL":
        rules = [r for r in rules if r["category"] == category]
    if level and level != "ALL":
        rules = [r for r in rules if r["level"] == level]
    if db_type and db_type != "ALL":
        rules = [r for r in rules if r["db_type"] == db_type]
    if status and status != "ALL":
        rules = [r for r in rules if r["status"] == status]

    enabled_count = sum(1 for r in rules if r["status"] == "enabled")
    disabled_count = sum(1 for r in rules if r["status"] == "disabled")

    return {
        "rules": rules,
        "total": len(rules),
        "enabled_count": enabled_count,
        "disabled_count": disabled_count
    }


@router.put("/{rule_id}/toggle")
async def toggle_rule(rule_id: str, request: Request):
    """切换规则启用/禁用状态"""
    require_roles(request, ["admin", "data_admin"])
    rule_db = RuleConfigDatabase()

    rule = rule_db.get_by_rule_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    # 获取操作人信息
    user = get_current_user(request)
    operator = user.get("username", "unknown")
    operator_id = user.get("id")

    # 记录变更前快照
    old_snapshot = rule.to_dict()
    old_enabled = rule.enabled

    new_enabled = not rule.enabled
    rule_db.toggle(rule_id, new_enabled)
    new_status = "enabled" if new_enabled else "disabled"

    # 异步写入审计日志
    try:
        audit_logger.log_rule_change(
            rule_section=rule_id,
            change_type="toggle",
            operator=operator,
            operator_id=operator_id,
            old_value={"enabled": old_enabled},
            new_value={"enabled": new_enabled},
            description=f"规则 {rule_id} 状态切换: {old_enabled} -> {new_enabled}"
        )
    except Exception as e:
        logger.warning("规则变更审计日志写入失败: %s", e)

    return {
        "rule_id": rule_id,
        "status": new_status,
        "message": f"规则已{'启用' if new_enabled else '禁用'}"
    }


@router.post("/")
async def create_custom_rule(rule: ValidationRule, request: Request):
    """创建自定义规则"""
    require_roles(request, ["admin", "data_admin"])
    rule_db = RuleConfigDatabase()

    existing = rule_db.get_by_rule_id(rule.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"规则 ID '{rule.id}' 已存在")

    # 获取操作人信息
    user = get_current_user(request)
    operator = user.get("username", "unknown")
    operator_id = user.get("id")

    new_rule = rule_db.create_rule(
        rule_id=rule.id,
        name=rule.name,
        level=rule.level,
        category=rule.category,
        description=rule.description,
        suggestion=rule.suggestion,
        db_type=rule.db_type,
        is_custom=True,
        enabled=True,
    )

    # 异步写入审计日志
    try:
        audit_logger.log_rule_change(
            rule_section=new_rule.rule_id,
            change_type="create",
            operator=operator,
            operator_id=operator_id,
            old_value=None,
            new_value=new_rule.to_dict(),
            description=f"创建自定义规则 {new_rule.rule_id}"
        )
    except Exception as e:
        logger.warning("规则变更审计日志写入失败: %s", e)

    return {"rule": new_rule.to_dict(), "message": "自定义规则创建成功"}


@router.delete("/{rule_id}")
async def delete_custom_rule(rule_id: str, request: Request):
    """删除自定义规则"""
    require_roles(request, ["admin", "data_admin"])
    rule_db = RuleConfigDatabase()

    rule = rule_db.get_by_rule_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    if not rule.is_custom:
        raise HTTPException(status_code=403, detail="无法删除内置规则")

    # 获取操作人信息
    user = get_current_user(request)
    operator = user.get("username", "unknown")
    operator_id = user.get("id")

    # 记录删除前快照
    old_snapshot = rule.to_dict()

    rule_db.delete(rule_id)

    # 异步写入审计日志
    try:
        audit_logger.log_rule_change(
            rule_section=rule_id,
            change_type="delete",
            operator=operator,
            operator_id=operator_id,
            old_value=old_snapshot,
            new_value=None,
            description=f"删除自定义规则 {rule_id}"
        )
    except Exception as e:
        logger.warning("规则变更审计日志写入失败: %s", e)

    return {"message": "规则删除成功"}
