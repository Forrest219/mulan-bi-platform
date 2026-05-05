"""数据库连接模块"""
import logging
import yaml
from typing import Optional, Dict, Any
from urllib.parse import quote_plus
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class DatabaseConnector:
    """数据库连接器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化数据库连接器

        Args:
            config: 数据库配置，包含 host, port, user, password, database, db_type
        """
        self.config = config or {}
        self.engine: Optional[Engine] = None
        self.inspector = None

    def connect(self) -> bool:
        """
        建立数据库连接

        Returns:
            连接是否成功
        """
        try:
            connection_string = self._build_connection_string()
            connect_args = {}
            db_type = self.config.get("db_type", "mysql")
            # P1 修复：网络数据库（MySQL/PostgreSQL）添加 10 秒连接超时，防止黑洞 IP 雪崩
            if db_type in ("mysql", "postgresql", "starrocks"):
                connect_args["connect_timeout"] = 10
            self.engine = create_engine(
                connection_string,
                echo=False,
                connect_args=connect_args if connect_args else None,
            )
            self.inspector = inspect(self.engine)
            return True
        except Exception as e:
            # Redact password from connection string in error message before logging
            import re
            error_str = str(e)
            error_str = re.sub(r'(://[^:]+:)[^@]+(@)', r'\1***\2', error_str)
            logger.error("数据库连接失败: %s", error_str, exc_info=False)
            return False

    def disconnect(self):
        """关闭数据库连接"""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            self.inspector = None

    def _build_connection_string(self) -> str:
        """构建数据库连接字符串"""
        db_type = self.config.get("db_type", "mysql")
        host = self.config.get("host", "localhost")
        port = self.config.get("port", 3306)
        user = quote_plus(self.config.get("user", "root"))
        password = quote_plus(self.config.get("password", ""))
        database = self.config.get("database", "")

        if db_type == "mysql":
            db_path = f"/{database}" if database else ""
            return f"mysql+pymysql://{user}:{password}@{host}:{port}{db_path}"
        elif db_type == "postgresql":
            db_path = f"/{database}" if database else ""
            return f"postgresql://{user}:{password}@{host}:{port}{db_path}"
        elif db_type == "sqlite":
            return f"sqlite:///{database}"
        elif db_type == "starrocks":
            port = self.config.get("port", 9030)
            db_path = f"/{database}" if database else ""
            return f"mysql+pymysql://{user}:{password}@{host}:{port}{db_path}"
        else:
            raise ValueError(f"不支持的数据库类型: {db_type}")

    def get_table_names(self) -> list:
        """获取所有表名"""
        if not self.inspector:
            raise RuntimeError("请先连接数据库")
        return self.inspector.get_table_names()

    def get_table_columns(self, table_name: str) -> list:
        """获取表的所有列信息"""
        if not self.inspector:
            raise RuntimeError("请先连接数据库")
        return self.inspector.get_columns(table_name)

    def get_table_indexes(self, table_name: str) -> list:
        """获取表的索引信息"""
        if not self.inspector:
            raise RuntimeError("请先连接数据库")
        return self.inspector.get_indexes(table_name)

    def get_table_primary_key(self, table_name: str) -> dict:
        """获取表的主键信息"""
        if not self.inspector:
            raise RuntimeError("请先连接数据库")
        return self.inspector.get_pk_constraint(table_name)

    def get_table_foreign_keys(self, table_name: str) -> list:
        """获取表的外键信息"""
        if not self.inspector:
            raise RuntimeError("请先连接数据库")
        return self.inspector.get_foreign_keys(table_name)

    def get_table_comment(self, table_name: str) -> str:
        """获取表的注释"""
        if not self.inspector:
            raise RuntimeError("请先连接数据库")

        if self.config.get("db_type") in ("mysql", "starrocks"):
            try:
                with self.engine.connect() as conn:
                    result = conn.execute(
                        text("SELECT TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_NAME = :table_name"),
                        {"table_name": table_name}
                    )
                    row = result.fetchone()
                    return row[0] if row else ""
            except Exception as e:
                logger.warning(f"获取表注释失败 (table={table_name}): {e}")
                return ""
        return ""

    def get_column_comment(self, table_name: str, column_name: str) -> str:
        """获取列的注释"""
        if not self.inspector:
            raise RuntimeError("请先连接数据库")

        if self.config.get("db_type") in ("mysql", "starrocks"):
            try:
                with self.engine.connect() as conn:
                    result = conn.execute(
                        text("SELECT COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"),
                        {"table_name": table_name, "column_name": column_name}
                    )
                    row = result.fetchone()
                    return row[0] if row else ""
            except Exception as e:
                logger.warning(f"获取列注释失败 (table={table_name}, column={column_name}): {e}")
                return ""
        return ""

    def show_partitions(self, db: str, tbl: str) -> list:
        """
        查询 StarRocks 分区信息

        Args:
            db: 数据库名
            tbl: 表名

        Returns:
            分区信息列表，每条记录为一个 dict
        """
        if self.config.get("db_type") != "starrocks":
            return []
        try:
            sql = f"SHOW PARTITIONS FROM `{db}`.`{tbl}`"
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                columns = result.keys()
                return [dict(zip(columns, row)) for row in result.fetchall()]
        except Exception as e:
            logger.warning(f"查询分区信息失败 (db={db}, tbl={tbl}): {e}")
            return []

    def show_tablets(self, db: str, tbl: str) -> list:
        """
        查询 StarRocks Tablet 信息

        Args:
            db: 数据库名
            tbl: 表名

        Returns:
            Tablet 信息列表，每条记录为一个 dict
        """
        if self.config.get("db_type") != "starrocks":
            return []
        try:
            sql = f"SHOW TABLETS FROM `{db}`.`{tbl}`"
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                columns = result.keys()
                return [dict(zip(columns, row)) for row in result.fetchall()]
        except Exception as e:
            logger.warning(f"查询 Tablet 信息失败 (db={db}, tbl={tbl}): {e}")
            return []

    @staticmethod
    def from_yaml(config_path: str) -> "DatabaseConnector":
        """从 YAML 配置文件加载配置并创建连接器"""
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        connector = DatabaseConnector(config.get("database", {}))
        return connector

    def create_target_engine(self, conn_url: str = None) -> Engine:
        """
        直连目标库，使用独立短连接池 + statement_timeout

        用于 DDL 扫描时直连目标库，配合 statement_timeout 防止慢查询阻塞。

        Args:
            conn_url: 连接 URL，若为 None 则使用当前配置的连接字符串

        Returns:
            配置好的 SQLAlchemy Engine
        """
        if conn_url is None:
            conn_url = self._build_connection_string()

        engine = create_engine(
            conn_url,
            pool_pre_ping=True,
            pool_size=2,          # 独立小池
            max_overflow=0,       # 不溢出
            pool_timeout=10,
        )

        # 设置 statement_timeout = 30s
        try:
            with engine.connect() as conn:
                conn.execute(text("SET statement_timeout = '30s'"))
                conn.commit()
        except Exception as e:
            logger.warning("设置 statement_timeout 失败: %s", e)

        return engine
