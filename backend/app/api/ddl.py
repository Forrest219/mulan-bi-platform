"""
DDL 检查 API
"""
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from typing import Optional, List

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from ddl_checker.parser import DDLParser
from ddl_checker.validator import DDLValidator
from app.core.dependencies import get_current_user

router = APIRouter()

# 规则配置文件路径
RULES_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "rules.yaml"
validator = DDLValidator(str(RULES_CONFIG_PATH))


class DDLCheckRequest(BaseModel):
    """DDL 检查请求"""
    ddl_text: str
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

    - **ddl_text**: CREATE TABLE SQL 语句
    - **db_type**: 数据库类型 (mysql/sqlserver)
    """
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
    """获取当前启用的规则列表（从 rules.yaml）"""
    import yaml
    with open(RULES_CONFIG_PATH, "r", encoding="utf-8") as f:
        rules_config = yaml.safe_load(f)

    rules = []
    rule_id = 1

    sections = [
        ("table_naming", "表命名规范"),
        ("column_naming", "字段命名规范"),
        ("data_type", "数据类型规范"),
        ("primary_key", "主键规范"),
        ("index", "索引规范"),
        ("comment", "注释规范"),
        ("timestamp", "时间戳规范"),
        ("soft_delete", "软删除规范"),
    ]

    for section, name in sections:
        if rules_config.get(section, {}).get("enabled", True):
            risk = "High" if section in ("table_naming", "column_naming", "primary_key", "timestamp") else "Medium"
            rules.append({"rule_id": f"RULE_{rule_id:03d}", "name": name, "risk_level": risk})
            rule_id += 1

    return {"rules": rules, "total": len(rules)}
