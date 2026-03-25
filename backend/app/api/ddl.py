"""
DDL 检查 API
"""
from pydantic import BaseModel
from fastapi import APIRouter
from typing import Optional, List

# 导入 ddl_check_engine
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "modules" / "ddl_check_engine"))

from ddl_check_engine import DDLCheckEngine

router = APIRouter()
engine = DDLCheckEngine()


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


@router.post("/check", response_model=DDLCheckResponse)
async def check_ddl(request: DDLCheckRequest):
    """
    检查 DDL 语句

    - **ddl_text**: CREATE TABLE SQL 语句
    - **db_type**: 数据库类型 (mysql/sqlserver)
    """
    result = engine.check(request.ddl_text, request.db_type)

    return DDLCheckResponse(
        passed=result.passed,
        score=result.score,
        summary=result.summary,
        issues=[CheckIssue(**issue) for issue in result.issues],
        executable=result.executable
    )


@router.get("/rules")
async def get_rules():
    """获取当前启用的规则列表"""
    return {
        "rules": [
            {"rule_id": "RULE_001", "name": "表命名规范", "risk_level": "High"},
            {"rule_id": "RULE_002", "name": "字段必须有注释", "risk_level": "High"},
            {"rule_id": "RULE_003", "name": "金额字段类型", "risk_level": "Medium"},
            {"rule_id": "RULE_004", "name": "必须包含 create_time", "risk_level": "High"},
            {"rule_id": "RULE_005", "name": "必须包含 update_time", "risk_level": "High"},
        ],
        "total": 5
    }
