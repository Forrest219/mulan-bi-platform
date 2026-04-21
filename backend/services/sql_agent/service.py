"""SQL Agent — 主服务层"""

import logging
import time
from typing import Optional, Tuple, List, Dict, Any

import sqlglot
from sqlglot import exp

from app.core.errors import MulanError
from app.core.database import SessionLocal

from .models import SQLAgentQueryLog
from .security import (
    SQLSecurityValidator,
    ValidationResult,
    LIMIT_CEILING,
    QUERY_TIMEOUT,
    SQLGLOT_DIALECT_MAP,
    MYSQL_WRITE_BLOCKED,
)
from .executor import get_executor

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 内部异常
# -----------------------------------------------------------------------------

class SQLAgentError(MulanError):
    """SQL Agent 统一异常"""
    def __init__(self, error_code: str, message: str, status_code: int = 400, detail: dict = None):
        super().__init__(error_code, message, status_code, detail)


# -----------------------------------------------------------------------------
# 主服务
# -----------------------------------------------------------------------------

class SQLAgentService:
    """
    SQL Agent 服务层。

    使用方式（FastAPI 路由中）：
        from services.sql_agent import SQLAgentService
        svc = SQLAgentService(db_session)
        result = svc.execute_query(datasource_id=1, sql="SELECT ...", user_id=123)
    """

    def __init__(self, db_session):
        self.db = db_session

    # -------------------------------------------------------------------------
    # 公共 API
    # -------------------------------------------------------------------------

    def execute_query(
        self,
        datasource_id: int,
        sql: str,
        user_id: int,
        timeout_seconds: Optional[int] = None,
    ) -> dict:
        """
        执行 SQL 查询的完整流程：
        1. 加载数据源配置
        2. 安全校验
        3. LIMIT 注入
        4. 执行
        5. 写入日志

        Returns:
            {
                "log_id": int,
                "sql_hash": str,
                "action_type": str,
                "row_count": int | None,
                "duration_ms": int,
                "limit_applied": int | None,
                "data": list[dict],
                "columns": list[str],
                "truncated": bool,
                "truncated_reason": str | None,
                "warning": str | None,
            }
        Raises:
            SQLAgentError: 校验失败或执行失败
        """
        # Step 1: 加载数据源
        ds = self._get_datasource(datasource_id)
        db_type = ds.get("db_type", "")
        ds_config = self._decrypt_datasource_config(ds)

        # Step 2: 安全校验
        validator = SQLSecurityValidator(db_type)
        validation = validator.validate(sql)

        if not validation.ok:
            # 记录拒绝日志
            log_id = self._log_query(
                datasource_id=datasource_id,
                db_type=db_type,
                sql_text=sql,
                sql_hash=SQLAgentQueryLog.compute_sql_hash(sql),
                action_type="REJECTED",
                rejected_reason=validation.reason,
                row_count=None,
                duration_ms=0,
                limit_applied=None,
                user_id=user_id,
            )
            raise SQLAgentError(
                error_code=validation.error_code or "SQLA_001",
                message="违反安全策略",
                status_code=400,
                detail={"log_id": log_id, "rejected_sql": sql, "reason": validation.reason},
            )

        # Step 3: LIMIT 注入
        validated_sql, limit_applied, limit_warning = self._inject_limit(
            sql, db_type, validation.action_type
        )

        # Step 4: 执行
        effective_timeout = timeout_seconds or QUERY_TIMEOUT.get(db_type, 30)
        start_time = time.perf_counter()
        truncated = False
        truncated_reason: Optional[str] = None

        try:
            executor = get_executor(db_type, ds_config, effective_timeout)
            rows, columns = executor.execute(validated_sql)
        except MulanError:
            raise
        except Exception as e:
            logger.exception("SQL 执行失败: datasource_id=%s, sql=%s", datasource_id, validated_sql)
            log_id = self._log_query(
                datasource_id=datasource_id,
                db_type=db_type,
                sql_text=validated_sql,
                sql_hash=SQLAgentQueryLog.compute_sql_hash(validated_sql),
                action_type=validation.action_type,
                rejected_reason=None,
                row_count=None,
                duration_ms=int((time.perf_counter() - start_time) * 1000),
                limit_applied=limit_applied,
                user_id=user_id,
            )
            raise SQLAgentError(
                error_code="SQLA_007",
                message="SQL 执行引擎异常",
                status_code=500,
                detail={"log_id": log_id, "error": str(e)},
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # 判断是否截断
        if limit_applied is not None and len(rows) >= limit_applied:
            truncated = True
            truncated_reason = "limit_applied"

        # Step 5: 写入日志
        log_id = self._log_query(
            datasource_id=datasource_id,
            db_type=db_type,
            sql_text=validated_sql,
            sql_hash=SQLAgentQueryLog.compute_sql_hash(validated_sql),
            action_type=validation.action_type,
            rejected_reason=None,
            row_count=len(rows),
            duration_ms=duration_ms,
            limit_applied=limit_applied,
            user_id=user_id,
        )

        return {
            "log_id": log_id,
            "sql_hash": SQLAgentQueryLog.compute_sql_hash(validated_sql),
            "action_type": validation.action_type,
            "row_count": len(rows),
            "duration_ms": duration_ms,
            "limit_applied": limit_applied,
            "data": rows,
            "columns": columns,
            "truncated": truncated,
            "truncated_reason": truncated_reason,
            "warning": limit_warning,
        }

    def get_query_log(self, log_id: int, user_id: int) -> dict:
        """查询历史记录（不含结果数据）"""
        log = self.db.query(SQLAgentQueryLog).filter(
            SQLAgentQueryLog.id == log_id,
            SQLAgentQueryLog.user_id == user_id,
        ).first()

        if not log:
            raise SQLAgentError("SQLA_404", "查询记录不存在", 404)

        return log.to_dict()

    def preview_datasource(
        self,
        datasource_id: int,
        user_id: int,
    ) -> dict:
        """
        预览数据源表结构（不返回数据行，仅 schema）。
        """
        ds = self._get_datasource(datasource_id)
        db_type = ds.get("db_type", "")
        ds_config = self._decrypt_datasource_config(ds)
        timeout = 30

        # 查询表列表
        if db_type == "mysql":
            table_sql = """
                SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name,
                       TABLE_ROWS AS row_count_estimate
                FROM information_schema.tables
                WHERE TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                ORDER BY TABLE_ROWS DESC
                LIMIT 100
            """
        elif db_type == "postgresql":
            table_sql = """
                SELECT schemaname AS schema_name, tablename AS table_name,
                       n_live_tup AS row_count_estimate
                FROM pg_stat_user_tables
                ORDER BY n_live_tup DESC
                LIMIT 100
            """
        elif db_type == "starrocks":
            table_sql = """
                SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name,
                       TABLE_ROWS AS row_count_estimate
                FROM information_schema.tables
                WHERE TABLE_SCHEMA NOT IN ('information_schema')
                ORDER BY TABLE_ROWS DESC
                LIMIT 100
            """
        else:
            raise SQLAgentError("DS_004", f"不支持的数据库类型: {db_type}", 400)

        executor = get_executor(db_type, ds_config, timeout)
        rows, _ = executor.execute(table_sql)

        # 对每个表查询列信息
        tables = []
        for row in rows:
            schema_name = row.get("schema_name", "def")
            table_name = row.get("table_name", "")
            row_count = row.get("row_count_estimate") or 0

            columns = self._get_table_columns(db_type, ds_config, timeout, schema_name, table_name)
            tables.append({
                "schema": schema_name,
                "name": table_name,
                "row_count_estimate": int(row_count),
                "columns": columns,
            })

        return {
            "datasource_id": datasource_id,
            "db_type": db_type,
            "tables": tables,
        }

    # -------------------------------------------------------------------------
    # 内部方法
    # -------------------------------------------------------------------------

    def _get_datasource(self, datasource_id: int) -> dict:
        """从 bi_data_sources 加载数据源配置（未解密）"""
        from services.datasources.models import DataSource
        ds = self.db.query(DataSource).filter(DataSource.id == datasource_id).first()
        if not ds:
            raise SQLAgentError("DS_001", "数据源不存在", 404)
        return {
            "id": ds.id,
            "name": ds.name,
            "db_type": ds.db_type,
            "config_encrypted": ds.config_json,
            "owner_id": ds.owner_id,
        }

    def _decrypt_datasource_config(self, ds: dict) -> dict:
        """解密数据源连接配置"""
        from services.common.crypto import CryptoHelper
        from app.core.config import get_settings
        settings = get_settings()
        crypto = CryptoHelper(settings.DATASOURCE_ENCRYPTION_KEY)
        encrypted_config = ds.get("config_encrypted", "{}")
        import json
        try:
            config = json.loads(encrypted_config)
        except Exception:
            raise SQLAgentError("DS_005", "数据源配置解密失败", 500)
        return {
            "host": config.get("host", ""),
            "port": int(config.get("port", 0)),
            "username": config.get("username", ""),
            "password": crypto.decrypt(config.get("password_encrypted", "")) if config.get("password_encrypted") else "",
            "database": config.get("database", ""),
        }

    def _inject_limit(
        self, sql: str, db_type: str, action_type: str
    ) -> Tuple[str, Optional[int], Optional[str]]:
        """
        注入或校验 LIMIT。
        - 无 LIMIT → 追加默认 LIMIT
        - 有 LIMIT < 上限 → 保持不变
        - 有 LIMIT > 上限 → 强制截断，返回警告
        """
        ceiling = LIMIT_CEILING.get(db_type, 5_000)
        dialect = SQLGLOT_DIALECT_MAP.get(db_type, db_type)

        try:
            parsed = sqlglot.parse(sql, dialect=dialect)
        except Exception:
            # 解析失败，不注入，走原 SQL
            return sql, None, None

        if not parsed:
            return sql, None, None

        statement = parsed[0]

        # 获取最外层 LIMIT
        limit_node = statement.find(exp.Limit)

        if limit_node is None:
            # 无 LIMIT，追加
            new_sql = f"{sql.rstrip(';')} LIMIT {ceiling}"
            return new_sql, ceiling, None
        else:
            # 有 LIMIT，检查是否超限
            limit_value = self._extract_limit_value(limit_node)
            if limit_value is None:
                return sql, None, None
            if limit_value > ceiling:
                # 强制截断
                new_sql = self._replace_limit(statement, ceiling, db_type)
                return new_sql, ceiling, "SQLA_W01"
            else:
                return sql, limit_value, None

    def _extract_limit_value(self, limit_node) -> Optional[int]:
        """从 LIMIT 节点提取数值"""
        if limit_node.args.get("limit"):
            limit_exp = limit_node.args["limit"]
            if isinstance(limit_exp, exp.Literal) and limit_exp.is_numeric:
                return int(limit_exp.name)
        return None

    def _replace_limit(self, statement, new_limit: int, db_type: str) -> str:
        """替换 LIMIT 值"""
        # 直接字符串替换（简单有效）
        limit_node = statement.find(exp.Limit)
        if limit_node:
            statement.set("limit", exp.Limit(expression=exp.Literal.number(new_limit)))
        return statement.sql(dialect=db_type)

    def _get_table_columns(
        self, db_type: str, ds_config: dict, timeout: int, schema_name: str, table_name: str
    ) -> List[dict]:
        """查询指定表的列信息"""
        if db_type == "mysql":
            col_sql = """
                SELECT COLUMN_NAME AS name, DATA_TYPE AS type,
                       IS_NULLABLE AS nullable, COLUMN_KEY AS key
                FROM information_schema.columns
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
            """
            params = (schema_name, table_name)
        elif db_type == "postgresql":
            col_sql = """
                SELECT column_name AS name, data_type AS type,
                       is_nullable AS nullable
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """
            params = (schema_name, table_name)
        elif db_type == "starrocks":
            col_sql = """
                SELECT COLUMN_NAME AS name, DATA_TYPE AS type,
                       IS_NULLABLE AS nullable
                FROM information_schema.columns
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
            """
            params = (schema_name, table_name)
        else:
            return []

        try:
            executor = get_executor(db_type, ds_config, timeout)
            rows, _ = executor.execute(col_sql, params)
            return rows
        except Exception:
            return []

    def _log_query(
        self,
        datasource_id: int,
        db_type: str,
        sql_text: str,
        sql_hash: str,
        action_type: str,
        rejected_reason: Optional[str],
        row_count: Optional[int],
        duration_ms: int,
        limit_applied: Optional[int],
        user_id: int,
    ) -> int:
        """写入 sql_agent_query_log，返回 log_id"""
        log = SQLAgentQueryLog(
            datasource_id=datasource_id,
            db_type=db_type,
            sql_text=sql_text,
            sql_hash=sql_hash,
            action_type=action_type,
            rejected_reason=rejected_reason,
            row_count=row_count,
            duration_ms=duration_ms,
            limit_applied=limit_applied,
            user_id=user_id,
        )
        self.db.add(log)
        self.db.flush()
        return log.id
