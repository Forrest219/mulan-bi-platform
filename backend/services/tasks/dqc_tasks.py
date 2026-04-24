"""DQC 异步任务

遵循 spec 31 §10：
- run_daily_full_cycle / run_hourly_light_cycle / run_for_asset_task
- profile_and_suggest_task：添加资产后 profiling + （V1 才有）建议规则
- partition_maintenance：按月滚动创建分区 + DROP 过期分区
- cleanup_old_analyses：LLM 分析 90d / cycles 180d 过期清理
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from celery import shared_task

from services.tasks.decorators import beat_guarded

logger = logging.getLogger(__name__)


# ==================== 核心任务 ====================


@shared_task(
    bind=True,
    name="services.tasks.dqc_tasks.run_daily_full_cycle",
    soft_time_limit=3000,
    time_limit=3600,
    acks_late=True,
    max_retries=0,
)
@beat_guarded("dqc-cycle-daily")
def run_daily_full_cycle(self):
    """每日 04:00 完整 cycle"""
    from services.dqc.orchestrator import CycleLockedError, DqcOrchestrator

    try:
        cycle_id = DqcOrchestrator().run_full_cycle(trigger_type="scheduled")
        return {"cycle_id": str(cycle_id), "status": "ok"}
    except CycleLockedError as exc:
        logger.warning("daily full cycle skipped: %s", exc)
        return {"status": "skipped", "reason": "locked"}
    except Exception:
        logger.exception("dqc full cycle failed")
        raise


@shared_task(
    bind=True,
    name="services.tasks.dqc_tasks.run_hourly_light_cycle",
    soft_time_limit=600,
    time_limit=900,
    acks_late=True,
    max_retries=0,
)
def run_hourly_light_cycle(self):
    """每小时轻量 cycle（freshness + null_rate）"""
    from services.dqc.orchestrator import CycleLockedError, DqcOrchestrator

    try:
        cycle_id = DqcOrchestrator().run_hourly_light_cycle()
        return {"cycle_id": str(cycle_id), "status": "ok"}
    except CycleLockedError as exc:
        logger.warning("hourly light cycle skipped: %s", exc)
        return {"status": "skipped", "reason": "locked"}
    except Exception:
        logger.exception("dqc hourly light cycle failed")
        raise


@shared_task(
    bind=True,
    name="services.tasks.dqc_tasks.run_for_asset",
    soft_time_limit=300,
    time_limit=600,
    max_retries=0,
)
def run_for_asset_task(self, asset_id: int, trigger_type: str = "manual", triggered_by: Optional[int] = None):
    """单资产 cycle（手动触发 / 首次评分）"""
    from services.dqc.orchestrator import DqcOrchestrator

    cycle_id = DqcOrchestrator().run_for_asset(
        asset_id, trigger_type=trigger_type, triggered_by=triggered_by
    )
    return {"cycle_id": str(cycle_id)}


@shared_task(
    bind=True,
    name="services.tasks.dqc_tasks.profile_and_suggest",
    soft_time_limit=600,
    time_limit=900,
    max_retries=2,
    default_retry_delay=60,
)
def profile_and_suggest_task(self, asset_id: int):
    """添加资产后：profiling + （V1）LLM 建议规则

    MVP：只做 profiling 并写入 asset.profile_json；LLM 建议规则留桩为空。
    """
    from app.core.crypto import get_datasource_crypto
    from app.core.database import SessionLocal
    from services.datasources.models import DataSourceDatabase
    from services.dqc.database import DqcDatabase
    from services.dqc.profiler import Profiler

    dao = DqcDatabase()
    ds_db = DataSourceDatabase()

    db = SessionLocal()
    try:
        asset = dao.get_asset(db, asset_id)
        if not asset:
            return {"status": "failed", "error": "asset_not_found"}

        ds = ds_db.get(db, asset.datasource_id)
        if not ds:
            return {"status": "failed", "error": "datasource_not_found"}

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

        profiler = Profiler(db_config)
        try:
            profile = profiler.profile_table(asset.schema_name, asset.table_name)
            profile_json = profiler.to_json(profile)
        except Exception as exc:
            logger.exception("profiling failed: asset_id=%s", asset_id)
            raise self.retry(exc=exc)

        dao.update_asset(db, asset_id, profile_json=profile_json)
        db.commit()
        return {"status": "ok", "asset_id": asset_id}
    finally:
        db.close()


# ==================== 维护任务 ====================


@shared_task(bind=True, name="services.tasks.dqc_tasks.partition_maintenance")
@beat_guarded("dqc-partition-maintenance")
def partition_maintenance(self):
    """滚动创建未来 3 个月分区 + DROP 超期分区

    仅在 PostgreSQL 上生效；非 PG 直接 no-op。
    """
    from sqlalchemy import text

    from app.core.database import engine

    if engine.dialect.name != "postgresql":
        return {"status": "skipped", "reason": "non_postgres"}

    specs = [
        ("bi_dqc_dimension_scores", 180),
        ("bi_dqc_asset_snapshots", 180),
        ("bi_dqc_rule_results", 90),
    ]

    now = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    created = []
    dropped = []
    with engine.begin() as conn:
        for tbl, retention_days in specs:
            for delta in range(0, 4):
                y, m = _month_offset(now, delta)
                y_next, m_next = _month_offset(now, delta + 1)
                partition_name = f"{tbl}_{y:04d}_{m:02d}"
                conn.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {partition_name} "
                        f"PARTITION OF {tbl} FOR VALUES FROM ('{y:04d}-{m:02d}-01') "
                        f"TO ('{y_next:04d}-{m_next:02d}-01')"
                    )
                )
                created.append(partition_name)

            cutoff = now - timedelta(days=retention_days)
            cutoff_partition_tag = f"{tbl}_{cutoff.year:04d}_{cutoff.month:02d}"
            rows = conn.execute(
                text(
                    "SELECT c.relname FROM pg_inherits i "
                    "JOIN pg_class c ON c.oid = i.inhrelid "
                    "JOIN pg_class p ON p.oid = i.inhparent "
                    "WHERE p.relname = :tbl"
                ),
                {"tbl": tbl},
            ).fetchall()
            for (child_name,) in rows:
                if child_name < cutoff_partition_tag:
                    conn.execute(text(f"DROP TABLE IF EXISTS {child_name}"))
                    dropped.append(child_name)
    return {"status": "ok", "created": created, "dropped": dropped}


@shared_task(bind=True, name="services.tasks.dqc_tasks.cleanup_old_analyses")
@beat_guarded("dqc-cleanup-old-analyses")
def cleanup_old_analyses(self):
    """删除 90 天前的 bi_dqc_llm_analyses 与 180 天前的 bi_dqc_cycles"""
    from app.core.database import SessionLocal
    from services.dqc.models import DqcCycle, DqcLlmAnalysis

    now = datetime.utcnow()
    analysis_cutoff = now - timedelta(days=90)
    cycle_cutoff = now - timedelta(days=180)

    db = SessionLocal()
    try:
        analyses_deleted = (
            db.query(DqcLlmAnalysis)
            .filter(DqcLlmAnalysis.created_at < analysis_cutoff)
            .delete(synchronize_session=False)
        )
        cycles_deleted = (
            db.query(DqcCycle)
            .filter(DqcCycle.created_at < cycle_cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return {"status": "ok", "analyses_deleted": analyses_deleted, "cycles_deleted": cycles_deleted}
    finally:
        db.close()


def _month_offset(base: datetime, delta: int):
    year = base.year
    month = base.month + delta
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return year, month
