"""SQL Agent — 各方言执行器"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager

import sqlglot

from app.core.errors import MulanError

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 连接配置
# -----------------------------------------------------------------------------

@contextmanager
def _get_target_db_connection(datasource_config: dict, db_type: str, timeout_seconds: int):
    """
    建立到目标数据库的连接。
    datasource_config 来自 bi_data_sources.decrypt()，包含 host/port/username/password/database
    返回 context manager，自动关闭连接。
    """
    import socket

    host = datasource_config.get("host", "")
    port = int(datasource_config.get("port", 0))
    user = datasource_config.get("username", "")
    password = datasource_config.get("password", "")
    database = datasource_config.get("database", "")

    timeout = min(timeout_seconds, 30)

    if db_type == "mysql":
        import pymysql
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=timeout,
            read_timeout=timeout,
            write_timeout=timeout,
            charset="utf8mb4",
        )
        try:
            yield conn
        finally:
            conn.close()

    elif db_type == "postgresql":
        import psycopg2
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database,
            connect_timeout=timeout,
            options=f"-c statement_timeout={timeout_seconds * 1000}",
        )
        try:
            yield conn
        finally:
            conn.close()

    elif db_type == "starrocks":
        # StarRocks 使用 MySQL 协议（pymysql）
        import pymysql
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=timeout,
            read_timeout=timeout,
            write_timeout=timeout,
            charset="utf8mb4",
        )
        try:
            yield conn
        finally:
            conn.close()

    else:
        raise MulanError("DS_004", f"不支持的数据库类型: {db_type}", 400)


# -----------------------------------------------------------------------------
# 执行器基类
# -----------------------------------------------------------------------------

class BaseExecutor(ABC):
    """方言执行器基类"""

    def __init__(self, db_type: str, datasource_config: dict, timeout_seconds: int):
        self.db_type = db_type
        self.datasource_config = datasource_config
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    def execute(self, sql: str) -> Tuple[List[dict], List[str]]:
        """执行 SQL，返回 (rows, column_names)"""
        ...

    def _rows_to_dicts(self, cursor) -> Tuple[List[dict], List[str]]:
        """将 cursor 结果转换为 list[dict] + column_names"""
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return rows, columns


class MySQLExecutor(BaseExecutor):
    def execute(self, sql: str) -> Tuple[List[dict], List[str]]:
        with _get_target_db_connection(self.datasource_config, self.db_type, self.timeout_seconds) as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(sql)
                rows, columns = self._rows_to_dicts(cursor)
                conn.commit()
                return rows, columns


class PostgreSQLExecutor(BaseExecutor):
    def execute(self, sql: str) -> Tuple[List[dict], List[str]]:
        with _get_target_db_connection(self.datasource_config, self.db_type, self.timeout_seconds) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                rows, columns = self._rows_to_dicts(cursor)
                conn.commit()
                return rows, columns


class StarRocksExecutor(BaseExecutor):
    def execute(self, sql: str) -> Tuple[List[dict], List[str]]:
        with _get_target_db_connection(self.datasource_config, self.db_type, self.timeout_seconds) as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(sql)
                rows, columns = self._rows_to_dicts(cursor)
                conn.commit()
                return rows, columns


def get_executor(db_type: str, datasource_config: dict, timeout_seconds: int) -> BaseExecutor:
    """工厂方法：获取对应方言的执行器"""
    if db_type == "mysql":
        return MySQLExecutor(db_type, datasource_config, timeout_seconds)
    elif db_type == "postgresql":
        return PostgreSQLExecutor(db_type, datasource_config, timeout_seconds)
    elif db_type == "starrocks":
        return StarRocksExecutor(db_type, datasource_config, timeout_seconds)
    else:
        raise MulanError("DS_004", f"不支持的数据库类型: {db_type}", 400)
