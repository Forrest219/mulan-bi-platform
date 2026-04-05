"""
DDL 检查 API
"""
from pathlib import Path
from typing import Optional, List

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from services.ddl_checker.parser import DDLParser
from services.ddl_checker.validator import DDLValidator
from services.rules.models import RuleConfigDatabase
from app.core.dependencies import get_current_user

router = APIRouter()

# DDL 文本最大长度 64KB（65,536 字节）— ReDoS 防护
MAX_DDL_TEXT_LENGTH = 65536

# 懒加载 DDLValidator，规则从数据库读取
_validator: Optional[DDLValidator] = None


def get_validator() -> DDLValidator:
    """获取 DDLValidator 单例"""
    global _validator
    if _validator is None:
        _validator = DDLValidator()
    return _validator


class DDLCheckRequest(BaseModel):
    """DDL 检查请求"""
    ddl_text: str = Field(
        ...,
        max_length=MAX_DDL_TEXT_LENGTH,
        description=f"CREATE TABLE SQL 语句，最大长度 {MAX_DDL_TEXT_LENGTH} 字节"
    )
    db_type: str = "mysql"


class CheckIssue(BaseModel):
    """检查问题"""
    rule_id: str
    risk_level: str
    object_type: str
    object_name: str
    description: str
    suggestion: str


class DDLCheckResponse(BaseModel):
    """DDL 检查响应"""
    passed: bool
    score: int
    summary: dict
    issues: List[CheckIssue]
    executable: bool


def _violation_to_issue(v) -> CheckIssue:
    """将 Violation 转换为 CheckIssue"""
    # 映射 ViolationLevel 到字符串 risk_level
    level_map = {"error": "High", "warning": "Medium", "info": "Low"}
    return CheckIssue(
        rule_id=v.rule_name,
        risk_level=level_map.get(v.level.value, "Low"),
        object_type=v.column_name and "column" or "table",
        object_name=v.column_name or v.table_name,
        description=v.message,
        suggestion=v.suggestion or ""
    )


def _calculate_score(violations) -> tuple:
    """计算评分和汇总"""
    high = sum(1 for v in violations if v.level.value == "error")
    medium = sum(1 for v in violations if v.level.value == "warning")
    low = sum(1 for v in violations if v.level.value == "info")
    score = 100 - high * 20 - medium * 5 - low * 1
    score = max(0, min(100, score))
    summary = {"High": high, "Medium": medium, "Low": low}
    return score, summary


@router.post("/check", response_model=DDLCheckResponse, dependencies=[Depends(get_current_user)])
async def check_ddl(request: DDLCheckRequest):
    """
    检查 DDL 语句

    - **ddl_text**: CREATE TABLE SQL 语句，最大 64KB
    - **db_type**: 数据库类型 (mysql/sqlserver)
    """
    # 长度检查（ReDoS 防护第一道防线）
    if len(request.ddl_text.encode("utf-8")) > MAX_DDL_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "DDL_004",
                "message": f"ddl_text 超过最大长度限制 ({MAX_DDL_TEXT_LENGTH} 字节)"
            }
        )

    parser = DDLParser()
    table_info = parser.parse_create_table(request.ddl_text)

    if not table_info:
        return DDLCheckResponse(
            passed=False,
            score=0,
            summary={"High": 0, "Medium": 0, "Low": 0},
            issues=[CheckIssue(
                rule_id="PARSE_ERROR",
                risk_level="High",
                object_type="table",
                object_name="",
                description="无法解析 DDL 语句",
                suggestion="请检查 CREATE TABLE 语法是否正确"
            )],
            executable=False
        )

    validator = get_validator()
    violations = validator.validate_table(table_info)
    score, summary = _calculate_score(violations)

    executable = score >= 60 and not any(v.level.value == "error" for v in violations)
    passed = executable and score >= 80

    return DDLCheckResponse(
        passed=passed,
        score=score,
        summary=summary,
        issues=[_violation_to_issue(v) for v in violations],
        executable=executable
    )


@router.get("/rules", dependencies=[Depends(get_current_user)])
async def get_rules():
    """获取当前启用的规则列表（从数据库 bi_rule_configs 加载）"""
    rule_db = RuleConfigDatabase()
    all_rules = rule_db.get_all()

    rules = []
    for rule in all_rules:
        if rule.enabled:
            rules.append({
                "rule_id": rule.rule_id,
                "name": rule.name,
                "risk_level": rule.level,
            })

    return {"rules": rules, "total": len(rules)}
