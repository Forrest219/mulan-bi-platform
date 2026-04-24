"""任务管理 API — Spec 33"""
from datetime import datetime
import logging

from celery.result import AsyncResult
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.dependencies import get_current_user
from services.tasks import celery_app
from services.tasks.seed import seed_task_schedules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["tasks"])

# 白名单：仅允许手动触发以下任务
ALLOWED_MANUAL_TASKS = [
    "services.tasks.tableau_tasks.sync_connection_task",
    "services.tasks.dqc_tasks.run_daily_full_cycle",
    "services.tasks.dqc_tasks.partition_maintenance",
    "services.tasks.dqc_tasks.cleanup_old_analyses",
    "services.tasks.api_contract_tasks.sample_asset",
    "services.tasks.api_contract_tasks.run_cycle",
    "services.tasks.api_contract_tasks.compare_snapshots",
]


def _get_user(request: Request):
    """获取当前用户，reject user 角色"""
    user = get_current_user(request)
    if user["role"] == "user":
        raise HTTPException(
            status_code=403,
            detail={"error_code": "TASK_005", "message": "权限不足"},
        )
    return user


def _require_admin(request: Request):
    """仅 admin 可操作"""
    user = get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail={"error_code": "TASK_005", "message": "权限不足"},
        )
    return user


# ─── 执行记录 ────────────────────────────────────────────────

@router.get("/runs")
async def list_runs(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    status: str = None,
    task_name: str = None,
    trigger_type: str = None,
    start_time: str = None,
    end_time: str = None,
):
    """分页查询任务执行历史"""
    _get_user(request)

    if page_size > 100 or page < 1 or page_size < 1:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "TASK_004", "message": "分页参数无效"},
        )

    parsed_start = datetime.fromisoformat(start_time) if start_time else None
    parsed_end = datetime.fromisoformat(end_time) if end_time else None

    from services.tasks.task_manager import TaskManager
    from services.tasks.signals import TASK_LABELS

    with SessionLocal() as db:
        result = TaskManager().list_runs(
            db,
            page=page,
            page_size=page_size,
            status=status,
            task_name=task_name,
            trigger_type=trigger_type,
            start_time=parsed_start,
            end_time=parsed_end,
        )
        for item in result.get("items", []):
            item["task_label"] = TASK_LABELS.get(item.get("task_name", ""))
        return result


@router.get("/runs/{run_id}")
async def get_run(run_id: int, request: Request):
    """获取单条执行记录详情"""
    _get_user(request)

    from services.tasks.task_manager import TaskManager
    from services.tasks.signals import TASK_LABELS

    with SessionLocal() as db:
        run = TaskManager().get_run(db, run_id)
        if not run:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "TASK_001", "message": "执行记录不存在"},
            )
        run_dict = run.to_dict()
        run_dict["task_label"] = TASK_LABELS.get(run_dict.get("task_name", ""))
        return run_dict


# ─── 调度配置 ────────────────────────────────────────────────

@router.get("/schedules")
async def list_schedules(request: Request):
    """查询所有调度任务配置"""
    _get_user(request)

    from services.tasks.task_manager import TaskManager
    from services.tasks.signals import TASK_LABELS

    with SessionLocal() as db:
        schedules = TaskManager().list_schedules(db)
        for item in schedules:
            item["task_label"] = TASK_LABELS.get(item.get("task_name", ""))
        return {"items": schedules, "total": len(schedules)}


@router.patch("/schedules/{schedule_key}")
async def update_schedule_enabled(schedule_key: str, request: Request):
    """启用/禁用调度任务"""
    _require_admin(request)

    body = await request.json()
    is_enabled = body.get("is_enabled")
    if is_enabled is None:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "TASK_006", "message": "缺少 is_enabled 参数"},
        )

    from services.tasks.task_manager import TaskManager

    with SessionLocal() as db:
        result = TaskManager().update_schedule_enabled(db, schedule_key, is_enabled)
        if not result:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "TASK_002", "message": "调度任务不存在"},
            )
        return {
            "schedule_key": schedule_key,
            "is_enabled": result.is_enabled,
            "updated_at": result.updated_at.isoformat() if result.updated_at else None,
        }


# ─── 手动触发 & 统计 ─────────────────────────────────────────

@router.post("/trigger")
async def trigger_task(request: Request):
    """手动触发任务（白名单限制）"""
    _require_admin(request)

    body = await request.json()
    task_name = body.get("task_name")

    if task_name not in ALLOWED_MANUAL_TASKS:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "TASK_003", "message": "不允许手动触发该任务"},
        )

    result = celery_app.send_task(task_name, headers={"trigger_type": "manual"})
    return JSONResponse(
        status_code=202,
        content={
            "celery_task_id": result.id,
            "task_name": task_name,
            "trigger_type": "manual",
            "message": "任务已提交",
        },
    )


@router.get("/stats")
async def get_stats(request: Request, date: str = None):
    """获取任务统计 KPI"""
    _get_user(request)

    from services.tasks.task_manager import TaskManager

    parsed_date = datetime.fromisoformat(date).date() if date else datetime.utcnow().date()

    with SessionLocal() as db:
        return TaskManager().get_stats(db, parsed_date)


# ─── 临时接口：初始化表结构 & 种子数据 ──────────────────────

@router.post("/seed")
async def seed_tasks(request: Request):
    """创建 task 相关表（如不存在）并写入种子调度数据"""
    _require_admin(request)

    migration_sql = """
    CREATE TABLE IF NOT EXISTS bi_task_runs (
        id BIGSERIAL PRIMARY KEY,
        celery_task_id VARCHAR(256),
        task_name VARCHAR(256) NOT NULL,
        task_label VARCHAR(128),
        trigger_type VARCHAR(16) NOT NULL DEFAULT 'beat',
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        started_at TIMESTAMP,
        finished_at TIMESTAMP,
        duration_ms INTEGER,
        result_summary JSONB,
        error_message TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        parent_run_id BIGINT REFERENCES bi_task_runs(id) ON DELETE SET NULL,
        triggered_by BIGINT REFERENCES auth_users(id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        CONSTRAINT chk_trigger_type CHECK (trigger_type IN ('beat', 'manual', 'api')),
        CONSTRAINT chk_status CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled'))
    );

    CREATE TABLE IF NOT EXISTS bi_task_schedules (
        id SERIAL PRIMARY KEY,
        schedule_key VARCHAR(128) UNIQUE NOT NULL,
        task_name VARCHAR(256) NOT NULL,
        description TEXT,
        schedule_expr VARCHAR(256) NOT NULL,
        is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        last_run_at TIMESTAMP,
        last_run_status VARCHAR(16),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_task_runs_task_name_started ON bi_task_runs(task_name, started_at);
    CREATE INDEX IF NOT EXISTS ix_task_runs_status_started ON bi_task_runs(status, started_at);
    CREATE INDEX IF NOT EXISTS ix_task_runs_started_at ON bi_task_runs(started_at);
    CREATE INDEX IF NOT EXISTS ix_task_runs_parent ON bi_task_runs(parent_run_id);
    CREATE INDEX IF NOT EXISTS ix_task_runs_celery_task_id ON bi_task_runs(celery_task_id);
    CREATE INDEX IF NOT EXISTS ix_task_schedules_task_name ON bi_task_schedules(task_name);
    CREATE INDEX IF NOT EXISTS ix_task_schedules_is_enabled ON bi_task_schedules(is_enabled);
    """

    with SessionLocal() as db:
        for stmt in migration_sql.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                db.execute(text(stmt))
        db.commit()

        seed_task_schedules(db)

    return {"message": "表结构已创建，种子数据已写入"}


# ─── 废弃端点（保留原路径避免 404） ─────────────────────────

@router.get("/{task_id}/status")
async def get_task_status(task_id: str, request: Request):
    """
    Legacy: 查询 Celery 任务状态
    Deprecated — 保留以兼容旧前端，未来移除。
    """
    get_current_user(request)
    result = AsyncResult(task_id, app=celery_app)
    response = {"task_id": task_id, "status": result.status}
    if result.ready():
        response["result"] = result.result
    elif result.status == "STARTED":
        response["message"] = "任务执行中"
    elif result.status == "PENDING":
        response["message"] = "任务等待中"
    return response