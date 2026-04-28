"""DQC 规则执行器

职责：
- 接收 (asset, rule)，根据 rule_type 生成方言适配的只读 SQL 并执行
- 复用 services.governance.engine 的方言分派思路（DQC 自持一套更贴近 DQC 规则类型的实现）
- 返回 RuleExecutionResult，由 orchestrator 负责写入 bi_dqc_rule_results
"""
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import column, create_engine, func, literal, select, table, text as sa_text

from .constants import DEFAULT_MAX_SCAN_ROWS, RuleType
from .models import DqcMonitoredAsset, DqcQualityRule

logger = logging.getLogger(__name__)


FORBIDDEN_SQL_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE",
    "COPY", "INTO OUTFILE", "INTO DUMPFILE",
]


@dataclass
class RuleExecutionResult:
    rule_id: int
    asset_id: int
    dimension: str
    rule_type: str
    passed: bool
    actual_value: Optional[float] = None
    expected_config: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    execution_time_ms: int = 0


class DqcRuleEngineError(Exception):
    pass


class DqcRuleEngine:
    """DQC 规则执行器"""

    def __init__(self, db_config: Optional[dict] = None, connection=None):
        """
        Args:
            db_config: 已解密的目标库连接配置；用于建立只读连接（orchestrator 通常传此）
            connection: 也可直接复用已建立的连接（测试用）
        """
        self.db_config = db_config or {}
        self.db_type = (self.db_config.get("db_type") or "").lower()
        self._external_conn = connection

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _get_conn(self):
        if self._external_conn is not None:
            return self._external_conn, False
        user = self.db_config.get("user")
        password = self.db_config.get("password")
        host = self.db_config.get("host")
        port = self.db_config.get("port")
        database = self.db_config.get("database")
        if self.db_type == "postgresql":
            url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
            connect_args = {"options": "-c default_transaction_read_only=on -c statement_timeout=60000"}
        elif self.db_type in ("mysql", "starrocks", "doris"):
            url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
            connect_args = {}
        else:
            url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
            connect_args = {}
        engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
        return engine.connect(), True

    def _close(self, conn, owned: bool):
        if owned:
            try:
                conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def execute_rule(
        self, asset: DqcMonitoredAsset, rule: DqcQualityRule
    ) -> RuleExecutionResult:
        start = time.time()
        config = dict(rule.rule_config or {})
        dispatch = {
            RuleType.NULL_RATE.value: self._exec_null_rate,
            RuleType.UNIQUENESS.value: self._exec_uniqueness,
            RuleType.RANGE_CHECK.value: self._exec_range_check,
            RuleType.FRESHNESS.value: self._exec_freshness,
            RuleType.REGEX.value: self._exec_regex,
            RuleType.CUSTOM_SQL.value: self._exec_custom_sql,
            RuleType.VOLUME_ANOMALY.value: self._exec_volume_anomaly,
            RuleType.TABLE_COUNT_COMPARE.value: self._exec_table_count_compare,
        }
        handler = dispatch.get(rule.rule_type)
        if not handler:
            return RuleExecutionResult(
                rule_id=rule.id,
                asset_id=asset.id,
                dimension=rule.dimension,
                rule_type=rule.rule_type,
                passed=False,
                actual_value=None,
                expected_config=config,
                error_message=f"unsupported rule_type: {rule.rule_type}",
                execution_time_ms=int((time.time() - start) * 1000),
            )

        if rule.rule_type == RuleType.VOLUME_ANOMALY.value:
            passed, actual_value, err = handler(asset, rule, config)
            return RuleExecutionResult(
                rule_id=rule.id,
                asset_id=asset.id,
                dimension=rule.dimension,
                rule_type=rule.rule_type,
                passed=passed,
                actual_value=actual_value,
                expected_config=config,
                error_message=err,
                execution_time_ms=int((time.time() - start) * 1000),
            )

        conn, owned = None, False
        try:
            conn, owned = self._get_conn()
        except Exception as exc:
            return RuleExecutionResult(
                rule_id=rule.id,
                asset_id=asset.id,
                dimension=rule.dimension,
                rule_type=rule.rule_type,
                passed=False,
                actual_value=None,
                expected_config=config,
                error_message=f"target_connection_failed: {exc}",
                execution_time_ms=int((time.time() - start) * 1000),
            )

        try:
            passed, actual_value, err = handler(conn, asset, rule, config)
        except Exception as exc:
            logger.exception("dqc rule execution failed: rule_id=%s", rule.id)
            passed, actual_value, err = False, None, f"execution_error: {exc}"
        finally:
            self._close(conn, owned)

        return RuleExecutionResult(
            rule_id=rule.id,
            asset_id=asset.id,
            dimension=rule.dimension,
            rule_type=rule.rule_type,
            passed=passed,
            actual_value=actual_value,
            expected_config=config,
            error_message=err,
            execution_time_ms=int((time.time() - start) * 1000),
        )

    # ------------------------------------------------------------------
    # 共用工具
    # ------------------------------------------------------------------

    def _qualified_table(self, asset: DqcMonitoredAsset):
        return table(asset.table_name, schema=asset.schema_name)

    def _fetch_scalar(self, conn, stmt) -> Optional[float]:
        result = conn.execute(stmt)
        row = result.fetchone()
        if row is None:
            return None
        value = row[0]
        if value is None:
            return None
        return float(value)

    def _check_scan_limit(self, conn, asset: DqcMonitoredAsset, config: dict) -> Tuple[bool, Optional[str]]:
        max_scan_rows = int(config.get("max_scan_rows") or DEFAULT_MAX_SCAN_ROWS)
        row_count = None
        profile = getattr(asset, "profile_json", None)
        if isinstance(profile, dict) and profile.get("row_count") is not None:
            row_count = int(profile["row_count"])
        if row_count is None:
            stmt = select(func.count()).select_from(self._qualified_table(asset))
            try:
                row_count = int(self._fetch_scalar(conn, stmt) or 0)
            except Exception as exc:
                return False, f"row_count_query_failed: {exc}"
        if row_count > max_scan_rows:
            return False, f"max_scan_rows_exceeded:{row_count}>{max_scan_rows}"
        return True, None

    # ------------------------------------------------------------------
    # 规则实现
    # ------------------------------------------------------------------

    def _exec_null_rate(self, conn, asset, rule, config) -> Tuple[bool, Optional[float], Optional[str]]:
        col_name = config.get("column")
        max_rate = config.get("max_rate")
        if not col_name or max_rate is None:
            return False, None, "invalid_rule_config: require column and max_rate"

        ok, err = self._check_scan_limit(conn, asset, config)
        if not ok:
            return False, None, err

        col = column(col_name)
        # 跨方言一致：CASE WHEN col IS NULL THEN 1 ELSE 0 END 后 SUM
        from sqlalchemy import case as sa_case
        null_count_expr = func.sum(sa_case((col.is_(None), literal(1)), else_=literal(0)))
        total_count_expr = func.count()
        stmt = select(null_count_expr.label("null_count"), total_count_expr.label("total_count")).select_from(
            self._qualified_table(asset)
        )
        result = conn.execute(stmt).fetchone()
        if not result:
            return False, None, "empty_result"
        null_count = int(result[0] or 0)
        total_count = int(result[1] or 0)
        if total_count == 0:
            return True, 0.0, None
        rate = round(null_count / total_count, 6)
        return (rate <= float(max_rate)), rate, None

    def _exec_uniqueness(self, conn, asset, rule, config) -> Tuple[bool, Optional[float], Optional[str]]:
        cols = config.get("columns")
        if not cols or not isinstance(cols, list):
            return False, None, "invalid_rule_config: require columns list"
        max_dup_rate = float(config.get("max_duplicate_rate") or 0)

        ok, err = self._check_scan_limit(conn, asset, config)
        if not ok:
            return False, None, err

        tbl = self._qualified_table(asset)
        col_exprs = [column(c) for c in cols]
        if len(col_exprs) == 1:
            distinct_expr = func.count(func.distinct(col_exprs[0]))
        else:
            if self.db_type in ("mysql", "starrocks", "doris"):
                coalesced = [func.ifnull(col, sa_text("'__NULL__'")) for col in col_exprs]
            else:
                coalesced = [func.coalesce(col, sa_text("'__NULL__'")) for col in col_exprs]
            distinct_expr = func.count(
                func.distinct(func.concat_ws(sa_text("'::'"), *coalesced))
            )
        total_expr = func.count()
        stmt = select(distinct_expr.label("distinct_count"), total_expr.label("total_count")).select_from(tbl)
        result = conn.execute(stmt).fetchone()
        if not result:
            return False, None, "empty_result"
        distinct_count = int(result[0] or 0)
        total_count = int(result[1] or 0)
        if total_count == 0:
            return True, 0.0, None
        dup_rate = round((total_count - distinct_count) / total_count, 6)
        return (dup_rate <= max_dup_rate), dup_rate, None

    def _exec_range_check(self, conn, asset, rule, config) -> Tuple[bool, Optional[float], Optional[str]]:
        col_name = config.get("column")
        if not col_name:
            return False, None, "invalid_rule_config: require column"
        min_val = config.get("min")
        max_val = config.get("max")
        check_mode = (config.get("check_mode") or "min_max_all").lower()

        ok, err = self._check_scan_limit(conn, asset, config)
        if not ok:
            return False, None, err

        tbl = self._qualified_table(asset)
        col = column(col_name)

        if check_mode == "avg":
            stmt = select(func.avg(col).label("avg_value")).select_from(tbl).where(col.isnot(None))
            avg_value = self._fetch_scalar(conn, stmt)
            if avg_value is None:
                return True, None, None
            passed = True
            if min_val is not None and avg_value < float(min_val):
                passed = False
            if max_val is not None and avg_value > float(max_val):
                passed = False
            return passed, round(float(avg_value), 6), None

        total_stmt = select(func.count()).select_from(tbl).where(col.isnot(None))
        total_count = int(self._fetch_scalar(conn, total_stmt) or 0)
        if total_count == 0:
            return True, 0.0, None

        violation_stmt = select(func.count()).select_from(tbl).where(col.isnot(None))
        if min_val is not None and max_val is not None:
            violation_stmt = violation_stmt.where((col < float(min_val)) | (col > float(max_val)))
        elif min_val is not None:
            violation_stmt = violation_stmt.where(col < float(min_val))
        elif max_val is not None:
            violation_stmt = violation_stmt.where(col > float(max_val))
        else:
            return False, 0.0, "invalid_rule_config: require min or max for min_max_all"

        violation_count = int(self._fetch_scalar(conn, violation_stmt) or 0)
        violation_rate = round(violation_count / total_count, 6)
        return (violation_count == 0), violation_rate, None

    def _exec_freshness(self, conn, asset, rule, config) -> Tuple[bool, Optional[float], Optional[str]]:
        col_name = config.get("column")
        max_age_hours = config.get("max_age_hours")
        if not col_name or max_age_hours is None:
            return False, None, "invalid_rule_config: require column and max_age_hours"

        tbl = self._qualified_table(asset)
        col = column(col_name)
        if self.db_type in ("mysql", "starrocks", "doris"):
            delay_expr = func.timestampdiff(sa_text("HOUR"), func.max(col), func.now())
        else:
            delay_expr = func.extract("epoch", func.now() - func.max(col)) / literal(3600)

        stmt = select(delay_expr.label("age_hours")).select_from(tbl)
        age_hours = self._fetch_scalar(conn, stmt)
        if age_hours is None:
            return False, None, "no_timestamp_available"
        age_hours = round(float(age_hours), 4)
        return (age_hours <= float(max_age_hours)), age_hours, None

    def _exec_regex(self, conn, asset, rule, config) -> Tuple[bool, Optional[float], Optional[str]]:
        """V1 留桩：返回 not_implemented，不阻塞 cycle"""
        return False, None, "regex_rule_not_implemented_v1"

    def _exec_custom_sql(self, conn, asset, rule, config) -> Tuple[bool, Optional[float], Optional[str]]:
        """V2 留桩：custom_sql 需要完整的只读校验与黑名单"""
        return False, None, "custom_sql_rule_not_implemented_v1"

    # ------------------------------------------------------------------
    # volume_anomaly — 快照对比，不扫描目标库
    # ------------------------------------------------------------------

    def _exec_volume_anomaly(
        self, asset, rule, config, db=None
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        direction = config.get("direction", "drop")
        threshold_pct = config.get("threshold_pct", 0.80)
        comparison_window = config.get("comparison_window", "1d")
        min_row_count = config.get("min_row_count", 1000)

        today_count = self._get_row_count_snapshot(asset.id, db=db)
        if today_count is None:
            return False, None, "row_count_snapshot not available for today"

        baseline_count = self._get_baseline_snapshot(asset.id, comparison_window, db=db)
        if baseline_count is None:
            return False, None, f"insufficient history for {comparison_window} comparison"

        if today_count <= min_row_count:
            return True, 0.0, None

        if baseline_count == 0:
            return True, 0.0, None

        drop_pct = (baseline_count - today_count) / baseline_count
        rise_pct = (today_count - baseline_count) / baseline_count

        passed = True
        direction_result = "ok"
        actual_value = 0.0

        if direction in ("drop", "both") and drop_pct >= threshold_pct:
            passed = False
            direction_result = "drop"
            actual_value = round(abs(drop_pct), 4)
        if direction in ("rise", "both") and rise_pct >= threshold_pct:
            passed = False
            direction_result = "rise"
            actual_value = round(abs(rise_pct), 4)

        return passed, round(actual_value, 4), None

    def _get_row_count_snapshot(self, asset_id: int, db=None) -> Optional[int]:
        from services.dqc.database import DqcDatabase
        dao = DqcDatabase()
        if db is None:
            from app.core.database import SessionLocal
            db = SessionLocal()
            owned = True
        else:
            owned = False
        try:
            snapshot = dao.get_latest_snapshot(db, asset_id)
            if snapshot and snapshot.row_count_snapshot is not None:
                return snapshot.row_count_snapshot
        finally:
            if owned:
                db.close()
        return None

    def _get_baseline_snapshot(self, asset_id: int, window: str, db=None) -> Optional[int]:
        from datetime import timedelta
        from services.dqc.database import DqcDatabase
        dao = DqcDatabase()
        days_map = {"1d": 1, "7d": 7, "30d": 30}
        days = days_map.get(window, 1)
        target_date = datetime.utcnow() - timedelta(days=days)
        if db is None:
            from app.core.database import SessionLocal
            db = SessionLocal()
            owned = True
        else:
            owned = False
        try:
            mid_point = target_date - timedelta(hours=12)
            snapshots = dao.list_snapshots(db, asset_id, start=None, end=mid_point)
            if not snapshots:
                return None
            latest = max(snapshots, key=lambda s: s.computed_at)
            return latest.row_count_snapshot
        finally:
            if owned:
                db.close()

    # ------------------------------------------------------------------
    # table_count_compare — 跨表行数对比
    # ------------------------------------------------------------------

    def _exec_table_count_compare(
        self, conn, asset, rule, config
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        target_schema = config.get("target_schema")
        target_table = config.get("target_table")
        target_datasource_id = config.get("target_datasource_id")
        tolerance_pct = config.get("tolerance_pct", 0.0)

        if not target_schema or not target_table:
            return False, None, "invalid_rule_config: require target_schema and target_table"

        current_count = self._get_table_count(conn, asset.schema_name, asset.table_name)

        if target_datasource_id:
            target_conn = self._get_datasource_connection(target_datasource_id)
            try:
                target_count = self._get_table_count(target_conn, target_schema, target_table)
            finally:
                target_conn.close()
        else:
            target_count = self._get_table_count(conn, target_schema, target_table)

        if target_count is None or current_count is None:
            return False, None, "count_query_failed"

        if target_count == 0:
            return True, 0.0, None

        diff_pct = abs(current_count - target_count) / target_count
        passed = diff_pct <= tolerance_pct

        return passed, round(diff_pct, 6), None

    def _get_table_count(self, conn, schema: str, table_name: str) -> Optional[int]:
        tbl = table(table_name, schema=schema)
        stmt = select(func.count()).select_from(tbl)
        result = conn.execute(stmt)
        row = result.fetchone()
        if row is None:
            return None
        value = row[0]
        return int(value) if value is not None else None

    def _get_datasource_connection(self, datasource_id: str):
        from app.core.database import SessionLocal
        from services.datasources.service import DataSourceService

        db = SessionLocal()
        try:
            svc = DataSourceService(db)
            ds = svc.get_by_id(datasource_id)
            if not ds:
                raise DqcRuleEngineError(f"datasource not found: {datasource_id}")

            config = ds.get_decrypted_config()
            db_type = (config.get("db_type") or "").lower()

            user = config.get("user")
            password = config.get("password")
            host = config.get("host")
            port = config.get("port")
            database = config.get("database")

            if db_type in ("mysql", "starrocks", "doris"):
                url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
            elif db_type == "sqlserver":
                url = f"mssql+pymssql://{user}:{password}@{host}:{port}/{database}"
            elif db_type == "hive" or db_type == "hive_server2":
                url = f"pyhive://{user}:{password}@{host}:{port}/{database}"
            else:
                url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"

            engine = create_engine(url, pool_pre_ping=True)
            return engine.connect()
        finally:
            db.close()


def validate_custom_sql(sql: str) -> bool:
    """简单的 custom_sql 黑名单校验，供 V2 复用。"""
    if not sql or not sql.strip().upper().startswith("SELECT"):
        return False
    upper_sql = sql.upper()
    for kw in FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", upper_sql):
            return False
    return True
