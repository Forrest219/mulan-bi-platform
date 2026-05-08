"""Token 消耗统计 API（管理员专用）"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.dependencies import get_current_user

router = APIRouter(tags=["Token 统计"])


def _require_admin(request: Request) -> dict:
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail={"error_code": "AUTH_403", "message": "需要管理员权限"},
        )
    return user


@router.get("/summary")
async def get_token_summary(request: Request):
    """今日 Token 消耗概览：总量 + 模型分布 + Top 5 用户"""
    _require_admin(request)

    today = date.today()
    tomorrow = today + timedelta(days=1)
    params = {"today": today.isoformat(), "tomorrow": tomorrow.isoformat()}

    session = SessionLocal()
    try:
        row = session.execute(
            text("""
                SELECT
                    COALESCE(SUM(total_tokens), 0),
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0)
                FROM ai_token_usage_logs
                WHERE created_at >= CAST(:today AS date) AND created_at < CAST(:tomorrow AS date)
            """),
            params,
        ).fetchone()

        today_stats = {
            "total_tokens": int(row[0]),
            "prompt_tokens": int(row[1]),
            "completion_tokens": int(row[2]),
        }

        model_rows = session.execute(
            text("""
                SELECT model, provider, COALESCE(SUM(total_tokens), 0) AS total
                FROM ai_token_usage_logs
                WHERE created_at >= CAST(:today AS date) AND created_at < CAST(:tomorrow AS date)
                GROUP BY model, provider
                ORDER BY total DESC
                LIMIT 10
            """),
            params,
        ).fetchall()

        grand_total = today_stats["total_tokens"] or 1
        by_model = [
            {
                "model": r[0],
                "provider": r[1],
                "total_tokens": int(r[2]),
                "percentage": round(int(r[2]) / grand_total * 100, 1),
            }
            for r in model_rows
        ]

        top_rows = session.execute(
            text("""
                SELECT
                    l.user_id,
                    COALESCE(u.display_name, u.username, '系统') AS username,
                    COALESCE(SUM(l.total_tokens), 0) AS total
                FROM ai_token_usage_logs l
                LEFT JOIN auth_users u ON l.user_id = u.id
                WHERE l.created_at >= CAST(:today AS date) AND l.created_at < CAST(:tomorrow AS date)
                GROUP BY l.user_id, u.display_name, u.username
                ORDER BY total DESC
                LIMIT 5
            """),
            params,
        ).fetchall()

        top_users = [
            {"user_id": r[0], "username": r[1], "total_tokens": int(r[2])}
            for r in top_rows
        ]

        return {"today": today_stats, "by_model": by_model, "top_users": top_users}
    finally:
        session.close()


@router.get("/users")
async def get_token_by_user(
    request: Request,
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
):
    """用户 Token 消耗明细（支持时间段筛选，默认近 30 天）"""
    _require_admin(request)

    today = date.today()
    start = date.fromisoformat(start_date) if start_date else today - timedelta(days=29)
    end = date.fromisoformat(end_date) + timedelta(days=1) if end_date else today + timedelta(days=1)

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
                WHERE l.created_at >= CAST(:start AS date) AND l.created_at < CAST(:end AS date)
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
