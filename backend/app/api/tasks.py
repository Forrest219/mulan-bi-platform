"""任务管理 API — Spec 33"""
from datetime import datetime
import logging
import re

from celery.result import AsyncResult
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

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
    "services.tasks.cleanup_tasks.cleanup_old_task_runs",
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
    """启用/禁用调度任务，或更新 cron 表达式"""
    _require_admin(request)

    body = await request.json()
    is_enabled = body.get("is_enabled")
    cron_expr = body.get("cron_expr")

    if is_enabled is None and cron_expr is None:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "TASK_006", "message": "缺少 is_enabled 或 cron_expr 参数"},
        )

    from services.tasks.task_manager import TaskManager

    with SessionLocal() as db:
        tm = TaskManager()

        if cron_expr is not None:
            # Validate cron expression
            try:
                from croniter import croniter
                if not croniter.is_valid(cron_expr):
                    raise HTTPException(
                        status_code=400,
                        detail={"error_code": "TASK_007", "message": f"无效的 cron 表达式: {cron_expr}"},
                    )
            except ImportError:
                pass  # croniter 未安装时跳过校验

            result = tm.update_schedule_cron(db, schedule_key, cron_expr)
            if not result:
                raise HTTPException(
                    status_code=404,
                    detail={"error_code": "TASK_002", "message": "调度任务不存在"},
                )

        if is_enabled is not None:
            result = tm.update_schedule_enabled(db, schedule_key, is_enabled)
            if not result:
                raise HTTPException(
                    status_code=404,
                    detail={"error_code": "TASK_002", "message": "调度任务不存在"},
                )

        return {
            "schedule_key": schedule_key,
            "is_enabled": result.is_enabled,
            "cron_expr": result.cron_expr,
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


# ─── Spec 33 §3.4: 90天清理 dry-run ─────────────────────────────────

@router.get("/cleanup-dry-run")
async def cleanup_dry_run(request: Request):
    """返回待清理的 bi_task_runs 记录数（admin 专用，dry-run 不删除）"""
    _require_admin(request)

    from services.tasks.cleanup_tasks import cleanup_old_task_runs

    result = cleanup_old_task_runs(dry_run=True)
    return result


# ─── 接口：写入种子数据 ──────────────────────────────────────

@router.post("/seed")
async def seed_tasks(request: Request):
    """写入 task 调度种子数据（表结构由 Alembic 迁移 20260508_task_ddl 管理）"""
    _require_admin(request)

    with SessionLocal() as db:
        seed_task_schedules(db)

    return {"message": "种子数据已写入"}


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


# ─── AI 解析 & 预览 ──────────────────────────────────────────

_SYSTEM_PROMPT = """\
你是一个 Cron 表达式生成器。将用户描述的任务执行时间转换为标准 5 字段 Cron 表达式。
字段顺序：分钟 小时 日 月 星期（0=周日）。

规则：
- 只输出 cron 表达式本身，不加任何解释
- 不支持秒级精度，最小粒度为分钟
- 示例：
  "每天凌晨三点" → 0 3 * * *
  "每天零点和中午" → 0 0,12 * * *
  "每周日凌晨三点" → 0 3 * * 0
  "每月1号凌晨3点10分" → 10 3 1 * *
  "工作日上午九点" → 0 9 * * 1-5
  "每15分钟" → */15 * * * *
  "每小时整点" → 0 * * * *\
"""

_CRON_RE = re.compile(r"^\S+\s+\S+\s+\S+\s+\S+\s+\S+$")


@router.post("/parse-cron")
async def parse_cron(request: Request):
    """用 LLM 将自然语言描述解析为 Cron 表达式"""
    _get_user(request)

    body = await request.json()
    description = (body.get("description") or "").strip()
    if not description:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "TASK_008", "message": "描述不能为空"},
        )

    from services.llm.service import llm_service
    result = await llm_service.complete(
        prompt=description,
        system=_SYSTEM_PROMPT,
        timeout=15,
        purpose="default",
    )

    if "error" in result:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "LLM_500", "message": result["error"]},
        )

    raw = result.get("content", "").strip()
    # 从输出中提取第一个匹配的 5 字段 cron（防止 LLM 多输出文字）
    cron_expr = None
    for token in raw.splitlines():
        token = token.strip()
        if _CRON_RE.match(token):
            cron_expr = token
            break
    if not cron_expr:
        # fallback: 取第一行
        cron_expr = raw.splitlines()[0].strip() if raw else ""

    try:
        from croniter import croniter
        if not croniter.is_valid(cron_expr):
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "TASK_009",
                    "message": f"LLM 返回了无效的 cron 表达式：{cron_expr!r}，请重新描述或手动输入",
                },
            )
    except ImportError:
        pass

    from services.tasks.task_manager import _compute_next_run
    next_runs = []
    try:
        from croniter import croniter as _cr
        import datetime as _dt
        it = _cr(cron_expr, _dt.datetime.now())
        for _ in range(3):
            next_runs.append(it.get_next(_dt.datetime).strftime("%Y-%m-%dT%H:%M:%S"))
    except Exception:
        pass

    return {"cron_expr": cron_expr, "next_runs": next_runs}


@router.get("/preview-cron")
async def preview_cron(request: Request, cron_expr: str, n: int = 3):
    """计算 cron 表达式的下次 N 次执行时间（只读，不写库）"""
    _get_user(request)

    if n < 1 or n > 10:
        n = 3

    try:
        from croniter import croniter
        if not croniter.is_valid(cron_expr):
            raise HTTPException(
                status_code=400,
                detail={"error_code": "TASK_007", "message": f"无效的 cron 表达式: {cron_expr}"},
            )
        import datetime as _dt
        it = croniter(cron_expr, _dt.datetime.now())
        next_runs = [it.get_next(_dt.datetime).strftime("%Y-%m-%dT%H:%M:%S") for _ in range(n)]
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "TASK_010", "message": "croniter 未安装"},
        )

    return {"cron_expr": cron_expr, "next_runs": next_runs}