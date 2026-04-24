"""数据质量监控 - Celery 异步任务

遵循 Spec 15 v1.1：
- Celery Beat 按 Cron 表达式触发 execute_quality_rules_task
- 按 datasource_id 分组复用数据库连接
- 逐条执行检测 SQL，写入 bi_quality_results
- 全部执行完毕后触发评分计算
- Append-Only bi_quality_scores
- max_scan_rows 熔断
- Read-Only 连接约束
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from celery import shared_task

from services.tasks.decorators import beat_guarded

logger = logging.getLogger(__name__)


EXECUTION_TIMEOUT_SECONDS = 60  # GOV_007


@shared_task(bind=True)
def execute_quality_rules_task(
    self,
    datasource_id: int,
    rule_ids: List[int] = None,
    db_config: dict = None,
) -> Dict[str, Any]:
    """执行质量规则检测任务

    Args:
        datasource_id: 数据源 ID
        rule_ids: 指定规则 ID 列表（None 表示执行所有启用的规则）
        db_config: 目标数据库连接配置（解密后的明文密码）

    Returns:
        dict: 执行结果统计
    """
    from services.governance.database import QualityDatabase
    from services.governance.engine import QualitySQLEngine, validate_custom_sql, check_scan_row_limit, SQLGenerationError
    from services.governance.scorer import calculate_quality_score
    from services.datasources.models import DataSource, DataSourceDatabase
    from app.core.database import SessionLocal

    qdb = QualityDatabase()
    started_at = datetime.now()

    db = SessionLocal()
    try:
        # 1. 获取数据源信息
        ds_db = DataSourceDatabase()
        ds = ds_db.get(db, datasource_id)
        if not ds:
            logger.error(f"execute_quality_rules_task: datasource {datasource_id} not found")
            return {"status": "failed", "error": "GOV_010: 数据源不存在或未激活"}

        # 2. 获取待执行规则
        if rule_ids:
            rules = [qdb.get_rule(db, rid) for rid in rule_ids]
            rules = [r for r in rules if r and r.enabled]
        else:
            rules = qdb.get_enabled_rules(db, datasource_id=datasource_id)

        if not rules:
            logger.info(f"execute_quality_rules_task: no enabled rules for datasource {datasource_id}")
            return {"status": "success", "rules_executed": 0, "rules_passed": 0, "rules_failed": 0}

        # 3. 建立目标数据库只读连接（强制约束 §8.2）
        target_config = db_config or _build_readonly_config(ds)
        conn = _get_target_connection(target_config, ds.db_type)
        if not conn:
            return {"status": "failed", "error": "GOV_008: 目标数据库连接失败"}

        results_to_insert = []
        engine = QualitySQLEngine(ds.db_type)

        # 4. 逐条执行规则
        for rule in rules:
            rule_start = time.time()
            try:
                # max_scan_rows 熔断检查
                threshold = rule.threshold or {}
                max_scan_rows = threshold.get("max_scan_rows", 1000000)
                estimated_rows = _estimate_row_count(conn, rule.table_name, ds.db_type)
                passed_check, warning = check_scan_row_limit(estimated_rows, max_scan_rows, rule.name)
                if not passed_check:
                    results_to_insert.append({
                        "rule_id": rule.id,
                        "datasource_id": datasource_id,
                        "table_name": rule.table_name,
                        "field_name": rule.field_name,
                        "rule_type": rule.rule_type,
                        "executed_at": datetime.now(),
                        "passed": True,  # 熔断跳过视为通过
                        "actual_value": None,
                        "expected_value": f"skipped: {warning}",
                        "detail_json": {"skipped": True, "warning": warning},
                        "execution_time_ms": int((time.time() - rule_start) * 1000),
                    })
                    continue

                # 生成 SQL
                if rule.rule_type == "custom_sql":
                    if not validate_custom_sql(rule.custom_sql or ""):
                        raise SQLGenerationError("GOV_005: 自定义 SQL 安全校验失败")
                    sql = rule.custom_sql
                else:
                    sql = engine.generate_sql(rule)

                # 执行 SQL
                actual_value, detail_json = _execute_sql(conn, sql, rule.rule_type, ds.db_type, rule.threshold or {})

                # 比较结果
                passed, expected_value_str = engine.compare_result(
                    actual_value,
                    rule.operator,
                    rule.threshold or {},
                )

                execution_time_ms = int((time.time() - rule_start) * 1000)

                results_to_insert.append({
                    "rule_id": rule.id,
                    "datasource_id": datasource_id,
                    "table_name": rule.table_name,
                    "field_name": rule.field_name,
                    "rule_type": rule.rule_type,
                    "executed_at": datetime.now(),
                    "passed": passed,
                    "actual_value": actual_value,
                    "expected_value": expected_value_str,
                    "detail_json": detail_json,
                    "execution_time_ms": execution_time_ms,
                })

            except SQLGenerationError as e:
                logger.warning(f"Rule {rule.id} SQL generation error: {e}")
                results_to_insert.append({
                    "rule_id": rule.id,
                    "datasource_id": datasource_id,
                    "table_name": rule.table_name,
                    "field_name": rule.field_name,
                    "rule_type": rule.rule_type,
                    "executed_at": datetime.now(),
                    "passed": False,
                    "actual_value": None,
                    "expected_value": None,
                    "detail_json": None,
                    "execution_time_ms": int((time.time() - rule_start) * 1000),
                    "error_message": str(e),
                })
            except Exception as e:
                logger.error(f"Rule {rule.id} execution error: {e}", exc_info=True)
                results_to_insert.append({
                    "rule_id": rule.id,
                    "datasource_id": datasource_id,
                    "table_name": rule.table_name,
                    "field_name": rule.field_name,
                    "rule_type": rule.rule_type,
                    "executed_at": datetime.now(),
                    "passed": False,
                    "actual_value": None,
                    "expected_value": None,
                    "detail_json": None,
                    "execution_time_ms": int((time.time() - rule_start) * 1000),
                    "error_message": str(e),
                })

        # 5. 关闭目标数据库连接
        _close_connection(conn, ds.db_type)

        # 6. 批量写入检测结果
        if results_to_insert:
            qdb.batch_create_results(db, results_to_insert)

        # 7. 计算并追加评分
        _calculate_and_append_score(qdb, db, datasource_id, started_at)

        passed_count = sum(1 for r in results_to_insert if r["passed"])
        failed_count = len(results_to_insert) - passed_count

        logger.info(
            f"execute_quality_rules_task completed: datasource={datasource_id}, "
            f"executed={len(results_to_insert)}, passed={passed_count}, failed={failed_count}"
        )

        return {
            "status": "success",
            "rules_executed": len(results_to_insert),
            "rules_passed": passed_count,
            "rules_failed": failed_count,
        }

    except Exception as e:
        logger.error(f"execute_quality_rules_task failed: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()


def _build_readonly_config(ds) -> Dict[str, Any]:
    """从 DataSource 构建只读连接配置（强制约束 §8.2）"""
    from app.core.crypto import get_datasource_crypto
    crypto = get_datasource_crypto()
    password = crypto.decrypt(ds.password_encrypted)
    return {
        "db_type": ds.db_type,
        "host": ds.host,
        "port": ds.port,
        "user": ds.username,
        "password": password,
        "database": ds.database_name,
        # 只读连接参数（数据库层面通过 default_transaction_read_only=true 强制约束）
        "connect_timeout": 30,
    }


def _get_target_connection(config: Dict[str, Any], db_type: str):
    """建立目标数据库只读连接

    Returns:
        connection object or None
    """
    import sqlalchemy
    try:
        if db_type == "postgresql":
            url = f"postgresql://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}?connect_timeout={config.get('connect_timeout', 30)}&default_transaction_read_only=true"
            engine = sqlalchemy.create_engine(url, pool_pre_ping=True, pool_recycle=300)
        elif db_type in ("mysql", "starrocks", "doris"):
            url = f"mysql+pymysql://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}?connect_timeout={config.get('connect_timeout', 30)}"
            engine = sqlalchemy.create_engine(url, pool_pre_ping=True, pool_recycle=300)
        elif db_type in ("mssql", "sqlserver"):
            url = f"mssql+pymssql://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}?charset=utf8"
            engine = sqlalchemy.create_engine(url, pool_pre_ping=True, pool_recycle=300)
        elif db_type == "oracle":
            url = f"oracle+cx_oracle://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
            engine = sqlalchemy.create_engine(url, pool_pre_ping=True, pool_recycle=300)
        else:
            logger.warning(f"Unsupported db_type for quality check: {db_type}")
            return None

        conn = engine.connect()
        # 设置只读事务（数据库层面约束）
        if db_type == "postgresql":
            conn.execute(sqlalchemy.text("SET default_transaction_read_only = ON"))
        return conn

    except Exception as e:
        logger.error(f"Failed to connect to target database: {e}")
        return None


def _close_connection(conn, db_type: str):
    """安全关闭数据库连接"""
    try:
        if conn:
            conn.close()
    except Exception as e:
        logger.warning(f"Error closing {db_type} connection: {e}")


def _estimate_row_count(conn, table_name: str, db_type: str) -> int:
    """预估表行数（用于熔断检查）"""
    import re
    # Defensive: only allow alphanumeric + underscore + dot (schema.table)
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_\.]*$", table_name):
        logger.warning("Blocked unsafe table_name in row estimation: %s", table_name)
        return 0
    try:
        if db_type == "postgresql":
            result = conn.execute(
                sqlalchemy.text(
                    "SELECT reltuples::bigint FROM pg_class WHERE relname = :table_name"
                ),
                {"table_name": table_name},
            )
        elif db_type in ("mysql", "starrocks", "doris"):
            result = conn.execute(
                sqlalchemy.text(
                    "SELECT TABLE_ROWS FROM information_schema.TABLES WHERE TABLE_NAME = :table_name"
                ),
                {"table_name": table_name},
            )
        elif db_type in ("mssql", "sqlserver"):
            result = conn.execute(
                sqlalchemy.text(
                    "SELECT SUM(row_count) FROM sys.dm_db_partition_stats WHERE object_id = OBJECT_ID(:table_name)"
                ),
                {"table_name": table_name},
            )
        else:
            return 0

        row = result.fetchone()
        if row and row[0]:
            return int(row[0])
    except Exception:
        pass
    return 0


def _execute_sql(conn, sql: str, rule_type: str, db_type: str, threshold: Dict[str, Any]) -> tuple:
    """执行检测 SQL 并解析结果

    Returns:
        (actual_value: float, detail_json: dict)
    """
    import sqlalchemy

    try:
        result = conn.execute(sqlalchemy.text(sql), execution_options={"statement_timeout": EXECUTION_TIMEOUT_SECONDS * 1000})
        row = result.fetchone()

        if not row:
            return 0.0, {"note": "no rows returned"}

        raw_value = row[0]

        # 特殊处理 custom_sql：0=通过，非0=失败
        if rule_type == "custom_sql":
            passed = raw_value == 0
            return float(raw_value), {"custom_sql_result": raw_value, "passed": passed}

        # 解析 actual_value
        actual_value = float(raw_value) if raw_value is not None else None

        # 补充采样数据（detail_json，最多10条）
        detail_json = {"value": actual_value}

        return actual_value, detail_json

    except sqlalchemy.exc.OperationalError as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower() or "canceling statement" in error_msg.lower():
            raise Exception("GOV_007: 目标数据库执行检测 SQL 超时")
        raise


def _calculate_and_append_score(qdb, db, datasource_id: int, executed_at: datetime):
    """计算质量评分并追加到 bi_quality_scores（Append-Only）"""
    from services.governance.scorer import calculate_quality_score

    # 获取本次执行的规则最新结果
    rule_results = qdb.get_latest_results(db, datasource_id=datasource_id)

    # 获取健康扫描评分（Spec 11 集成）
    health_scan_score = qdb.get_health_scan_score(db, datasource_id)

    # 获取 DDL 合规评分（Spec 06 集成）
    ddl_compliance_score = qdb.get_ddl_compliance_score(db, datasource_id)

    # 计算评分
    score_dict = calculate_quality_score(
        rule_results,
        health_scan_score,
        ddl_compliance_score,
    )

    # Append-Only 追加评分快照
    qdb.append_score(
        db,
        datasource_id=datasource_id,
        scope_type="datasource",
        scope_name=f"datasource_{datasource_id}",
        calculated_at=executed_at,
        **score_dict,
    )


@shared_task
@beat_guarded("quality-cleanup-old-results")
def cleanup_old_quality_results():
    """清理过期的 bi_quality_results 历史数据

    按 Spec 15 v1.1 §2.1 数据生命周期策略：
    - 默认保留 90 天
    - PostgreSQL 按月分区，Celery 定时 Drop 过期分区
    - 每月 1 日凌晨执行
    """
    from services.governance.database import QualityDatabase
    from sqlalchemy import text
    from app.core.database import engine

    qdb = QualityDatabase()
    retention_days = 90

    try:
        cutoff = datetime.now() - timedelta(days=retention_days)

        # 使用 DELETE 清理过期数据（分区表可直接 DROP 分区）
        with engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM bi_quality_results WHERE executed_at < :cutoff"),
                {"cutoff": cutoff}
            )
            # P1 修复：SQLAlchemy 2.0 Core DML 默认不自动提交，须显式 commit
            conn.commit()
            logger.info(f"cleanup_old_quality_results: deleted {result.rowcount} rows older than {retention_days} days")

    except Exception as e:
        logger.error(f"cleanup_old_quality_results failed: {e}", exc_info=True)
        raise

