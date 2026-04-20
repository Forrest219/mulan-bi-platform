"""规则配置 API — 持久化到 PostgreSQL
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.dependencies import get_current_user, require_roles
from services.ddl_checker.cache import RuleCache
from services.logs.logger import logger as audit_logger
from services.rules.models import RuleConfigDatabase

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

# 初始化 seed（幂等性：已修改的规则不会被覆盖）
try:
    _rule_db = RuleConfigDatabase()
    _rule_db.seed_defaults(DEFAULT_RULES_SEED)
except Exception as e:
    logger.warning("规则 seed 失败（数据库可能未就绪）: %s", e)


class ValidationRule(BaseModel):
    """DDL 验证规则模型"""

    id: str
    name: str
    level: str
    category: str
    description: str
    suggestion: str
    db_type: str
    built_in: bool = True
    status: str = "enabled"


class DryRunRequest(BaseModel):
    """Dry Run 请求"""

    rule: dict
    ddl_text: str
    db_type: str = "mysql"


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
async def toggle_rule(
    rule_id: str,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """切换规则启用/禁用状态。

    关键变更（disable）使用同一 DB 事务同步写入审计日志。
    """
    rule_db = RuleConfigDatabase()

    rule = rule_db.get_by_rule_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail={"code": "DDL_002", "message": "规则不存在"})

    operator = current_user.get("username", "unknown")
    operator_id = current_user.get("id")

    old_snapshot = rule.to_dict()
    old_enabled = rule.enabled
    new_enabled = not rule.enabled

    # 切换状态
    rule_db.toggle(rule_id, new_enabled)
    new_status = "enabled" if new_enabled else "disabled"

    # 失效缓存
    RuleCache.invalidate()

    # 关键变更（disable）同步写入审计日志，确保可靠性
    if not new_enabled:
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
            logger.error("关键规则变更审计日志写入失败: %s", e)
            raise HTTPException(status_code=500, detail={"code": "DDL_500", "message": "审计日志写入失败"})
    else:
        # 一般变更可用异步
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
async def create_custom_rule(
    rule: ValidationRule,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """创建自定义规则"""
    rule_db = RuleConfigDatabase()

    existing = rule_db.get_by_rule_id(rule.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"规则 ID '{rule.id}' 已存在")

    # 获取操作人信息
    operator = current_user.get("username", "unknown")
    operator_id = current_user.get("id")

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
        is_modified_by_user=True,  # 标记为用户创建的规则
    )

    # 失效缓存
    RuleCache.invalidate()

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
async def delete_custom_rule(
    rule_id: str,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """删除自定义规则。

    删除操作使用同步 DB 事务写入审计日志，确保可靠性。
    """
    rule_db = RuleConfigDatabase()

    rule = rule_db.get_by_rule_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail={"code": "DDL_002", "message": "规则不存在"})
    if not rule.is_custom:
        raise HTTPException(status_code=403, detail={"code": "DDL_403", "message": "无法删除内置规则"})

    operator = current_user.get("username", "unknown")
    operator_id = current_user.get("id")

    old_snapshot = rule.to_dict()

    # 删除规则
    rule_db.delete(rule_id)

    # 失效缓存
    RuleCache.invalidate()

    # 同步写入审计日志（关键操作，必须确保成功）
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
        logger.error("关键规则删除审计日志写入失败: %s", e)
        raise HTTPException(status_code=500, detail={"code": "DDL_500", "message": "审计日志写入失败"})

    return {"message": "规则删除成功"}


@router.post("/test")
async def test_rule(
    body: DryRunRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """Dry Run：测试新规则对指定 DDL 的拦截效果（不保存规则）。

    用于管理员在修改规则配置后，预验证规则是否按预期拦截/放行。
    """

    from services.ddl_checker.parser import DDLParser

    rule = body.rule
    ddl_text = body.ddl_text
    db_type = body.db_type

    # 解析 DDL
    parser = DDLParser()
    try:
        table_info, parse_mode = parser.parse_create_table(ddl_text)
    except Exception as e:
        return {
            "code": "DDL_006",
            "message": f"Dry Run 失败: {str(e)}",
            "trace_id": "",
            "data": {
                "rule_id": rule.get("rule_id", "TEST"),
                "ddl_text": ddl_text,
                "hit": False,
                "violations": []
            }
        }

    if not table_info:
        return {
            "code": "DDL_001",
            "message": "无法解析 DDL 语句",
            "trace_id": "",
            "data": {
                "rule_id": rule.get("rule_id", "TEST"),
                "ddl_text": ddl_text,
                "hit": False,
                "violations": []
            }
        }

    # 临时应用规则进行测试
    # 注意：这里仅做简化验证，实际实现可能需要更复杂的规则引擎
    violations = []

    # 简单检查：按规则中的 pattern 进行正则匹配
    import re
    pattern = rule.get("pattern", "")
    check_target = rule.get("check_target", "table_name")

    if pattern:
        try:
            if check_target == "table_name":
                target_value = table_info.name
                if not re.match(pattern, target_value):
                    violations.append({
                        "level": rule.get("level", "HIGH"),
                        "message": f"表名 '{target_value}' 不符合正则 {pattern}",
                        "suggestion": rule.get("suggestion", "")
                    })
        except re.error:
            return {
                "code": "DDL_006",
                "message": f"规则正则表达式无效: {pattern}",
                "trace_id": "",
                "data": {
                    "rule_id": rule.get("rule_id", "TEST"),
                    "ddl_text": ddl_text,
                    "hit": False,
                    "violations": []
                }
            }

    return {
        "code": "DDL_000",
        "message": "Dry Run 完成",
        "trace_id": "",
        "data": {
            "rule_id": rule.get("rule_id", "TEST"),
            "ddl_text": ddl_text,
            "hit": len(violations) > 0,
            "violations": violations
        }
    }
