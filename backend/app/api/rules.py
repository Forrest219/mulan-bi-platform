"""
规则配置 API
"""
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional, List
from datetime import datetime
import os
import jwt

router = APIRouter()

# JWT 验签
_JWT_SECRET = os.environ.get("SESSION_SECRET")
_JWT_ALGORITHM = "HS256"


def _decode_session_token(token: str):
    """验证并解码 session token"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return {"id": int(payload["sub"]), "username": payload["username"], "role": payload["role"]}
    except jwt.InvalidTokenError:
        return None


def get_current_user(request: Request) -> dict:
    """获取当前登录用户"""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user_info = _decode_session_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="无效的会话")
    return user_info


# 内存存储规则状态（实际应持久化到数据库）
rules_storage = {
    "RULE_001": {"status": "enabled"},
    "RULE_002": {"status": "enabled"},
    "RULE_003": {"status": "enabled"},
    "RULE_004": {"status": "enabled"},
    "RULE_005": {"status": "enabled"},
}


class ValidationRule(BaseModel):
    """验证规则"""
    id: str
    name: str
    level: str  # HIGH, MEDIUM, LOW
    category: str  # Naming, Structure, Type, Index, Audit
    description: str
    suggestion: str
    db_type: str  # MySQL, SQL Server
    built_in: bool = True
    status: str = "enabled"  # enabled, disabled


# 默认规则列表
DEFAULT_RULES = [
    ValidationRule(
        id="RULE_001",
        name="表命名规范",
        level="HIGH",
        category="Naming",
        description="表名必须以小写字母开头，支持小写字母、数字、下划线",
        suggestion="表名格式：dim_xxx, fact_xxx, ods_xxx",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_002",
        name="字段必须有注释",
        level="HIGH",
        category="Structure",
        description="所有字段必须包含 COMMENT 注释说明",
        suggestion="为每个字段添加清晰的 COMMENT 说明",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_003",
        name="金额字段类型",
        level="MEDIUM",
        category="Type",
        description="金额相关字段必须使用 DECIMAL 类型，避免精度问题",
        suggestion="使用 DECIMAL(18,2) 等明确精度",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_004",
        name="必须包含 create_time",
        level="HIGH",
        category="Audit",
        description="表必须包含 create_time 字段记录创建时间",
        suggestion="添加 create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_005",
        name="必须包含 update_time",
        level="HIGH",
        category="Audit",
        description="表必须包含 update_time 字段记录更新时间",
        suggestion="添加 update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_006",
        name="主键规范",
        level="HIGH",
        category="Structure",
        description="表必须包含主键",
        suggestion="使用 BIGINT AUTO_INCREMENT 作为主键",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_007",
        name="索引数量限制",
        level="MEDIUM",
        category="Index",
        description="单表索引数量不超过 10 个",
        suggestion="保留必要的索引，删除冗余索引",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_008",
        name="字段命名规范",
        level="MEDIUM",
        category="Naming",
        description="字段名必须以小写字母开头，支持小写字母、数字、下划线",
        suggestion="使用下划线分隔：user_name, create_time",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_009",
        name="软删除字段",
        level="LOW",
        category="Audit",
        description="业务表建议包含 is_deleted 字段支持软删除",
        suggestion="添加 is_deleted TINYINT(1) DEFAULT 0",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_010",
        name="表注释规范",
        level="MEDIUM",
        category="Structure",
        description="表必须包含 COMMENT 注释说明表用途",
        suggestion="使用 COMMENT='表用途说明'",
        db_type="MySQL",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_011",
        name="SQL Server 主键规范",
        level="HIGH",
        category="Structure",
        description="SQL Server 表必须包含主键",
        suggestion="使用 INT IDENTITY(1,1) 或 BIGINT IDENTITY 作为主键",
        db_type="SQL Server",
        built_in=True,
        status="enabled"
    ),
    ValidationRule(
        id="RULE_012",
        name="SQL Server 注释规范",
        level="MEDIUM",
        category="Structure",
        description="SQL Server 表和字段使用 EXTENDED PROPERTY 存储注释",
        suggestion="使用 sp_addextendedproperty 存储注释",
        db_type="SQL Server",
        built_in=True,
        status="enabled"
    ),
]


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
    rules = DEFAULT_RULES.copy()

    # 应用过滤
    if category and category != "ALL":
        rules = [r for r in rules if r.category == category]
    if level and level != "ALL":
        rules = [r for r in rules if r.level == level]
    if db_type and db_type != "ALL":
        rules = [r for r in rules if r.db_type == db_type]

    # 应用状态
    for rule in rules:
        rule.status = rules_storage.get(rule.id, {}).get("status", "enabled")

    if status and status != "ALL":
        rules = [r for r in rules if r.status == status]

    enabled_count = sum(1 for r in rules if r.status == "enabled")
    disabled_count = sum(1 for r in rules if r.status == "disabled")

    return {
        "rules": [r.dict() for r in rules],
        "total": len(rules),
        "enabled_count": enabled_count,
        "disabled_count": disabled_count
    }


@router.put("/{rule_id}/toggle")
async def toggle_rule(rule_id: str, request: Request):
    """切换规则启用/禁用状态"""
    get_current_user(request)
    if rule_id not in rules_storage:
        rules_storage[rule_id] = {"status": "enabled"}

    current_status = rules_storage[rule_id]["status"]
    new_status = "disabled" if current_status == "enabled" else "enabled"
    rules_storage[rule_id]["status"] = new_status

    return {
        "rule_id": rule_id,
        "status": new_status,
        "message": f"规则已{'禁用' if new_status == 'disabled' else '启用'}"
    }


@router.post("/")
async def create_custom_rule(rule: ValidationRule, request: Request):
    """创建自定义规则"""
    get_current_user(request)
    rule.built_in = False
    rule.status = "enabled"
    DEFAULT_RULES.append(rule)
    rules_storage[rule.id] = {"status": "enabled"}
    return {"rule": rule.dict(), "message": "自定义规则创建成功"}


@router.delete("/{rule_id}")
async def delete_custom_rule(rule_id: str, request: Request):
    """删除自定义规则"""
    get_current_user(request)
    global DEFAULT_RULES
    rule = next((r for r in DEFAULT_RULES if r.id == rule_id and not r.built_in), None)
    if not rule:
        return {"error": "规则不存在或无法删除内置规则"}, 404

    DEFAULT_RULES = [r for r in DEFAULT_RULES if r.id != rule_id]
    if rule_id in rules_storage:
        del rules_storage[rule_id]

    return {"message": "规则删除成功"}
