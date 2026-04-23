"""DQC 表 Profiling

职责：
- 采样 10k 行（或全表，若 < 10k）
- 统计：row_count / column_stats (type, null_count, null_rate, distinct_count, min, max)
- 提取字段样本值（top 20 + 10 random）用于 LLM 建议规则
- 识别候选主键列（distinct ≈ row_count）与候选时间戳列
"""
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import column, func, select, table

from .constants import PROFILING_SAMPLE_ROWS


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value.strftime("%Y-%m-%d")
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).decode("utf-8", errors="replace")
        except Exception:
            return "<binary>"
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


@dataclass
class ColumnProfile:
    name: str
    data_type: str
    null_count: int
    null_rate: float
    distinct_count: Optional[int] = None
    min_value: Any = None
    max_value: Any = None
    sample_values: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "null_count": self.null_count,
            "null_rate": self.null_rate,
            "distinct_count": self.distinct_count,
            "min_value": _json_safe(self.min_value),
            "max_value": _json_safe(self.max_value),
            "sample_values": [_json_safe(v) for v in self.sample_values],
        }


@dataclass
class TableProfile:
    row_count: int
    sampled_rows: int
    columns: List[ColumnProfile]
    profiled_at: str
    has_timestamp_column: bool
    candidate_timestamp_columns: List[str]
    candidate_id_columns: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_count": self.row_count,
            "sampled_rows": self.sampled_rows,
            "columns": [c.to_dict() for c in self.columns],
            "profiled_at": self.profiled_at,
            "has_timestamp_column": self.has_timestamp_column,
            "candidate_timestamp_columns": self.candidate_timestamp_columns,
            "candidate_id_columns": self.candidate_id_columns,
        }


_TIMESTAMP_TYPES = {
    "datetime", "timestamp", "timestamptz", "timestamp_ntz", "timestamp_ltz",
    "date", "time", "datetime2",
}
_NUMERIC_TYPES = {"int", "bigint", "smallint", "tinyint", "integer", "float", "double", "decimal", "numeric", "real"}


def _normalize_type(raw: str) -> str:
    if not raw:
        return ""
    lower = str(raw).lower().split("(", 1)[0].strip()
    return lower


def _is_timestamp_type(raw: str) -> bool:
    return _normalize_type(raw) in _TIMESTAMP_TYPES


def _is_numeric_type(raw: str) -> bool:
    return _normalize_type(raw) in _NUMERIC_TYPES


class Profiler:
    """表 Profiling

    db_config:
      {"db_type", "host", "port", "user", "password", "database", "readonly": True}
    """

    def __init__(self, db_config: dict):
        self.db_config = db_config
        self.db_type = (db_config.get("db_type") or "").lower()

    def profile_table(self, schema: str, table_name: str, sample_rows: int = PROFILING_SAMPLE_ROWS) -> TableProfile:
        """采样并返回 TableProfile

        真实 DB 连接由 ConnectionHub / QualitySQLEngine 负责；此处给出端到端骨架。
        实现：
          1. 读取字段列表（information_schema）
          2. SELECT * FROM table LIMIT sample_rows
          3. 用 Python 聚合统计
        """
        conn = self._connect_target()
        try:
            columns_meta = self._introspect_columns(conn, schema, table_name)
            total_rows = self._count_rows(conn, schema, table_name)
            sampled_rows_data = self._sample_rows(conn, schema, table_name, columns_meta, sample_rows)
        finally:
            self._close(conn)

        sampled_count = len(sampled_rows_data)
        columns: List[ColumnProfile] = []
        for col_name, col_type in columns_meta:
            values = [row.get(col_name) for row in sampled_rows_data]
            null_count = sum(1 for v in values if v is None)
            non_null = [v for v in values if v is not None]
            distinct_count = len(set(non_null)) if non_null else 0
            null_rate = (null_count / sampled_count) if sampled_count else 0.0

            min_value = None
            max_value = None
            if non_null:
                try:
                    min_value = min(non_null)
                    max_value = max(non_null)
                except TypeError:
                    min_value = None
                    max_value = None

            sample_values = self._pick_sample_values(non_null)

            columns.append(
                ColumnProfile(
                    name=col_name,
                    data_type=str(col_type or ""),
                    null_count=null_count,
                    null_rate=round(null_rate, 4),
                    distinct_count=distinct_count,
                    min_value=min_value,
                    max_value=max_value,
                    sample_values=sample_values,
                )
            )

        candidate_timestamp_columns = [
            c.name for c in columns if _is_timestamp_type(c.data_type)
        ]
        candidate_id_columns = self._detect_id_columns(columns, sampled_count)

        return TableProfile(
            row_count=total_rows,
            sampled_rows=sampled_count,
            columns=columns,
            profiled_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            has_timestamp_column=bool(candidate_timestamp_columns),
            candidate_timestamp_columns=candidate_timestamp_columns,
            candidate_id_columns=candidate_id_columns,
        )

    def to_json(self, profile: TableProfile) -> Dict[str, Any]:
        return profile.to_dict()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _pick_sample_values(self, non_null: List[Any], top_n: int = 20, random_n: int = 10) -> List[Any]:
        if not non_null:
            return []
        from collections import Counter
        import random

        counter: Counter = Counter()
        for v in non_null:
            try:
                counter[v] += 1
            except TypeError:
                counter[str(v)] += 1
        top = [v for v, _ in counter.most_common(top_n)]
        top_set = set(top)
        pool = [v for v in non_null if v not in top_set]
        random_sample: List[Any] = []
        if pool:
            random_sample = random.sample(pool, min(random_n, len(pool)))
        combined = top + random_sample
        return combined[: top_n + random_n]

    def _detect_id_columns(self, columns: List[ColumnProfile], sampled: int) -> List[str]:
        if sampled <= 0:
            return []
        out = []
        for c in columns:
            if c.distinct_count is None:
                continue
            non_null_count = sampled - c.null_count
            if non_null_count <= 0:
                continue
            ratio = c.distinct_count / non_null_count
            if ratio >= 0.98 and c.null_rate <= 0.01:
                out.append(c.name)
        return out

    # ------------------------------------------------------------------
    # DB 访问（由 connection hub 或直连驱动提供）
    # ------------------------------------------------------------------

    def _connect_target(self):
        """建立只读连接。"""
        from sqlalchemy import create_engine

        db_type = self.db_type
        user = self.db_config.get("user")
        password = self.db_config.get("password")
        host = self.db_config.get("host")
        port = self.db_config.get("port")
        database = self.db_config.get("database")

        if db_type == "postgresql":
            url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
            connect_args = {"options": "-c default_transaction_read_only=on"}
        elif db_type in ("mysql", "starrocks", "doris"):
            url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
            connect_args = {}
        else:
            url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
            connect_args = {}

        engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
        return engine.connect()

    def _close(self, conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def _introspect_columns(self, conn, schema: str, table_name: str) -> List[tuple]:
        """返回 [(column_name, data_type), ...]，使用 information_schema.columns（PG/MySQL 均兼容）"""
        from sqlalchemy import text as sa_text_fn

        stmt = sa_text_fn(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :tname "
            "ORDER BY ordinal_position"
        )
        result = conn.execute(stmt, {"schema": schema, "tname": table_name})
        return [(r[0], r[1]) for r in result.fetchall()]

    def _count_rows(self, conn, schema: str, table_name: str) -> int:
        tbl = table(table_name, schema=schema)
        stmt = select(func.count()).select_from(tbl)
        result = conn.execute(stmt)
        row = result.fetchone()
        return int(row[0]) if row else 0

    def _sample_rows(
        self,
        conn,
        schema: str,
        table_name: str,
        columns_meta: List[tuple],
        sample_rows: int,
    ) -> List[Dict[str, Any]]:
        cols = [column(name) for name, _ in columns_meta]
        tbl = table(table_name, schema=schema)
        stmt = select(*cols).select_from(tbl).limit(sample_rows)
        result = conn.execute(stmt)
        out: List[Dict[str, Any]] = []
        names = [name for name, _ in columns_meta]
        for row in result.fetchall():
            out.append(dict(zip(names, row)))
        return out
