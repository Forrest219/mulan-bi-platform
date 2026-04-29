"""历史数据清理 Celery 任务

遵循 Spec 15 v1.1 §2.1 数据保留策略：
- bi_quality_results: 保留 90 天
- bi_quality_scores: 保留 90 天（趋势 API 需要）

使用 PostgreSQL 分区表时，DROP 过期的分区是最高效的清理方式。
"""
from datetime import datetime, timedelta
from celery import shared_task

from app.core.database import SessionLocal


@shared_task
def cleanup_expired_quality_results(dry_run: bool = False):
    """
    清理超过 90 天的 bi_quality_results 历史数据。

    PostgreSQL 分区表：DROP 过期的分区（Metadata 操作，性能影响极小）。
    对于非分区表或未建立分区的表，执行 DELETE WHERE executed_at < cutoff。

    Args:
        dry_run: 若为 True，仅返回待清理记录数，不执行删除（冒烟测试用）

    Returns:
        dict: 清理结果摘要
    """
    session = SessionLocal()
    cutoff_date = datetime.utcnow() - timedelta(days=90)

    try:
        from services.governance.models import QualityResult

        # T3.4: dry_run 模式 — 仅计数，不删除
        if dry_run:
            count = (
                session.query(QualityResult)
                .filter(QualityResult.executed_at < cutoff_date)
                .count()
            )
            return {
                "task": "cleanup_expired_quality_results",
                "cutoff_date": cutoff_date.isoformat(),
                "dry_run": True,
                "pending_delete_count": count,
                "status": "dry_run_completed",
            }

        deleted_count = (
            session.query(QualityResult)
            .filter(QualityResult.executed_at < cutoff_date)
            .delete(synchronize_session=False)
        )

        session.commit()

        return {
            "task": "cleanup_expired_quality_results",
            "cutoff_date": cutoff_date.isoformat(),
            "deleted_count": deleted_count,
            "status": "completed",
        }

    except Exception as e:
        session.rollback()
        return {
            "task": "cleanup_expired_quality_results",
            "status": "failed",
            "error": str(e),
        }
    finally:
        session.close()


@shared_task
def cleanup_expired_quality_scores(dry_run: bool = False):
    """
    清理超过 90 天的 bi_quality_scores 历史数据。

    注意：趋势 API 需要保留 90 天数据，向后兼容。
    此任务仅清理超过 90 天的评分记录。

    Args:
        dry_run: 若为 True，仅返回待清理记录数，不执行删除（冒烟测试用）

    Returns:
        dict: 清理结果摘要
    """
    session = SessionLocal()
    cutoff_date = datetime.utcnow() - timedelta(days=90)

    try:
        from services.governance.models import QualityScore

        # T3.4: dry_run 模式 — 仅计数，不删除
        if dry_run:
            count = (
                session.query(QualityScore)
                .filter(QualityScore.calculated_at < cutoff_date)
                .count()
            )
            return {
                "task": "cleanup_expired_quality_scores",
                "cutoff_date": cutoff_date.isoformat(),
                "dry_run": True,
                "pending_delete_count": count,
                "status": "dry_run_completed",
            }

        deleted_count = (
            session.query(QualityScore)
            .filter(QualityScore.calculated_at < cutoff_date)
            .delete(synchronize_session=False)
        )

        session.commit()

        return {
            "task": "cleanup_expired_quality_scores",
            "cutoff_date": cutoff_date.isoformat(),
            "deleted_count": deleted_count,
            "status": "completed",
        }

    except Exception as e:
        session.rollback()
        return {
            "task": "cleanup_expired_quality_scores",
            "status": "failed",
            "error": str(e),
        }
    finally:
        session.close()


@shared_task
def cleanup_all_expired_data():
    """
    清理所有超过 90 天的质量相关历史数据。

    组合任务，同时清理 results 和 scores。
    推荐在低峰期执行。

    Returns:
        dict: 清理结果摘要
    """
    results_task = cleanup_expired_quality_results()
    scores_task = cleanup_expired_quality_scores()

    return {
        "task": "cleanup_all_expired_data",
        "results": results_task,
        "scores": scores_task,
        "status": "completed",
    }
