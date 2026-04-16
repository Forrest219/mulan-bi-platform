"""DDL 检查 API
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from services.ddl_checker.parser import DDLParser, RegexTimeoutError
from services.ddl_checker.validator import DDLValidator
from services.rules.models import RuleConfigDatabase

router = APIRouter()

# DDL 文本最大长度 64KB（65,536 字节）— ReDoS 防护
MAX_DDL_TEXT_LENGTH = 65536


class DDLCheckRequest(BaseModel):
    """DDL 检查请求"""

    ddl_text: str = Field(
        ...,
        max_length=MAX_DDL_TEXT_LENGTH,
        description=f"CREATE TABLE SQL 语句，最大长度 {MAX_DDL_TEXT_LENGTH} 字节"
    )
    db_type: str = "mysql"
    scene_type: str = "ALL"


class CheckIssue(BaseModel):
    """检查问题"""

    rule_id: str
    risk_level: str
    object_type: str
    object_name: str
    description: str
    suggestion: str


class DDLCheckResponse(BaseModel):
    """DDL 检查响应（统一响应结构）"""

    code: str
    message: str
    trace_id: str
    data: dict


def _violation_to_issue(v) -> CheckIssue:
    """将 Violation 转换为 CheckIssue"""
    level_map = {"error": "High", "warning": "Medium", "info": "Low"}
    return CheckIssue(
        rule_id=v.rule_name,
        risk_level=level_map.get(v.level.value, "Low"),
        object_type=v.column_name and "column" or "table",
        object_name=v.column_name or v.table_name,
        description=v.message,
        suggestion=v.suggestion or ""
    )


def _build_response(code: str, message: str, data: dict, trace_id: str) -> DDLCheckResponse:
    """构建统一响应结构"""
    return DDLCheckResponse(
        code=code,
        message=message,
        trace_id=trace_id,
        data=data
    )


@router.post("/check", dependencies=[Depends(get_current_user)])
async def check_ddl(request: DDLCheckRequest):
    """检查 DDL 语句

    - **ddl_text**: CREATE TABLE SQL 语句，最大 64KB
    - **db_type**: 数据库类型 (mysql/sqlserver)
    - **scene_type**: 业务场景（ODS/DWD/ADS/ALL），用于差异化评分
    """
    trace_id = str(uuid.uuid4())[:12]

    # 长度检查（ReDoS 防护第一道防线）
    if len(request.ddl_text.encode("utf-8")) > MAX_DDL_TEXT_LENGTH:
        return _build_response(
            code="DDL_004",
            message=f"ddl_text 超过最大长度限制 ({MAX_DDL_TEXT_LENGTH} 字节)",
            trace_id=trace_id,
            data={"passed": False, "score": 0, "summary": {}, "issues": [], "executable": False}
        )

    # 解析（双引擎：正则优先 + AST 回退）
    parser = DDLParser()
    try:
        table_info, parse_mode = parser.parse_create_table(request.ddl_text)
    except RegexTimeoutError:
        return _build_response(
            code="DDL_005",
            message="正则解析超时（200ms），已尝试 AST 回退",
            trace_id=trace_id,
            data={"passed": False, "score": 0, "summary": {}, "issues": [], "executable": False}
        )

    if not table_info:
        return _build_response(
            code="DDL_001",
            message="无法解析 DDL 语句",
            trace_id=trace_id,
            data={
                "passed": False,
                "score": 0,
                "summary": {"High": 0, "Medium": 0, "Low": 0},
                "issues": [{
                    "rule_id": "PARSE_ERROR",
                    "risk_level": "High",
                    "object_type": "table",
                    "object_name": "",
                    "description": "无法解析 DDL 语句",
                    "suggestion": "请检查 CREATE TABLE 语法是否正确"
                }],
                "executable": False,
                "parse_mode": parse_mode or "none",
                "scene_type": request.scene_type
            }
        )

    # 验证（支持场景化评分）
    validator = DDLValidator(scene_type=request.scene_type, db_type=request.db_type)
    violations = validator.validate_table(table_info)
    score, summary = validator.calculate_score(violations)

    executable = score >= 60 and not any(v.level.value == "error" for v in violations)
    passed = executable and score >= 80

    return _build_response(
        code="DDL_000",
        message="检查完成",
        trace_id=trace_id,
        data={
            "passed": passed,
            "score": score,
            "summary": summary,
            "issues": [_violation_to_issue(v).model_dump() for v in violations],
            "executable": executable,
            "parse_mode": parse_mode or "unknown",
            "scene_type": request.scene_type
        }
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
