"""数据质量监控 API

遵循 Spec 15 v1.1 §4 API 设计：
- /api/governance/quality/rules    - 规则 CRUD
- /api/governance/quality/execute  - 手动触发检测
- /api/governance/quality/results   - 检测结果查询
- /api/governance/quality/scores   - 质量评分查询
- /api/governance/quality/scores/trend - 评分趋势
- /api/governance/quality/dashboard - 质量看板

认证：规则管理（admin/data_admin）；查询（已认证 analyst 及以上）
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles
from services.datasources.models import DataSourceDatabase
from services.governance.database import QualityDatabase
from services.tasks.quality_tasks import execute_quality_rules_task

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== 请求/响应模型 ====================

class CreateRuleRequest(BaseModel):
    """创建质量规则请求模型"""

    name: str = Field(..., max_length=256)
    description: Optional[str] = None
    datasource_id: int
    table_name: str = Field(..., max_length=128)
    field_name: Optional[str] = Field(None, max_length=128)
    rule_type: str = Field(..., max_length=32)
    operator: str = Field(default="lte", max_length=16)
    threshold: dict = Field(default_factory=dict)
    severity: str = Field(default="MEDIUM", max_length=16)
    execution_mode: str = Field(default="scheduled", max_length=16)
    cron: Optional[str] = Field(None, max_length=64)
    custom_sql: Optional[str] = None
    tags_json: Optional[list] = None


class UpdateRuleRequest(BaseModel):
    """更新质量规则请求模型"""

    name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    rule_type: Optional[str] = Field(None, max_length=32)
    operator: Optional[str] = Field(None, max_length=16)
    threshold: Optional[dict] = None
    severity: Optional[str] = Field(None, max_length=16)
    execution_mode: Optional[str] = Field(None, max_length=16)
    cron: Optional[str] = Field(None, max_length=64)
    custom_sql: Optional[str] = None
    enabled: Optional[bool] = None
    tags_json: Optional[list] = None


class ExecuteRequest(BaseModel):
    """手动触发质量检测请求模型"""

    datasource_id: Optional[int] = None
    table_name: Optional[str] = None
    rule_ids: Optional[list[int]] = None


# ==================== 规则 CRUD ====================

@router.post("/rules")
async def create_rule(
    body: CreateRuleRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """创建质量规则 - admin/data_admin"""

    qdb = QualityDatabase()

    # 验证数据源存在且活跃
    ds_db = DataSourceDatabase()
    ds = ds_db.get(db, body.datasource_id)
    if not ds or not ds.is_active:
        raise HTTPException(status_code=400, detail="GOV_010: 数据源不存在或未激活")

    # 验证规则类型
    valid_rule_types = [
        "null_rate", "not_null", "row_count", "duplicate_rate", "unique_count",
        "referential", "cross_field", "value_range", "freshness", "latency",
        "format_regex", "enum_check", "custom_sql",
    ]
    if body.rule_type not in valid_rule_types:
        raise HTTPException(status_code=400, detail=f"GOV_003: 不支持的规则类型 {body.rule_type}")

    # 验证 cron 表达式（basic validation）
    if body.execution_mode == "scheduled" and body.cron:
        _validate_cron(body.cron)

    # 验证自定义 SQL
    if body.rule_type == "custom_sql" and body.custom_sql:
        from services.governance.engine import validate_custom_sql
        if not validate_custom_sql(body.custom_sql):
            raise HTTPException(status_code=400, detail="GOV_005: 自定义 SQL 必须为 SELECT 语句且不包含禁止关键字")

    # 检查重复规则
    if qdb.rule_exists(db, body.datasource_id, body.table_name, body.field_name, body.rule_type):
        raise HTTPException(status_code=409, detail="GOV_006: 同一数据源+表+字段+规则类型已存在相同规则")

    # 非 admin 只能为自己的数据源创建规则
    if current_user["role"] != "admin" and ds.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="GOV_001: 无权为此数据源创建规则")

    rule = qdb.create_rule(
        db,
        name=body.name,
        description=body.description,
        datasource_id=body.datasource_id,
        table_name=body.table_name,
        field_name=body.field_name,
        rule_type=body.rule_type,
        operator=body.operator,
        threshold=body.threshold,
        severity=body.severity,
        execution_mode=body.execution_mode,
        cron=body.cron,
        custom_sql=body.custom_sql,
        enabled=True,
        tags_json=body.tags_json,
        created_by=current_user["id"],
    )

    return {"rule": rule.to_dict(), "message": "质量规则创建成功"}


@router.get("/rules")
async def list_rules(
    request: Request,
    datasource_id: Optional[int] = None,
    table_name: Optional[str] = None,
    enabled: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """规则列表（支持筛选）- 已认证"""
    get_current_user(request)
    qdb = QualityDatabase()
    return qdb.list_rules(
        db,
        datasource_id=datasource_id,
        table_name=table_name,
        enabled=enabled,
        page=page,
        page_size=page_size,
    )


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: int, request: Request, db: Session = Depends(get_db)):
    """规则详情 - 已认证"""
    get_current_user(request)
    qdb = QualityDatabase()
    rule = qdb.get_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="GOV_001: 质量规则不存在")
    return rule.to_dict()


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    body: UpdateRuleRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """更新规则 - admin/data_admin"""
    qdb = QualityDatabase()
    rule = qdb.get_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="GOV_001: 质量规则不存在")

    # 验证 cron
    if body.cron:
        _validate_cron(body.cron)

    # 验证自定义 SQL
    if body.custom_sql:
        from services.governance.engine import validate_custom_sql
        if not validate_custom_sql(body.custom_sql):
            raise HTTPException(status_code=400, detail="GOV_005: 自定义 SQL 必须为 SELECT 语句")

    # 禁止修改的字段
    update_fields = body.model_dump(exclude_unset=True, exclude={"id", "created_by", "datasource_id", "table_name", "field_name", "rule_type"})
    update_fields["updated_by"] = current_user["id"]

    qdb.update_rule(db, rule_id, **update_fields)
    updated_rule = qdb.get_rule(db, rule_id)
    return {"rule": updated_rule.to_dict(), "message": "质量规则更新成功"}


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """删除规则 - admin/data_admin"""
    qdb = QualityDatabase()
    if not qdb.get_rule(db, rule_id):
        raise HTTPException(status_code=404, detail="GOV_001: 质量规则不存在")

    qdb.delete_rule(db, rule_id)
    return {"message": "质量规则删除成功"}


@router.put("/rules/{rule_id}/toggle")
async def toggle_rule(
    rule_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """启用/禁用规则 - admin/data_admin"""
    qdb = QualityDatabase()
    new_state = qdb.toggle_rule(db, rule_id)
    if new_state is None:
        raise HTTPException(status_code=404, detail="GOV_001: 质量规则不存在")

    return {"rule_id": rule_id, "enabled": new_state, "message": f"规则已{'启用' if new_state else '禁用'}"}


# ==================== 检测执行 ====================

@router.post("/execute")
async def execute_quality_checks(
    body: ExecuteRequest,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """手动触发质量检测 - admin/data_admin"""
    datasource_id = body.datasource_id
    rule_ids = body.rule_ids

    # 如果指定了 rule_ids，不需要 datasource_id
    if not rule_ids and not datasource_id:
        raise HTTPException(status_code=400, detail="GOV_002: 规则 ID 或数据源 ID 必须提供其一")

    # 验证数据源
    if datasource_id:
        ds_db = DataSourceDatabase()
        ds = ds_db.get(db, datasource_id)
        if not ds or not ds.is_active:
            raise HTTPException(status_code=400, detail="GOV_010: 数据源不存在或未激活")

        # 非 admin 只能操作自己的数据源
        if current_user["role"] != "admin" and ds.owner_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="GOV_001: 无权操作此数据源")

        # 构建只读连接配置
        from app.core.crypto import get_datasource_crypto
        crypto = get_datasource_crypto()
        password = crypto.decrypt(ds.password_encrypted)
        db_config = {
            "db_type": ds.db_type,
            "host": ds.host,
            "port": ds.port,
            "user": ds.username,
            "password": password,
            "database": ds.database_name,
            "readonly": True,
        }
    else:
        db_config = None

    # 异步执行
    task = execute_quality_rules_task.delay(datasource_id, rule_ids, db_config)

    return {
        "task_id": task.id,
        "message": "质量检测已启动",
    }


@router.post("/execute/rule/{rule_id}")
async def execute_single_rule(
    rule_id: int,
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
    db: Session = Depends(get_db),
):
    """执行单条规则 - admin/data_admin"""
    qdb = QualityDatabase()
    rule = qdb.get_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="GOV_001: 质量规则不存在")

    ds_db = DataSourceDatabase()
    ds = ds_db.get(db, rule.datasource_id)
    if not ds or not ds.is_active:
        raise HTTPException(status_code=400, detail="GOV_010: 数据源不存在或未激活")

    from app.core.crypto import get_datasource_crypto
    crypto = get_datasource_crypto()
    password = crypto.decrypt(ds.password_encrypted)
    db_config = {
        "db_type": ds.db_type,
        "host": ds.host,
        "port": ds.port,
        "user": ds.username,
        "password": password,
        "database": ds.database_name,
        "readonly": True,
    }

    task = execute_quality_rules_task.delay(rule.datasource_id, [rule_id], db_config)

    return {"task_id": task.id, "message": "规则检测已启动"}


# ==================== 检测结果 ====================

@router.get("/results")
async def list_results(
    request: Request,
    datasource_id: Optional[int] = None,
    rule_id: Optional[int] = None,
    passed: Optional[bool] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """检测结果列表 - 已认证"""
    get_current_user(request)

    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None

    qdb = QualityDatabase()
    return qdb.list_results(
        db,
        datasource_id=datasource_id,
        rule_id=rule_id,
        passed=passed,
        start_date=start_dt,
        end_date=end_dt,
        page=page,
        page_size=page_size,
    )


@router.get("/results/latest")
async def get_latest_results(request: Request, datasource_id: Optional[int] = None, db: Session = Depends(get_db)):
    """各规则最新检测结果 - 已认证"""
    get_current_user(request)
    qdb = QualityDatabase()
    results = qdb.get_latest_results(db, datasource_id=datasource_id)
    return {"results": [r.to_dict() for r in results]}


# ==================== 质量评分 ====================

@router.get("/scores")
async def get_scores(
    request: Request,
    datasource_id: int,
    scope_type: Optional[str] = None,
    scope_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """质量评分查询（最新评分）- 已认证"""
    get_current_user(request)
    qdb = QualityDatabase()
    scores = qdb.get_latest_scores(db, datasource_id=datasource_id, scope_type=scope_type, scope_name=scope_name)
    return {"scores": [s.to_dict() for s in scores]}


@router.get("/scores/trend")
async def get_score_trend(
    request: Request,
    datasource_id: int,
    scope_type: Optional[str] = None,
    scope_name: Optional[str] = None,
    days: int = 30,
    db: Session = Depends(get_db),
):
    """评分趋势（近 N 天历史）- 已认证"""
    get_current_user(request)
    qdb = QualityDatabase()
    trend = qdb.get_score_trend(db, datasource_id=datasource_id, scope_type=scope_type, scope_name=scope_name, days=days)
    return {
        "trend": trend,
        "datasource_id": datasource_id,
        "scope_type": scope_type or "datasource",
        "days": days,
    }


# ==================== 质量看板 ====================

@router.get("/dashboard")
async def get_dashboard(request: Request, db: Session = Depends(get_db)):
    """质量看板数据 - 已认证"""
    get_current_user(request)
    qdb = QualityDatabase()

    summary = qdb.get_dashboard_summary(db)
    top_failures = qdb.get_top_failures(db, limit=10)

    # 各数据源最新评分
    from sqlalchemy import func

    from app.core.database import SessionLocal
    from services.governance.models import QualityScore

    s = SessionLocal()
    try:
        latest_subq = (
            s.query(
                QualityScore.datasource_id,
                func.max(QualityScore.id).label("max_id"),
            )
            .group_by(QualityScore.datasource_id)
            .subquery()
        )
        latest_scores = (
            s.query(QualityScore)
            .join(latest_subq, QualityScore.id == latest_subq.c.max_id)
            .all()
        )

        from services.datasources.models import DataSource
        datasource_scores = []
        for sc in latest_scores:
            ds = s.query(DataSource).filter(DataSource.id == sc.datasource_id).first()
            # 计算趋势
            trend = qdb.get_score_trend(db, sc.datasource_id, days=7)
            trend_direction = "up" if len(trend) >= 2 and trend[-1]["overall_score"] > trend[0]["overall_score"] else "down"

            datasource_scores.append({
                "datasource_id": sc.datasource_id,
                "datasource_name": ds.name if ds else sc.datasource_id,
                "overall_score": sc.overall_score,
                "trend": trend_direction,
            })

        return {
            "summary": summary,
            "datasource_scores": datasource_scores,
            "top_failures": top_failures,
        }
    finally:
        s.close()


# ==================== 工具函数 ====================

def _validate_cron(cron: str):
    """验证 Cron 表达式基本格式"""
    import re
    pattern = r'^(\S+\s+){4}\S+$'  # 5 字段
    if not re.match(pattern, cron.strip()):
        raise HTTPException(status_code=400, detail="GOV_004: Cron 表达式格式无效")
