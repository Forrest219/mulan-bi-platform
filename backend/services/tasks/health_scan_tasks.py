"""
健康扫描 Celery 任务
"""
import logging

from services.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def run_health_scan_task(self, scan_record_id: int, db_config: dict):
    """后台执行数仓健康扫描"""
    from services.health_scan.engine import HealthScanEngine
    from services.health_scan.models import HealthScanDatabase

    try:
        engine = HealthScanEngine(db_config)
        scan_db = HealthScanDatabase()
        engine.run_scan(scan_db, scan_record_id)
        logger.info("Health scan task completed for record %d", scan_record_id)
        return {"status": "success", "scan_id": scan_record_id}
    except Exception as e:
        logger.error("Health scan task failed for record %d: %s", scan_record_id, e, exc_info=True)
        try:
            scan_db = HealthScanDatabase()
            scan_db.update_scan_status(scan_record_id, "failed", error=str(e))
        except Exception:
            pass
        return {"status": "error", "scan_id": scan_record_id, "message": str(e)}
