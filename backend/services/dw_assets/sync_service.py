"""数仓资产元数据同步服务

实现 Spec §6.1 元数据同步流程、§6.2 热度计算、§10.3 敏感性自动检测。
"""
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.crypto import get_datasource_crypto
from services.datasources.models import DataSource
from services.ddl_checker.connector import DatabaseConnector
from services.dw_assets.models import (
    DwAssetTable,
    DwAssetColumn,
    DwAssetPartition,
    DwAssetSyncRun,
    DwAssetLineageEdge,
)

logger = logging.getLogger(__name__)

# 服务级连接（database_name 为空）时需要跳过的系统库
_SYSTEM_DATABASES = frozenset({
    "information_schema", "sys", "_statistics_", "mysql", "performance_schema",
})

# ─────────────────────────────────────────────────────────────────────────────
# 敏感性检测正则规则 (Spec §10.3)
# ─────────────────────────────────────────────────────────────────────────────

_SENSITIVITY_RULES: List[Tuple[re.Pattern, str]] = [
    # restricted 级别
    (re.compile(r"(id_card|identity|certificate|passport)"), "restricted"),
    (re.compile(r"(password|passwd|pwd|token|secret|api_key|access_key)"), "restricted"),
    # confidential 级别
    (re.compile(r"(^|_)(phone|mobile|tel|telephone)(_|$)"), "confidential"),
    (re.compile(r"(^|_)(email|mail)(_|$)"), "confidential"),
    (re.compile(r"(^|_)(address|addr)(_|$)"), "confidential"),
]

# 需要人工确认的名称规则 — 不自动提升，保持 internal
_NAME_RULES: List[re.Pattern] = [
    re.compile(r"(^|_)(name|real_name|username)(_|$)"),
]


class MetadataSyncService:
    """数仓资产元数据同步服务"""

    # ─────────────────────────────────────────────────────────────────────────
    # 公共入口
    # ─────────────────────────────────────────────────────────────────────────

    def sync_datasource(
        self,
        db: Session,
        datasource_id: int,
        mode: str = "incremental",
        include_partitions: bool = True,
        operator_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        主同步入口：拉取远端数仓元数据并 upsert 到本地。

        Args:
            db: SQLAlchemy Session
            datasource_id: 数据源 ID
            mode: incremental / full
            include_partitions: 是否同步分区 (StarRocks)
            operator_id: 操作人 ID

        Returns:
            sync_run 的 dict 表示
        """
        # 1. 并发检查
        existing_run = (
            db.query(DwAssetSyncRun)
            .filter(
                DwAssetSyncRun.datasource_id == datasource_id,
                DwAssetSyncRun.status == "running",
            )
            .first()
        )
        if existing_run:
            return {
                "error": True,
                "code": "DWASSET_004",
                "message": "该数据源已有同步任务正在运行",
                "sync_run_id": existing_run.id,
            }

        # 2. 查询数据源
        datasource = db.query(DataSource).filter(
            DataSource.id == datasource_id,
            DataSource.is_active == True,  # noqa: E712
        ).first()
        if not datasource:
            return {"error": True, "code": "DWASSET_001", "message": "数据源不存在或已停用"}

        if datasource.db_type not in ("starrocks", "mysql"):
            return {"error": True, "code": "DWASSET_003", "message": "不支持的数据源类型，仅支持 StarRocks/MySQL"}

        # 3. 创建 sync_run 记录
        sync_run = DwAssetSyncRun(
            datasource_id=datasource_id,
            trigger_type="manual" if operator_id else "scheduled",
            status="running",
            operator_id=operator_id,
        )
        db.add(sync_run)
        db.flush()

        connector: Optional[DatabaseConnector] = None
        try:
            # 4. 解密密码并构建连接
            crypto = get_datasource_crypto()
            password = crypto.decrypt(datasource.password_encrypted)

            connector = DatabaseConnector({
                "host": datasource.host,
                "port": datasource.port,
                "user": datasource.username,
                "password": password,
                "database": datasource.database_name,
                "db_type": datasource.db_type,
            })
            if not connector.connect():
                raise ConnectionError("无法连接到目标数据源")

            # 5. 拉取表信息
            tables_info = self._fetch_tables_info(connector, datasource)
            sync_run.tables_found = len(tables_info)

            # 6. Upsert 表和字段
            tables_upserted = 0
            columns_upserted = 0
            partitions_upserted = 0
            synced_table_ids = set()

            for table_info in tables_info:
                table_record = self._upsert_table(db, datasource, table_info)
                synced_table_ids.add(table_record.id)
                tables_upserted += 1

                # 字段同步
                col_count = self._upsert_columns(db, connector, table_record, table_info)
                columns_upserted += col_count

                # 分区同步 (仅 StarRocks)
                if include_partitions and datasource.db_type == "starrocks":
                    part_count = self._upsert_partitions(
                        db, connector, table_record, table_record.database_name
                    )
                    partitions_upserted += part_count

            # 7. 软删除未出现的表
            self._mark_deleted_tables(db, datasource_id, synced_table_ids)

            # 8. 更新 sync_run 为成功
            sync_run.status = "success"
            sync_run.tables_upserted = tables_upserted
            sync_run.columns_upserted = columns_upserted
            sync_run.partitions_upserted = partitions_upserted
            sync_run.finished_at = datetime.utcnow()
            db.commit()

            # 9. 刷新热度 (失败不影响主事务)
            try:
                self.refresh_heat_scores(db, datasource_id)
            except Exception as e:
                logger.warning("热度刷新失败 (datasource_id=%s): %s", datasource_id, str(e))
                sync_run.details_json = {
                    **(sync_run.details_json or {}),
                    "heat_refresh_error": str(e)[:200],
                }
                db.commit()

            return sync_run.to_dict()

        except Exception as e:
            db.rollback()
            # 错误脱敏：不暴露密码或完整连接串
            error_msg = self._sanitize_error(str(e))
            sync_run.status = "failed"
            sync_run.error_message = error_msg
            sync_run.finished_at = datetime.utcnow()
            db.add(sync_run)
            db.commit()
            return sync_run.to_dict()

        finally:
            if connector:
                connector.disconnect()

    # ─────────────────────────────────────────────────────────────────────────
    # 热度计算 (Spec §6.2)
    # ─────────────────────────────────────────────────────────────────────────

    def refresh_heat_scores(self, db: Session, datasource_id: int) -> int:
        """
        刷新指定数据源下所有活跃表的热度分数。

        公式: heat_score = min(100,
            query_count_7d * 0.5 +
            query_count_30d * 0.1 +
            downstream_count * 3 +
            has_recent_partition_bonus
        )

        Returns:
            更新的表数量
        """
        tables = (
            db.query(DwAssetTable)
            .filter(
                DwAssetTable.datasource_id == datasource_id,
                DwAssetTable.is_deleted == False,  # noqa: E712
            )
            .all()
        )

        updated_count = 0
        for table in tables:
            # 计算 downstream_count
            downstream_count = (
                db.query(DwAssetLineageEdge)
                .filter(DwAssetLineageEdge.source_table_id == table.id)
                .count()
            )

            # has_recent_partition_bonus: 有最近 7 天内更新的分区则 +10
            partition_bonus = 0
            if table.last_partition_at:
                days_since = (datetime.utcnow() - table.last_partition_at).days
                if days_since <= 7:
                    partition_bonus = 10

            heat = min(
                100.0,
                table.query_count_7d * 0.5
                + table.query_count_30d * 0.1
                + downstream_count * 3
                + partition_bonus,
            )
            table.heat_score = round(heat, 1)
            updated_count += 1

        db.commit()
        return updated_count

    # ─────────────────────────────────────────────────────────────────────────
    # 工具方法
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_asset_uid(
        datasource_id: int,
        database_name: str,
        schema_name: str,
        table_name: str,
    ) -> str:
        """
        生成四段式资产 UID。

        格式: dw:{datasource_id}:{database_name}:{schema_name}:{table_name}
        """
        return f"dw:{datasource_id}:{database_name}:{schema_name or ''}:{table_name}"

    @staticmethod
    def detect_sensitivity(
        column_name: str,
        business_name: Optional[str] = None,
        column_comment: Optional[str] = None,
    ) -> str:
        """
        根据正则规则自动检测字段敏感级别 (Spec §10.3)。

        对 column_name、business_name、column_comment 分别匹配正则规则。
        任一文本命中即标记对应级别，优先级 restricted > confidential > internal。

        Returns:
            sensitivity_level: public / internal / confidential / restricted
        """
        texts = []
        if column_name:
            texts.append(column_name.lower())
        if business_name:
            texts.append(business_name.lower())
        if column_comment:
            texts.append(column_comment.lower())

        if not texts:
            return "internal"

        # 按优先级从高到低匹配 (restricted 规则排在前面)
        for pattern, level in _SENSITIVITY_RULES:
            for t in texts:
                if pattern.search(t):
                    return level

        return "internal"

    # ─────────────────────────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_tables_info(
        self, connector: DatabaseConnector, datasource: DataSource
    ) -> List[Dict[str, Any]]:
        """从 information_schema 拉取表信息列表。

        当 database_name 为空时（服务级连接），先 SHOW DATABASES 枚举用户库，
        过滤掉系统库后逐库查询。
        """
        engine = connector.engine
        tables_info = []

        if datasource.database_name:
            db_names = [datasource.database_name]
        else:
            with engine.connect() as conn:
                result = conn.execute(text("SHOW DATABASES"))
                db_names = [
                    row[0] for row in result.fetchall()
                    if row[0].lower() not in _SYSTEM_DATABASES
                ]

        sql = text("""
            SELECT
                TABLE_NAME,
                TABLE_TYPE,
                TABLE_COMMENT,
                TABLE_ROWS,
                DATA_LENGTH
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = :db_name
        """)

        with engine.connect() as conn:
            for db_name in db_names:
                result = conn.execute(sql, {"db_name": db_name})
                for row in result.fetchall():
                    tables_info.append({
                        "db_name": db_name,
                        "table_name": row[0],
                        "table_type": row[1] or "BASE TABLE",
                        "table_comment": row[2] or "",
                        "row_count_estimate": row[3],
                        "storage_bytes": row[4],
                    })

        return tables_info

    def _upsert_table(
        self, db: Session, datasource: DataSource, table_info: Dict[str, Any]
    ) -> DwAssetTable:
        """Upsert 单张表记录，保护人工维护字段"""
        table_name = table_info["table_name"]
        db_name = table_info.get("db_name") or datasource.database_name or ""
        asset_uid = self.generate_asset_uid(
            datasource.id, db_name, "", table_name
        )

        existing = (
            db.query(DwAssetTable)
            .filter(DwAssetTable.asset_uid == asset_uid)
            .first()
        )

        if existing:
            # 更新物理元数据字段，保护人工维护字段
            existing.table_type = table_info["table_type"]
            existing.table_comment = table_info.get("table_comment")
            existing.row_count_estimate = table_info.get("row_count_estimate")
            existing.storage_bytes = table_info.get("storage_bytes")
            existing.is_deleted = False
            existing.synced_at = datetime.utcnow()
            existing.raw_metadata_json = table_info
            # 不覆盖: business_name, description, domain, layer, tags_json
            # 仅当 business_name 为空且 comment 有值时，用 comment 回填
            if not existing.business_name and table_info.get("table_comment"):
                existing.business_name = table_info["table_comment"]
            return existing
        else:
            table_comment = table_info.get("table_comment")
            new_table = DwAssetTable(
                asset_uid=asset_uid,
                datasource_id=datasource.id,
                database_name=db_name,
                schema_name="",
                table_name=table_name,
                table_type=table_info["table_type"],
                table_comment=table_comment,
                business_name=table_comment or None,
                row_count_estimate=table_info.get("row_count_estimate"),
                storage_bytes=table_info.get("storage_bytes"),
                raw_metadata_json=table_info,
                synced_at=datetime.utcnow(),
            )
            db.add(new_table)
            db.flush()
            return new_table

    def _upsert_columns(
        self,
        db: Session,
        connector: DatabaseConnector,
        table_record: DwAssetTable,
        table_info: Dict[str, Any],
    ) -> int:
        """Upsert 表的所有字段"""
        engine = connector.engine
        table_name = table_info["table_name"]
        db_name = table_record.database_name

        sql = text("""
            SELECT
                COLUMN_NAME,
                ORDINAL_POSITION,
                COLUMN_TYPE,
                IS_NULLABLE,
                COLUMN_DEFAULT,
                COLUMN_COMMENT,
                COLUMN_KEY
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = :db_name AND TABLE_NAME = :table_name
            ORDER BY ORDINAL_POSITION
        """)

        columns_data = []
        with engine.connect() as conn:
            result = conn.execute(sql, {"db_name": db_name, "table_name": table_name})
            columns_data = result.fetchall()

        count = 0
        for col_row in columns_data:
            col_name = col_row[0]
            ordinal_position = col_row[1]
            data_type = col_row[2]
            is_nullable = col_row[3] == "YES" if col_row[3] else None
            default_value = col_row[4]
            column_comment = col_row[5] or ""
            column_key = col_row[6] or ""

            is_primary_key = "PRI" in column_key.upper() if column_key else False
            normalized_type = self._normalize_type(data_type)

            existing_col = (
                db.query(DwAssetColumn)
                .filter(
                    DwAssetColumn.table_id == table_record.id,
                    DwAssetColumn.column_name == col_name,
                )
                .first()
            )

            if existing_col:
                # 更新物理元数据
                existing_col.ordinal_position = ordinal_position
                existing_col.data_type = data_type
                existing_col.normalized_type = normalized_type
                existing_col.is_nullable = is_nullable
                existing_col.is_primary_key = is_primary_key
                existing_col.default_value = default_value
                existing_col.column_comment = column_comment
                existing_col.raw_metadata_json = {
                    "column_key": column_key,
                    "data_type": data_type,
                }
                # 仅当 business_name 为空且 comment 有值时，用 comment 回填
                if not existing_col.business_name and column_comment:
                    existing_col.business_name = column_comment
                # 仅在字段名或注释变化时重新检测敏感级别
                # 且仅当 sensitivity_level 仍为默认值 internal 时才自动更新
                if existing_col.sensitivity_level == "internal":
                    new_level = self.detect_sensitivity(
                        col_name, existing_col.business_name, column_comment
                    )
                    if new_level != "internal":
                        existing_col.sensitivity_level = new_level
            else:
                # 新字段：自动检测敏感级别
                sensitivity = self.detect_sensitivity(col_name, None, column_comment)
                new_col = DwAssetColumn(
                    table_id=table_record.id,
                    column_name=col_name,
                    ordinal_position=ordinal_position,
                    data_type=data_type,
                    normalized_type=normalized_type,
                    is_nullable=is_nullable,
                    is_primary_key=is_primary_key,
                    default_value=default_value,
                    column_comment=column_comment,
                    business_name=column_comment or None,
                    sensitivity_level=sensitivity,
                    raw_metadata_json={
                        "column_key": column_key,
                        "data_type": data_type,
                    },
                )
                db.add(new_col)

            count += 1

        db.flush()
        return count

    def _upsert_partitions(
        self,
        db: Session,
        connector: DatabaseConnector,
        table_record: DwAssetTable,
        database_name: str,
    ) -> int:
        """Upsert StarRocks 分区信息"""
        partitions = connector.show_partitions(database_name, table_record.table_name)
        if not partitions:
            return 0

        count = 0
        latest_partition_name = None
        latest_partition_at = None

        for part in partitions:
            partition_name = part.get("PartitionName", "") or part.get("partition_name", "")
            if not partition_name:
                continue

            partition_value = part.get("Range", "") or part.get("range", "")
            row_count = part.get("RowCount") or part.get("DataSize")
            storage_bytes_val = None
            visible_version = part.get("VisibleVersion") or part.get("visible_version")

            # 尝试解析数字字段
            try:
                row_count = int(row_count) if row_count else None
            except (ValueError, TypeError):
                row_count = None

            existing_part = (
                db.query(DwAssetPartition)
                .filter(
                    DwAssetPartition.table_id == table_record.id,
                    DwAssetPartition.partition_name == partition_name,
                )
                .first()
            )

            if existing_part:
                existing_part.partition_value = str(partition_value) if partition_value else None
                existing_part.row_count_estimate = row_count
                existing_part.storage_bytes = storage_bytes_val
                existing_part.visible_version = str(visible_version) if visible_version else None
                existing_part.raw_metadata_json = part
            else:
                new_part = DwAssetPartition(
                    table_id=table_record.id,
                    partition_name=partition_name,
                    partition_value=str(partition_value) if partition_value else None,
                    row_count_estimate=row_count,
                    storage_bytes=storage_bytes_val,
                    visible_version=str(visible_version) if visible_version else None,
                    raw_metadata_json=part,
                )
                db.add(new_part)

            latest_partition_name = partition_name
            count += 1

        # 更新表级分区摘要
        if count > 0:
            table_record.partition_count = count
            table_record.last_partition_name = latest_partition_name
            table_record.last_partition_at = datetime.utcnow()

        db.flush()
        return count

    def _mark_deleted_tables(
        self, db: Session, datasource_id: int, synced_table_ids: set
    ) -> None:
        """标记本次同步中未出现的表为 is_deleted=True"""
        if not synced_table_ids:
            return

        all_tables = (
            db.query(DwAssetTable)
            .filter(
                DwAssetTable.datasource_id == datasource_id,
                DwAssetTable.is_deleted == False,  # noqa: E712
            )
            .all()
        )

        for table in all_tables:
            if table.id not in synced_table_ids:
                table.is_deleted = True

    @staticmethod
    def _sanitize_error(error_str: str) -> str:
        """脱敏错误信息：移除密码、连接串等敏感信息"""
        # 移除连接字符串中的密码
        sanitized = re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", error_str)
        # 移除可能的密码参数
        sanitized = re.sub(r"password\s*=\s*['\"][^'\"]*['\"]", "password=***", sanitized, flags=re.IGNORECASE)
        # 截断过长错误
        if len(sanitized) > 500:
            sanitized = sanitized[:500] + "..."
        return sanitized

    @staticmethod
    def _normalize_type(data_type: str) -> str:
        """将数据库原始类型归一化为通用类型"""
        if not data_type:
            return "string"
        dt = data_type.upper()
        if any(t in dt for t in ("INT", "BIGINT", "SMALLINT", "TINYINT", "DECIMAL", "FLOAT", "DOUBLE", "NUMERIC")):
            return "number"
        if any(t in dt for t in ("DATE", "TIME", "DATETIME", "TIMESTAMP")):
            return "date"
        if any(t in dt for t in ("BOOL", "BOOLEAN")):
            return "bool"
        if any(t in dt for t in ("JSON", "JSONB")):
            return "json"
        return "string"
