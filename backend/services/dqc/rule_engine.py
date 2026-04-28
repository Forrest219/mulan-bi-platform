"""DQC 规则执行器

职责：
- 接收 (asset, rule)，根据 rule_type 生成方言适配的只读 SQL 并执行
- 复用 services.governance.engine 的方言分派思路（DQC 自持一套更贴近 DQC 规则类型的实现）
- 返回 RuleExecutionResult，由 orchestrator 负责写入 bi_dqc_rule_results
- StarRocks 合规巡检：seed_sr_rules() + 8 个 _check_sr_* 校验方法
"""
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import column, create_engine, func, literal, select, table, text as sa_text

from .constants import DEFAULT_MAX_SCAN_ROWS, RuleType
from .models import DqcMonitoredAsset, DqcQualityRule


class SrViolationLevel(Enum):
    """StarRocks 违规级别（对应 rule.level）"""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class SrViolation:
    """StarRocks 合规巡检违规项"""
    rule_id: str
    level: str  # HIGH / MEDIUM / LOW
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "level": self.level,
            "message": self.message,
            "detail": self.detail,
        }

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


# ---------------------------------------------------------------------------
# StarRocks 合规巡检 — 25 条规则种子
# ---------------------------------------------------------------------------

SR_RULES = [
    {
        "rule_id": "RULE_SR_001",
        "name": "ODS 双下划线命名",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ODS",
        "description": "ODS 层表名必须使用 {系统}__{模块}__{原表} 格式",
        "suggestion": "表名格式示例: erp__order__sales_order",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "pattern": "^[a-z]+__[a-z0-9_]+__[a-z0-9_]+$",
            "databases": ["ods_db", "ods_api", "ods_log"]
        },
    },
    {
        "rule_id": "RULE_SR_002",
        "name": "DWD 业务域+粒度后缀",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "DWD",
        "description": "DWD 层表名必须使用 {业务域}_{含义}_{粒度后缀} 格式",
        "suggestion": "粒度后缀: _di(日增量), _df(日全量), _hi(小时增量), _rt(实时)",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "pattern": "^(sales|finance|supply|hr|market|risk|ops|product|ai)_.*_(di|df|hi|rt)$",
            "databases": ["dwd"]
        },
    },
    {
        "rule_id": "RULE_SR_003",
        "name": "DIM 无业务域前缀",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "DIM 层表不应使用业务域前缀，应为通用维度命名",
        "suggestion": "表名格式: dim_xxx，不要带 sales_/finance_ 等业务前缀",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "forbidden_prefixes": ["sales_", "finance_", "supply_", "hr_", "market_", "risk_", "ops_", "product_", "ai_"],
            "databases": ["dim"]
        },
    },
    {
        "rule_id": "RULE_SR_004",
        "name": "DWS 粒度后缀",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "DWS 层表名必须包含粒度后缀",
        "suggestion": "表名末尾应为 _1d, _1h, _1m, _rt",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "_(1d|1h|1m|rt)$", "databases": ["dws"]},
    },
    {
        "rule_id": "RULE_SR_005",
        "name": "ADS 场景前缀",
        "level": "HIGH",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "ADS 层表名必须包含场景前缀",
        "suggestion": "表名前缀: board_, report_, api_, ai_, tag_, label_",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "^(board|report|api|ai|tag|label)_", "databases": ["ads"]},
    },
    {
        "rule_id": "RULE_SR_006",
        "name": "金额字段必须 DECIMAL",
        "level": "HIGH",
        "category": "sr_type_alignment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "金额字段（_amt/_amount 后缀）必须使用 DECIMAL 类型",
        "suggestion": "使用 DECIMAL(20,4)，禁止 FLOAT/DOUBLE",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "suffixes": ["_amt", "_amount"],
            "required_type": "DECIMAL",
            "forbidden_types": ["FLOAT", "DOUBLE"]
        },
    },
    {
        "rule_id": "RULE_SR_007",
        "name": "日期字段禁止 VARCHAR",
        "level": "HIGH",
        "category": "sr_type_alignment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "日期时间字段（_time/_at/_dt 后缀）必须使用时间类型",
        "suggestion": "使用 DATETIME/DATE/TIMESTAMP，禁止 VARCHAR/CHAR/STRING",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "suffixes": ["_time", "_at", "_dt"],
            "required_types": ["DATETIME", "DATE", "TIMESTAMP"],
            "forbidden_types": ["VARCHAR", "CHAR", "STRING"]
        },
    },
    {
        "rule_id": "RULE_SR_008",
        "name": "公共字段 etl_time",
        "level": "HIGH",
        "category": "sr_public_fields",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有表必须包含 etl_time DATETIME 字段",
        "suggestion": "添加 etl_time DATETIME 字段记录 ETL 处理时间",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"required_fields": [{"name": "etl_time", "type": "DATETIME"}], "databases": "__all__"},
    },
    {
        "rule_id": "RULE_SR_009",
        "name": "公共字段 dt",
        "level": "HIGH",
        "category": "sr_public_fields",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "ODS/DWD/DWS/DM 表必须包含 dt DATE 分区字段",
        "suggestion": "添加 dt DATE 字段作为分区键",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"required_fields": [{"name": "dt", "type": "DATE"}], "databases": ["ods_db", "ods_api", "ods_log", "dwd", "dws", "dm"]},
    },
    {
        "rule_id": "RULE_SR_010",
        "name": "ODS 全套公共字段",
        "level": "HIGH",
        "category": "sr_public_fields",
        "db_type": "StarRocks",
        "scene_type": "ODS",
        "description": "ODS 层表必须包含 etl_batch_id/src_system/src_table/is_deleted 公共字段",
        "suggestion": "添加 ODS 全套公共字段",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "required_fields": [
                {"name": "etl_batch_id", "type": "VARCHAR"},
                {"name": "src_system", "type": "VARCHAR"},
                {"name": "src_table", "type": "VARCHAR"},
                {"name": "is_deleted", "type": "TINYINT"}
            ],
            "databases": ["ods_db", "ods_api", "ods_log"]
        },
    },
    {
        "rule_id": "RULE_SR_011",
        "name": "ODS_DB CDC 字段",
        "level": "HIGH",
        "category": "sr_public_fields",
        "db_type": "StarRocks",
        "scene_type": "ODS",
        "description": "ODS_DB 表必须包含 src_op/src_ts CDC 操作字段",
        "suggestion": "添加 src_op VARCHAR 和 src_ts DATETIME 字段",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"required_fields": [{"name": "src_op", "type": "VARCHAR"}, {"name": "src_ts", "type": "DATETIME"}], "databases": ["ods_db"]},
    },
    {
        "rule_id": "RULE_SR_012",
        "name": "字段 snake_case",
        "level": "HIGH",
        "category": "sr_field_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有字段名必须使用 snake_case 命名",
        "suggestion": "字段名使用小写字母+数字+下划线，长度不超过 40",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "^[a-z][a-z0-9_]*$", "max_length": 40},
    },
    {
        "rule_id": "RULE_SR_013",
        "name": "字段注释覆盖率",
        "level": "HIGH",
        "category": "sr_comment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有字段必须有注释，覆盖率 100%",
        "suggestion": "为每个字段添加 COMMENT",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"min_coverage": 1.0},
    },
    {
        "rule_id": "RULE_SR_014",
        "name": "表注释存在",
        "level": "HIGH",
        "category": "sr_comment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有表必须包含注释说明用途",
        "suggestion": "使用 COMMENT 说明表的业务含义和数据粒度",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {},
    },
    {
        "rule_id": "RULE_SR_015",
        "name": "禁止额外数据库",
        "level": "HIGH",
        "category": "sr_database_whitelist",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "StarRocks 实例中只允许规划内的数据库",
        "suggestion": "联系管理员确认数据库是否在规划列表中",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "allowed": ["ods_db", "ods_api", "ods_log", "dwd", "dim", "dws", "dm", "ads", "feature", "ai", "sandbox", "tmp", "ops", "meta", "backup", "information_schema", "_statistics_"]
        },
    },
    {
        "rule_id": "RULE_SR_016",
        "name": "Feature 表命名",
        "level": "MEDIUM",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "Feature 层表名必须包含特征粒度后缀",
        "suggestion": "表名格式: xxx_features_1d/1h/rt",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "_features_(1d|1h|rt|[0-9]+[dhm])$", "databases": ["feature"]},
    },
    {
        "rule_id": "RULE_SR_017",
        "name": "AI 表前缀",
        "level": "MEDIUM",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "AI 层表名必须使用 kb/llm/agent/text2sql 前缀",
        "suggestion": "表名前缀: kb_, llm_, agent_, text2sql_",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "^(kb|llm|agent|text2sql)_", "databases": ["ai"]},
    },
    {
        "rule_id": "RULE_SR_018",
        "name": "Backup 命名含日期",
        "level": "MEDIUM",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "Backup 层表名必须包含 8 位日期后缀",
        "suggestion": "表名格式: xxx__yyy_20260101",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "__.*_\\d{8}$", "databases": ["backup"]},
    },
    {
        "rule_id": "RULE_SR_019",
        "name": "数量字段类型",
        "level": "HIGH",
        "category": "sr_type_alignment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "数量字段（_qty/_cnt 后缀）必须使用整数或精确数值类型",
        "suggestion": "使用 BIGINT/DECIMAL/INT，禁止 FLOAT/DOUBLE",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "suffixes": ["_qty", "_cnt"],
            "required_types": ["BIGINT", "DECIMAL", "INT"],
            "forbidden_types": ["FLOAT", "DOUBLE"]
        },
    },
    {
        "rule_id": "RULE_SR_020",
        "name": "比率字段类型",
        "level": "HIGH",
        "category": "sr_type_alignment",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "比率字段（_rate 后缀）必须使用 DECIMAL 类型",
        "suggestion": "使用 DECIMAL(10,6)，禁止 FLOAT/DOUBLE",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {
            "suffixes": ["_rate"],
            "required_type": "DECIMAL",
            "forbidden_types": ["FLOAT", "DOUBLE"]
        },
    },
    {
        "rule_id": "RULE_SR_021",
        "name": "无 ods_hive 库",
        "level": "HIGH",
        "category": "sr_database_whitelist",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "StarRocks 实例中不应存在 ods_hive 数据库（ADR-003 迁移要求）",
        "suggestion": "将 ods_hive 数据迁移至 ods_db/ods_api/ods_log",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"forbidden": ["ods_hive"]},
    },
    {
        "rule_id": "RULE_SR_022",
        "name": "表名无中文",
        "level": "HIGH",
        "category": "sr_table_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "表名不允许包含中文字符",
        "suggestion": "表名只使用英文字母、数字、下划线",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern_forbidden": "[\\u4e00-\\u9fff]"},
    },
    {
        "rule_id": "RULE_SR_023",
        "name": "表名无版本号",
        "level": "MEDIUM",
        "category": "sr_table_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "表名不应包含版本号（如 _v2）",
        "suggestion": "使用 DDL 变更管理，不要在表名中加版本号",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern_forbidden": "_v\\d+"},
    },
    {
        "rule_id": "RULE_SR_024",
        "name": "DM 部门前缀",
        "level": "MEDIUM",
        "category": "sr_layer_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "DM 层表名使用宽松 snake_case",
        "suggestion": "表名格式: 部门_主题_含义",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "^[a-z][a-z0-9_]+$", "databases": ["dm"]},
    },
    {
        "rule_id": "RULE_SR_025",
        "name": "视图命名 _vw 后缀",
        "level": "MEDIUM",
        "category": "sr_view_naming",
        "db_type": "StarRocks",
        "scene_type": "ALL",
        "description": "所有视图必须以 _vw 后缀命名",
        "suggestion": "视图命名: xxx_vw",
        "enabled": True,
        "is_custom": False,
        "is_modified_by_user": False,
        "config_json": {"pattern": "_vw$"},
    },
]


def seed_sr_rules(session) -> int:
    """
    向 bi_rule_configs 表 Seed 25 条 StarRocks 规则（幂等性 UPSERT）。

    Returns:
        写入的规则数量
    """
    from services.rules.models import RuleConfig

    written = 0
    for rule_data in SR_RULES:
        rule_id = rule_data["rule_id"]
        existing = session.query(RuleConfig).filter(RuleConfig.rule_id == rule_id).first()

        if not existing:
            session.add(RuleConfig(**rule_data))
            written += 1
        elif not existing.is_modified_by_user:
            for key, value in rule_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            written += 1

    if written > 0:
        session.commit()
    return written


# ---------------------------------------------------------------------------
# StarRocks 合规校验器（Spec 35 §4.4）
# ---------------------------------------------------------------------------

@dataclass
class SrTableInfo:
    """StarRocks 巡检用表信息（兼容 DDLScanner TableInfo 结构）"""
    name: str
    database: str
    columns: List[Any]  # List of {name, data_type, comment, ...}
    comment: str = ""
    table_type: str = "BASE TABLE"  # or "VIEW"


class SrComplianceValidator:
    """
    StarRocks 合规巡检验筋肉册（Spec 35 §4.4）。

    提供 8 个 _check_sr_* 方法，按 category 分派。
    逐表调用时通过 validate_table() 聚合所有 violations。
    """

    def __init__(self, rules: Optional[List[Dict[str, Any]]] = None):
        """
        Args:
            rules: 规则列表，不传则使用 SR_RULES 内置种子。
        """
        self.rules = rules if rules is not None else SR_RULES

    # ------------------------------------------------------------------.
    # 公共入口
    # ------------------------------------------------------------------.

    def validate_table(self, table: SrTableInfo) -> List[SrViolation]:
        """
        对一张表执行全部 StarRocks 合规检查。

        Args:
            table: SrTableInfo 实例

        Returns:
            所有违规项列表（可能为空）
        """
        violations: List[SrViolation] = []

        # SR_ADAPT_002: database 字段缺失则拒绝继续（防止误判）
        if not table.database:
            violations.append(SrViolation(
                rule_id="SR_ADAPT_002",
                level="HIGH",
                message="TableInfo.database 注入缺失，StarRocks 巡检中止以避免误判",
                detail={"table": table.name},
            ))
            return violations

        violations.extend(self._check_sr_layer_naming(table))
        violations.extend(self._check_sr_public_fields(table))
        violations.extend(self._check_sr_table_naming(table))
        violations.extend(self._check_sr_comment(table))
        violations.extend(self._check_sr_field_naming(table))
        violations.extend(self._check_sr_type_alignment(table))
        violations.extend(self._check_sr_view_naming(table))

        return violations

    @staticmethod
    def validate_database_whitelist(databases: List[str]) -> List[SrViolation]:
        """
        对整个 StarRocks 实例的数据库列表执行白名单检查（SR-015, SR-021）。
        此方法在 scan 级别执行一次，非逐表执行。
        """
        violations: List[SrViolation] = []

        # SR-015: 白名单
        sr015 = next((r for r in SR_RULES if r["rule_id"] == "RULE_SR_015"), None)
        if sr015:
            allowed = sr015["config_json"].get("allowed", [])
            for db in databases:
                if db not in allowed:
                    violations.append(SrViolation(
                        rule_id="RULE_SR_015",
                        level="HIGH",
                        message=f"数据库 '{db}' 不在白名单中",
                        detail={"database": db, "allowed": allowed},
                    ))

        # SR-021: 禁止 ods_hive
        sr021 = next((r for r in SR_RULES if r["rule_id"] == "RULE_SR_021"), None)
        if sr021:
            forbidden = sr021["config_json"].get("forbidden", [])
            for db in databases:
                if db in forbidden:
                    violations.append(SrViolation(
                        rule_id="RULE_SR_021",
                        level="HIGH",
                        message=f"数据库 '{db}' 为禁止使用的数据仓库（ADR-003 迁移要求）",
                        detail={"database": db, "forbidden": forbidden},
                    ))

        return violations

    # ------------------------------------------------------------------.
    # 规则实现
    # ------------------------------------------------------------------.

    def _check_sr_layer_naming(self, table: SrTableInfo) -> List[SrViolation]:
        """
        分层命名检查（SR-001~005, SR-016~018, SR-024）。
        根据 table.database 匹配对应分层规则。
        """
        violations: List[SrViolation] = []
        db = table.database

        layer_rules = [
            r for r in self.rules
            if r["category"] == "sr_layer_naming"
            and r["rule_id"] in (
                "RULE_SR_001", "RULE_SR_002", "RULE_SR_003",
                "RULE_SR_004", "RULE_SR_005",
                "RULE_SR_016", "RULE_SR_017", "RULE_SR_018",
                "RULE_SR_024",
            )
        ]

        for rule in layer_rules:
            cfg = rule["config_json"]
            databases = cfg.get("databases", [])
            # __all__ 表示所有库
            if databases != "__all__" and db not in databases:
                continue

            pattern = cfg.get("pattern")
            forbidden_prefixes = cfg.get("forbidden_prefixes", [])

            if pattern:
                try:
                    if not re.match(pattern, table.name):
                        violations.append(SrViolation(
                            rule_id=rule["rule_id"],
                            level=rule["level"],
                            message=f"表名 '{table.name}' 不符合分层命名规范: {rule['description']}",
                            detail={"database": db, "pattern": pattern, "table": table.name},
                        ))
                except re.error:
                    pass

            if forbidden_prefixes:
                for prefix in forbidden_prefixes:
                    if table.name.startswith(prefix):
                        violations.append(SrViolation(
                            rule_id=rule["rule_id"],
                            level=rule["level"],
                            message=f"表名 '{table.name}' 包含禁止的前缀 '{prefix}': {rule['description']}",
                            detail={"database": db, "prefix": prefix, "table": table.name},
                        ))
                        break

        return violations

    def _check_sr_public_fields(self, table: SrTableInfo) -> List[SrViolation]:
        """
        公共字段检查（SR-008~011）。
        根据 database 确定必需公共字段集合，对比 table.columns。
        """
        violations: List[SrViolation] = []
        db = table.database
        col_names = {c.name.lower() if hasattr(c, "name") else str(c).lower() for c in table.columns}
        # 兼容 dict 形式和 ColumnInfo 形式
        col_map: Dict[str, Any] = {}
        for c in table.columns:
            name = c.name if hasattr(c, "name") else c.get("name") if isinstance(c, dict) else str(c)
            col_map[name.lower()] = c

        public_field_rules = [
            r for r in self.rules if r["category"] == "sr_public_fields"
        ]

        for rule in public_field_rules:
            cfg = rule["config_json"]
            databases = cfg.get("databases", [])
            if databases != "__all__" and db not in databases:
                continue

            required_fields = cfg.get("required_fields", [])
            for field_req in required_fields:
                fname = field_req["name"]
                ftype = field_req["type"]
                if fname.lower() not in col_names:
                    violations.append(SrViolation(
                        rule_id=rule["rule_id"],
                        level=rule["level"],
                        message=f"表 '{table.name}' 缺少必需公共字段 '{fname}' ({ftype})",
                        detail={"database": db, "table": table.name, "field": fname, "expected_type": ftype},
                    ))

        return violations

    def _check_sr_table_naming(self, table: SrTableInfo) -> List[SrViolation]:
        """
        表名命名规范（SR-022, SR-023）。
        """
        violations: List[SrViolation] = []
        name = table.name

        # SR-022: 表名含中文
        sr022 = next((r for r in self.rules if r["rule_id"] == "RULE_SR_022"), None)
        if sr022:
            pattern = sr022["config_json"].get("pattern_forbidden", "")
            if pattern and re.search(pattern, name):
                violations.append(SrViolation(
                    rule_id="RULE_SR_022",
                    level="HIGH",
                    message=f"表名 '{name}' 包含中文字符",
                    detail={"table": name, "pattern_forbidden": pattern},
                ))

        # SR-023: 表名含版本号
        sr023 = next((r for r in self.rules if r["rule_id"] == "RULE_SR_023"), None)
        if sr023:
            pattern = sr023["config_json"].get("pattern_forbidden", "")
            if pattern and re.search(pattern, name):
                violations.append(SrViolation(
                    rule_id="RULE_SR_023",
                    level="MEDIUM",
                    message=f"表名 '{name}' 包含版本号后缀",
                    detail={"table": name, "pattern_forbidden": pattern},
                ))

        return violations

    def _check_sr_comment(self, table: SrTableInfo) -> List[SrViolation]:
        """
        注释检查（SR-013, SR-014）。
        SR-014: 表注释为空 → HIGH
        SR-013: 字段注释覆盖率 < 100% → HIGH
        """
        violations: List[SrViolation] = []

        # SR-014: 表注释
        sr014 = next((r for r in self.rules if r["rule_id"] == "RULE_SR_014"), None)
        if sr014:
            if not table.comment or not table.comment.strip():
                violations.append(SrViolation(
                    rule_id="RULE_SR_014",
                    level="HIGH",
                    message=f"表 '{table.name}' 缺少表注释（COMMENT）",
                    detail={"database": table.database, "table": table.name},
                ))

        # SR-013: 字段注释覆盖率
        sr013 = next((r for r in self.rules if r["rule_id"] == "RULE_SR_013"), None)
        if sr013:
            cfg = sr013["config_json"]
            min_coverage = cfg.get("min_coverage", 1.0)

            total_cols = len(table.columns)
            if total_cols == 0:
                coverage = 1.0
            else:
                commented = 0
                for col in table.columns:
                    comment = col.comment if hasattr(col, "comment") else (col.get("comment") if isinstance(col, dict) else "")
                    if comment and comment.strip():
                        commented += 1
                coverage = commented / total_cols

            if coverage < float(min_coverage):
                violations.append(SrViolation(
                    rule_id="RULE_SR_013",
                    level="HIGH",
                    message=f"表 '{table.name}' 字段注释覆盖率 {coverage:.1%} < {min_coverage:.0%}",
                    detail={"database": table.database, "table": table.name, "coverage": coverage, "min_coverage": min_coverage},
                ))

        return violations

    def _check_sr_field_naming(self, table: SrTableInfo) -> List[SrViolation]:
        """
        字段命名规范（SR-012）。
        长度 ≤ 40，^[a-z][a-z0-9_]*$。
        """
        violations: List[SrViolation] = []
        sr012 = next((r for r in self.rules if r["rule_id"] == "RULE_SR_012"), None)
        if not sr012:
            return violations

        cfg = sr012["config_json"]
        pattern = cfg.get("pattern", "^[a-z][a-z0-9_]*$")
        max_length = cfg.get("max_length", 40)

        for col in table.columns:
            cname = col.name if hasattr(col, "name") else (col.get("name") if isinstance(col, dict) else "")
            if not cname:
                continue

            if len(cname) > max_length:
                violations.append(SrViolation(
                    rule_id="RULE_SR_012",
                    level="HIGH",
                    message=f"字段名 '{cname}' 长度 {len(cname)} 超过限制 {max_length}",
                    detail={"database": table.database, "table": table.name, "column": cname, "length": len(cname), "max_length": max_length},
                ))

            try:
                if not re.match(pattern, cname):
                    violations.append(SrViolation(
                        rule_id="RULE_SR_012",
                        level="HIGH",
                        message=f"字段名 '{cname}' 不符合 snake_case 规范（应匹配 {pattern}）",
                        detail={"database": table.database, "table": table.name, "column": cname, "pattern": pattern},
                    ))
            except re.error:
                pass

        return violations

    def _check_sr_type_alignment(self, table: SrTableInfo) -> List[SrViolation]:
        """
        字段类型对齐（SR-006, SR-007, SR-019, SR-020）。
        按后缀匹配规则：
          _amt/_amount  → DECIMAL
          _time/_at/_dt → DATETIME/DATE/TIMESTAMP
          _qty/_cnt     → BIGINT/DECIMAL/INT
          _rate         → DECIMAL
        """
        violations: List[SrViolation] = []
        type_rules = [
            r for r in self.rules
            if r["category"] == "sr_type_alignment"
            and r["rule_id"] in ("RULE_SR_006", "RULE_SR_007", "RULE_SR_019", "RULE_SR_020")
        ]

        for rule in type_rules:
            cfg = rule["config_json"]
            suffixes = cfg.get("suffixes", [])
            required_type = cfg.get("required_type") or cfg.get("required_types", [])
            if isinstance(required_type, str):
                required_type = [required_type]
            forbidden_types = [t.upper() for t in cfg.get("forbidden_types", [])]

            for col in table.columns:
                cname = col.name if hasattr(col, "name") else (col.get("name") if isinstance(col, dict) else "")
                ctype = (col.data_type if hasattr(col, "data_type") else (col.get("data_type") if isinstance(col, dict) else "")).upper()

                if not cname or not ctype:
                    continue

                # 检查后缀匹配
                matched = False
                for suffix in suffixes:
                    if cname.endswith(suffix):
                        matched = True
                        break
                if not matched:
                    continue

                # 检查类型
                if ctype in forbidden_types:
                    violations.append(SrViolation(
                        rule_id=rule["rule_id"],
                        level=rule["level"],
                        message=f"字段 '{cname}' 类型为 {ctype}，违反后缀规则（应使用 {'/'.join(required_type)}）",
                        detail={"database": table.database, "table": table.name, "column": cname, "type": ctype, "required": required_type},
                    ))
                elif required_type and ctype not in required_type:
                    violations.append(SrViolation(
                        rule_id=rule["rule_id"],
                        level=rule["level"],
                        message=f"字段 '{cname}' 类型为 {ctype}，应为 {'/'.join(required_type)}",
                        detail={"database": table.database, "table": table.name, "column": cname, "type": ctype, "required": required_type},
                    ))

        return violations

    def _check_sr_view_naming(self, table: SrTableInfo) -> List[SrViolation]:
        """
        视图命名（SR-025）。
        仅对 table_type='VIEW' 的对象执行。
        """
        violations: List[SrViolation] = []
        if table.table_type != "VIEW":
            return violations

        sr025 = next((r for r in self.rules if r["rule_id"] == "RULE_SR_025"), None)
        if sr025:
            pattern = sr025["config_json"].get("pattern", "_vw$")
            if not re.search(pattern, table.name):
                violations.append(SrViolation(
                    rule_id="RULE_SR_025",
                    level="MEDIUM",
                    message=f"视图 '{table.name}' 未以 _vw 后缀命名",
                    detail={"database": table.database, "view": table.name, "pattern": pattern},
                ))

        return violations

