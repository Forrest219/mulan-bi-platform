"""数仓资产数据预览服务

实现 Spec §5.11 数据预览功能：安全的采样查询。
"""
import logging
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.crypto import get_datasource_crypto
from services.datasources.models import DataSource
from services.dw_assets.models import DwAssetTable, DwAssetColumn

logger = logging.getLogger(__name__)


class PreviewService:
    """数仓资产数据预览服务"""

    # analyst 可查看的最大行数
    ANALYST_MAX_LIMIT = 20
    # data_admin/admin 可查看的最大行数
    ADMIN_MAX_LIMIT = 100
    # 查询超时 (秒)
    STATEMENT_TIMEOUT_SECONDS = 5
    # 连接池大小
    POOL_SIZE = 2

    def preview_table(
        self,
        db: Session,
        table_id: int,
        user_role: str,
        limit: Optional[int] = None,
        columns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        安全的数据预览查询。

        Args:
            db: SQLAlchemy Session (本地 PostgreSQL)
            table_id: 表 ID
            user_role: 用户角色 (admin / data_admin / analyst)
            limit: 查询行数限制
            columns: 指定查询字段列表

        Returns:
            包含 columns, rows, masked_columns 的 dict
        """
        # 1. 查询本地资产元数据
        table_record = (
            db.query(DwAssetTable)
            .filter(
                DwAssetTable.id == table_id,
                DwAssetTable.is_deleted == False,  # noqa: E712
            )
            .first()
        )
        if not table_record:
            return {"error": True, "code": "DWASSET_001", "message": "数仓资产不存在"}

        # 2. 查询数据源
        datasource = db.query(DataSource).filter(
            DataSource.id == table_record.datasource_id,
            DataSource.is_active == True,  # noqa: E712
        ).first()
        if not datasource:
            return {"error": True, "code": "DWASSET_001", "message": "关联数据源不存在或已停用"}

        # 3. 确定行数限制
        max_limit = self.ADMIN_MAX_LIMIT if user_role in ("admin", "data_admin") else self.ANALYST_MAX_LIMIT
        if limit is None or limit <= 0:
            limit = min(20, max_limit)
        else:
            limit = min(limit, max_limit)

        # 4. 获取本地字段白名单
        all_columns = (
            db.query(DwAssetColumn)
            .filter(DwAssetColumn.table_id == table_id)
            .order_by(DwAssetColumn.ordinal_position)
            .all()
        )
        if not all_columns:
            return {"error": True, "code": "DWASSET_006", "message": "该表无同步字段元数据"}

        # 5. 构建安全字段列表
        selected_columns, masked_columns = self._resolve_columns(
            all_columns, columns, user_role
        )

        if not selected_columns:
            return {"error": True, "code": "DWASSET_006", "message": "无可预览字段（所有字段均为受限级别）"}

        # 6. 验证指定字段是否在白名单中
        if columns:
            whitelist = {col.column_name for col in all_columns}
            invalid = [c for c in columns if c not in whitelist]
            if invalid:
                return {
                    "error": True,
                    "code": "DWASSET_006",
                    "message": f"非法字段选择：{', '.join(invalid[:5])}",
                }

        # 7. 构建安全 SQL
        safe_sql = self._build_preview_sql(
            table_record.database_name,
            table_record.table_name,
            selected_columns,
            limit,
            datasource.db_type,
        )

        # 8. 使用独立短生命周期引擎查询
        engine = None
        try:
            engine = self._create_preview_engine(datasource)
            rows = self._execute_preview(engine, safe_sql, datasource.db_type)

            return {
                "columns": [
                    {"name": col.column_name, "data_type": col.data_type}
                    for col in selected_columns
                ],
                "rows": rows,
                "limit": limit,
                "truncated": len(rows) >= limit,
                "masked_columns": masked_columns,
            }

        except Exception as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "cancel" in error_msg.lower():
                return {"error": True, "code": "DWASSET_007", "message": "数据预览超时，请稍后重试"}
            logger.warning("数据预览失败 (table_id=%s): %s", table_id, error_msg[:200])
            return {"error": True, "code": "DWASSET_007", "message": "数据预览查询失败"}

        finally:
            if engine:
                engine.dispose()

    # ─────────────────────────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────────────────────────

    def _resolve_columns(
        self,
        all_columns: List[DwAssetColumn],
        requested_columns: Optional[List[str]],
        user_role: str,
    ) -> tuple:
        """
        解析要查询的字段列表，过滤受限字段。

        Returns:
            (selected_columns: List[DwAssetColumn], masked_columns: List[str])
        """
        masked_columns = []

        # 对 analyst 隐藏 confidential 和 restricted 字段
        # 对 data_admin/admin 隐藏 restricted
        if user_role == "analyst":
            hidden_levels = {"confidential", "restricted"}
        else:
            hidden_levels = {"restricted"}

        # 过滤后的可用字段
        available = []
        for col in all_columns:
            if col.sensitivity_level in hidden_levels:
                masked_columns.append(col.column_name)
            else:
                available.append(col)

        # 如果用户指定了字段列表，则从可用字段中筛选
        if requested_columns:
            requested_set = set(requested_columns)
            selected = [col for col in available if col.column_name in requested_set]
        else:
            # 默认取前 20 个可用字段
            selected = available[:20]

        return selected, masked_columns

    def _build_preview_sql(
        self,
        database_name: str,
        table_name: str,
        columns: List[DwAssetColumn],
        limit: int,
        db_type: str,
    ) -> str:
        """
        构建安全的 SELECT 语句。

        所有标识符做反引号转义，LIMIT 使用整数直接量。
        """
        # 标识符安全引用
        quoted_cols = ", ".join(
            f"`{col.column_name.replace('`', '``')}`" for col in columns
        )
        quoted_db = f"`{database_name.replace('`', '``')}`"
        quoted_table = f"`{table_name.replace('`', '``')}`"

        # LIMIT 为整数白名单值，安全
        return f"SELECT {quoted_cols} FROM {quoted_db}.{quoted_table} LIMIT {int(limit)}"

    def _create_preview_engine(self, datasource: DataSource):
        """创建独立短生命周期引擎，设置 statement_timeout"""
        crypto = get_datasource_crypto()
        password = crypto.decrypt(datasource.password_encrypted)

        user = quote_plus(datasource.username)
        pwd = quote_plus(password)
        host = datasource.host
        port = datasource.port
        database = datasource.database_name

        if datasource.db_type in ("mysql", "starrocks"):
            # StarRocks 使用 mysql 协议
            url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{database}"
            connect_args = {
                "connect_timeout": 10,
                "read_timeout": self.STATEMENT_TIMEOUT_SECONDS,
                "write_timeout": self.STATEMENT_TIMEOUT_SECONDS,
            }
        else:
            url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{database}"
            connect_args = {"connect_timeout": 10}

        engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=self.POOL_SIZE,
            max_overflow=0,
            pool_timeout=10,
            connect_args=connect_args,
        )

        return engine

    def _execute_preview(
        self, engine, sql: str, db_type: str
    ) -> List[Dict[str, Any]]:
        """执行预览查询并返回行数据"""
        rows = []
        with engine.connect() as conn:
            # 设置 session 超时
            if db_type in ("mysql", "starrocks"):
                conn.execute(text(
                    f"SET SESSION MAX_EXECUTION_TIME = {self.STATEMENT_TIMEOUT_SECONDS * 1000}"
                ))

            result = conn.execute(text(sql))
            col_names = list(result.keys())
            for row in result.fetchall():
                row_dict = {}
                for i, col_name in enumerate(col_names):
                    val = row[i]
                    # 序列化为 JSON-safe 值
                    if val is None:
                        row_dict[col_name] = None
                    elif isinstance(val, (int, float, bool)):
                        row_dict[col_name] = val
                    else:
                        row_dict[col_name] = str(val)
                rows.append(row_dict)

        return rows
