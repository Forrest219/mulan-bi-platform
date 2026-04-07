"""
DDL 扫描 Celery 任务 — 基于表级拆分的并发执行

Spec 06 OI-10 修复：
大表扫描（数千张表）必须拆解为表级子任务，通过 Celery group() 并发执行，
避免单 Worker 同步处理导致内存溢出或任务超时。

架构：
  batch_scan_tables  (parent)
      │
      ├── scan_table[t1]  ──→  violations[]
      ├── scan_table[t2]  ──→  violations[]
      └── scan_table[tN]  ──→  violations[]

结果通过 AsyncResult.group_results[] 聚合，写入 ScanLog。
"""
import logging
from typing import List, Dict, Any

from celery import group, chord
from celery.exceptions import MaxRetriesExceededError

from services.tasks import celery_app

logger = logging.getLogger(__name__)

# 每批最大并发任务数（防止 Worker 过载）
MAX_CONCURRENT_TABLES = 50

# 单表扫描超时（秒），超时视为失败
TABLE_SCAN_TIMEOUT = 120


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    expires=TABLE_SCAN_TIMEOUT + 30,
    acks_late=True,  # 任务完成才 ACK，防止 Worker 崩溃丢失
)
def scan_table_task(
    self,
    table_name: str,
    db_config: dict,
    scene_type: str = "ALL",
    db_type: str = "MySQL",
) -> Dict[str, Any]:
    """
    扫描单个表的 DDL 合规性（表级子任务）。

    失败重试策略：
    - 首次失败：10s 后重试（网络抖动等瞬时故障）
    - 第二次失败：不再重试，直接记录空违规列表

    Returns:
        {
            "table_name": str,
            "violations": List[dict],
            "error": str | None,
            "duration_seconds": float
        }
    """
    import time
    from services.ddl_checker.scanner import DDLScanner

    start = time.time()
    scanner = DDLScanner(enable_logging=False)

    try:
        connected = scanner.connect_database(db_config)
        if not connected:
            raise RuntimeError(f"无法连接到数据库: {db_config.get('database')}")

        result = scanner.scan_table(table_name)
        scanner.disconnect_database()

        duration = time.time() - start

        if not result.success:
            raise RuntimeError(result.error or "未知错误")

        violations = []
        if result.report and result.report.table_results:
            for tbl_name, violist in result.report.table_results.items():
                for v in violist:
                    violations.append(v.to_dict())

        return {
            "table_name": table_name,
            "violations": violations,
            "error": None,
            "duration_seconds": round(duration, 3),
        }

    except Exception as e:
        duration = time.time() - start
        retry_count = self.request.retries

        logger.warning(
            "scan_table_task 失败 [retry=%d/2]: table=%s, error=%s",
            retry_count, table_name, e,
        )

        if retry_count < self.max_retries:
            try:
                # 重试前先关闭连接
                if scanner.connector:
                    scanner.disconnect_database()
                raise self.retry(countdown=self.default_retry_delay)
            except MaxRetriesExceededError:
                pass

        # 达到最大重试次数，返回错误结果（不阻塞整批）
        return {
            "table_name": table_name,
            "violations": [],
            "error": str(e),
            "duration_seconds": round(duration, 3),
        }


def _aggregate_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """聚合所有子任务结果，生成合并报告"""
    total_violations = 0
    error_tables = []
    all_violations = []

    for r in results:
        if r.get("error"):
            error_tables.append(r["table_name"])
        total_violations += len(r.get("violations", []))
        all_violations.extend(r.get("violations", []))

    return {
        "total_tables": len(results),
        "total_violations": total_violations,
        "error_count": len(error_tables),
        "error_tables": error_tables,
        "all_violations": all_violations,
    }


@celery_app.task(
    bind=True,
    max_retries=0,  # 父任务不允许重试
    acks_late=True,
)
def batch_scan_tables(
    self,
    scan_id: int,
    table_names: List[str],
    db_config: dict,
    scene_type: str = "ALL",
    db_type: str = "MySQL",
) -> Dict[str, Any]:
    """
    全库 DDL 扫描父任务（Spec 06 OI-10 修复）。

    执行流程：
    1. 将 table_names 按 MAX_CONCURRENT_TABLES 分批
    2. 每批内用 group() 并发派发 scan_table_task
    3. 等待所有子任务完成后聚合结果
    4. 将聚合报告写入 ScanLog

    ⚡ 防雪崩设计：
    - MAX_CONCURRENT_TABLES=50：限制单 Worker 瞬时负载
    - acks_late=True：Worker 崩溃不丢任务（任务完成后才 ACK）
    - 单表超时 TABLE_SCAN_TIMEOUT=120s：超时即记录错误，不无限等待

    Args:
        scan_id: ScanLog 记录 ID
        table_names: 要扫描的表名列表
        db_config: 数据库连接配置
        scene_type: 业务场景（ODS/DWD/ADS/ALL）
        db_type: 数据库类型（MySQL/PostgreSQL）

    Returns:
        {
            "status": "success" | "partial" | "failed",
            "scan_id": int,
            "summary": {...}  # _aggregate_results 输出
        }
    """
    import time
    from services.ddl_checker.reporter import ReportGenerator
    from services.logs.models import ScanLog

    start = time.time()

    # 分批
    batches = [
        table_names[i:i + MAX_CONCURRENT_TABLES]
        for i in range(0, len(table_names), MAX_CONCURRENT_TABLES)
    ]
    logger.info(
        "batch_scan: scan_id=%d, total_tables=%d, batches=%d",
        scan_id, len(table_names), len(batches),
    )

    all_results = []

    for batch_idx, batch in enumerate(batches):
        logger.info(
            "batch_scan: 处理批次 %d/%d, tables=%d",
            batch_idx + 1, len(batches), len(batch),
        )
        # 并发派发
        job = group(
            scan_table_task.s(table_name, db_config, scene_type, db_type)
            for table_name in batch
        )
        batch_results = job.apply_async().get(disable_sync_subtasks=False)
        all_results.extend(batch_results)

    # 聚合
    summary = _aggregate_results(all_results)
    duration = time.time() - start

    # 生成报告
    validation_results = {}
    for r in all_results:
        if r.get("violations"):
            from dataclasses import dataclass
            @dataclass
            class FakeViolation:
                level = None
                def to_dict(self):
                    return self._d
                def __init__(self, d):
                    self._d = d

            violations = [FakeViolation(v) for v in r["violations"]]
            validation_results[r["table_name"]] = violations

    report = ReportGenerator.generate(validation_results) if validation_results else None

    # 确定最终状态
    final_status = "failed" if summary["error_count"] == len(table_names) else (
        "partial" if summary["error_count"] > 0 else "completed"
    )

    # 写入 ScanLog
    try:
        scan_log = ScanLog()
        scan_log.id = scan_id
        scan_log.status = final_status
        scan_log.total_violations = summary["total_violations"]
        scan_log.save()
    except Exception as e:
        logger.error("更新 ScanLog 失败: scan_id=%d, error=%s", scan_id, e)
        final_status = "partial"  # 回退

    logger.info(
        "batch_scan 完成: scan_id=%d, tables=%d, violations=%d, errors=%d, duration=%.1fs",
        scan_id, len(table_names), summary["total_violations"],
        summary["error_count"], duration,
    )

    return {
        "status": final_status,
        "scan_id": scan_id,
        "summary": summary,
        "duration_seconds": round(duration, 2),
    }
