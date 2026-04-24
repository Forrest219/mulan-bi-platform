"""Celery task decorators for schedule guard and other cross-cutting concerns."""
import functools
import logging

from app.core.database import get_db_context

logger = logging.getLogger(__name__)


def beat_guarded(schedule_key: str):
    """Beat task execution guard — skips if schedule is disabled."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                from services.tasks.models import BiTaskSchedule

                with get_db_context() as db:
                    schedule = db.query(BiTaskSchedule).filter(
                        BiTaskSchedule.schedule_key == schedule_key,
                    ).first()
                    if schedule and not schedule.is_enabled:
                        logger.info("beat_guarded: '%s' is disabled, skipping", schedule_key)
                        return {"status": "skipped", "reason": "disabled"}
            except Exception as e:
                logger.warning("beat_guarded check failed for '%s': %s (proceeding anyway)", schedule_key, e)
            return func(*args, **kwargs)
        return wrapper
    return decorator
