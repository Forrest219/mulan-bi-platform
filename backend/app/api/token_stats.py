"""Token 消耗统计 API（管理员专用）"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Query, Request
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.dependencies import get_current_user

router = APIRouter(tags=["Token 统计"])


def _require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if user.get("role") != "admin":
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail={"error_code": "AUTH_403", "message": "需要管理员权限"},
        )
    return user


def _date_range(days: int) -> tuple[date, date]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    end = today
    return start, end


def _calc_trend_pct(current: int, previous: int) -> Optional[float]:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


@router.get("/summary")
async def get_token_summary(
    request: Request,
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD，默认当日"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD，默认当日"),
):
    """Token 消耗概览：汇总 + 模型分布 + Top 5 用户，支持自定义时间范围"""
    _require_admin(request)

    today = date.today()
    end = date.fromisoformat(end_date) if end_date else today
    start = date.fromisoformat(start_date) if start_date else today
    period_days = (end - start).days + 1

    # 上期区间（等长向前）
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    session = SessionLocal()
    try:
        # 本期汇总
        cur_row = session.execute(
            text("""
                SELECT
                    COALESCE(SUM(total_tokens), 0),
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0)
                FROM ai_token_usage_logs
                WHERE created_at >= CAST(:start AS date) AND created_at < CAST(:end AS date) + INTERVAL '1 day'
            """),
            {"start": start.isoformat(), "end": end.isoformat()},
        ).fetchone()

        # 上期汇总
        prev_row = session.execute(
            text("""
                SELECT
                    COALESCE(SUM(total_tokens), 0),
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0)
                FROM ai_token_usage_logs
                WHERE created_at >= CAST(:start AS date) AND created_at < CAST(:end AS date) + INTERVAL '1 day'
            """),
            {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        ).fetchone()

        cur_total, cur_prompt, cur_completion = int(cur_row[0]), int(cur_row[1]), int(cur_row[2])
        prev_total, prev_prompt, prev_completion = int(prev_row[0]), int(prev_row[1]), int(prev_row[2])

        summary = {
            "total_tokens": cur_total,
            "prompt_tokens": cur_prompt,
            "completion_tokens": cur_completion,
            "total_trend_pct": _calc_trend_pct(cur_total, prev_total),
            "prompt_trend_pct": _calc_trend_pct(cur_prompt, prev_prompt),
            "completion_trend_pct": _calc_trend_pct(cur_completion, prev_completion),
        }

        # 模型分布（按本期统计）
        grand_total = cur_total or 1
        model_rows = session.execute(
            text("""
                SELECT model, provider, COALESCE(SUM(total_tokens), 0) AS total
                FROM ai_token_usage_logs
                WHERE created_at >= CAST(:start AS date) AND created_at < CAST(:end AS date) + INTERVAL '1 day'
                GROUP BY model, provider
                ORDER BY total DESC
                LIMIT 10
            """),
            {"start": start.isoformat(), "end": end.isoformat()},
        ).fetchall()

        by_model = [
            {
                "model": r[0],
                "provider": r[1],
                "total_tokens": int(r[2]),
                "percentage": round(int(r[2]) / grand_total * 100, 1),
            }
            for r in model_rows
        ]

        # Top 5 用户
        top_rows = session.execute(
            text("""
                SELECT
                    l.user_id,
                    COALESCE(u.display_name, u.username, '系统') AS username,
                    COALESCE(SUM(l.total_tokens), 0) AS total
                FROM ai_token_usage_logs l
                LEFT JOIN auth_users u ON l.user_id = u.id
                WHERE l.created_at >= CAST(:start AS date) AND l.created_at < CAST(:end AS date) + INTERVAL '1 day'
                GROUP BY l.user_id, u.display_name, u.username
                ORDER BY total DESC
                LIMIT 5
            """),
            {"start": start.isoformat(), "end": end.isoformat()},
        ).fetchall()

        top_users = [
            {"user_id": r[0], "username": r[1], "total_tokens": int(r[2])}
            for r in top_rows
        ]

        return {"summary": summary, "by_model": by_model, "top_users": top_users}
    finally:
        session.close()


@router.get("/trend")
async def get_token_trend(
    request: Request,
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD，默认近7天"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD，默认当日"),
):
    """每日 Token 消耗趋势（原始数据，不做补零）"""
    _require_admin(request)

    today = date.today()
    end = date.fromisoformat(end_date) if end_date else today
    start = date.fromisoformat(start_date) if start_date else (today - timedelta(days=6))

    session = SessionLocal()
    try:
        rows = session.execute(
            text("""
                SELECT
                    DATE(created_at) AS day,
                    COALESCE(SUM(total_tokens), 0),
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0)
                FROM ai_token_usage_logs
                WHERE created_at >= CAST(:start AS date) AND created_at < CAST(:end AS date) + INTERVAL '1 day'
                GROUP BY DATE(created_at)
                ORDER BY day ASC
            """),
            {"start": start.isoformat(), "end": end.isoformat()},
        ).fetchall()

        trend = [
            {
                "date": r[0].isoformat() if r[0] else None,
                "total_tokens": int(r[1]) if r[1] is not None else None,
                "prompt_tokens": int(r[2]) if r[2] is not None else None,
                "completion_tokens": int(r[3]) if r[3] is not None else None,
            }
            for r in rows
        ]
        return trend
    finally:
        session.close()


@router.get("/users")
async def get_token_by_user(
    request: Request,
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD，默认近30天"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD，默认当日"),
):
    """用户 Token 消耗明细（支持时间段筛选）"""
    _require_admin(request)

    today = date.today()
    end = date.fromisoformat(end_date) if end_date else today
    start = date.fromisoformat(start_date) if start_date else (today - timedelta(days=29))

    session = SessionLocal()
    try:
        rows = session.execute(
            text("""
                SELECT
                    l.user_id,
                    COALESCE(u.display_name, u.username, '系统') AS username,
                    COALESCE(SUM(l.total_tokens), 0)      AS total_tokens,
                    COALESCE(SUM(l.prompt_tokens), 0)     AS prompt_tokens,
                    COALESCE(SUM(l.completion_tokens), 0) AS completion_tokens,
                    COUNT(*)                               AS call_count
                FROM ai_token_usage_logs l
                LEFT JOIN auth_users u ON l.user_id = u.id
                WHERE l.created_at >= CAST(:start AS date) AND l.created_at < CAST(:end AS date) + INTERVAL '1 day'
                GROUP BY l.user_id, u.display_name, u.username
                ORDER BY total_tokens DESC
            """),
            {"start": start.isoformat(), "end": end.isoformat()},
        ).fetchall()

        users = [
            {
                "user_id": r[0],
                "username": r[1],
                "total_tokens": int(r[2]),
                "prompt_tokens": int(r[3]),
                "completion_tokens": int(r[4]),
                "call_count": int(r[5]),
            }
            for r in rows
        ]
        return {"users": users}
    finally:
        session.close()