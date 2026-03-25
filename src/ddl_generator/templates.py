"""DDL 生成模板 - 常用表结构模板"""
from typing import List, Dict, Any
from .models import TableDefinition, ColumnDefinition, IndexDefinition
from .generator import DDLGenerator


class TableTemplate:
    """表结构模板"""

    @staticmethod
    def dim_table(table_name: str, business_keys: List[str], attributes: List[Dict[str, Any]]) -> TableDefinition:
        """
        创建维度表模板

        Args:
            table_name: 表名（建议以 dim_ 开头）
            business_keys: 业务主键字段列表
            attributes: 属性字段列表，每项包含 name, data_type, length, comment

        Returns:
            TableDefinition 对象
        """
        table = TableDefinition(
            table_name=table_name,
            comment=f"维度表：{table_name}"
        )

        # 添加主键
        if business_keys:
            table.add_column(ColumnDefinition(
                name="id",
                data_type="BIGINT",
                nullable=False,
                is_auto_increment=True,
                is_primary_key=True,
                comment="代理键"
            ))
            table.add_index(IndexDefinition(
                name=f"uk_{table_name}",
                columns=business_keys,
                is_unique=True,
                comment="业务主键唯一索引"
            ))

        # 添加业务主键
        for key in business_keys:
            col = next((a for a in attributes if a["name"] == key), None)
            if col:
                table.add_column(ColumnDefinition(
                    name=key,
                    data_type=col.get("data_type", "VARCHAR"),
                    length=col.get("length", 64),
                    nullable=False,
                    comment=col.get("comment", key)
                ))

        # 添加属性字段
        for attr in attributes:
            if attr["name"] not in business_keys:
                table.add_column(ColumnDefinition(
                    name=attr["name"],
                    data_type=attr.get("data_type", "VARCHAR"),
                    length=attr.get("length", 255),
                    nullable=True,
                    comment=attr.get("comment", attr["name"])
                ))

        # 添加审计字段
        table.auto_add_timestamps()
        table.auto_add_soft_delete()

        return table

    @staticmethod
    def fact_table(table_name: str, facts: List[Dict[str, Any]], dimension_keys: List[str]) -> TableDefinition:
        """
        创建事实表模板

        Args:
            table_name: 表名（建议以 fact_ 开头）
            facts: 事实字段列表
            dimension_keys: 维度外键字段列表

        Returns:
            TableDefinition 对象
        """
        table = TableDefinition(
            table_name=table_name,
            comment=f"事实表：{table_name}"
        )

        # 添加主键
        table.add_column(ColumnDefinition(
            name="id",
            data_type="BIGINT",
            nullable=False,
            is_auto_increment=True,
            is_primary_key=True,
            comment="主键"
        ))

        # 添加维度外键
        for key in dimension_keys:
            table.add_column(ColumnDefinition(
                name=key,
                data_type="BIGINT",
                nullable=False,
                comment=f"维度外键：{key}"
            ))

        # 添加事实字段
        for fact in facts:
            table.add_column(ColumnDefinition(
                name=fact["name"],
                data_type=fact.get("data_type", "DECIMAL"),
                length=fact.get("length", 18),
                decimal_length=fact.get("decimal_length", 4),
                nullable=True,
                comment=fact.get("comment", fact["name"])
            ))

        # 添加审计字段
        table.auto_add_timestamps()
        table.auto_add_soft_delete()

        return table

    @staticmethod
    def ods_table(table_name: str, source_columns: List[Dict[str, Any]]) -> TableDefinition:
        """
        创建 ODS 层表模板

        Args:
            table_name: 表名（建议以 ods_ 开头）
            source_columns: 源表字段列表

        Returns:
            TableDefinition 对象
        """
        table = TableDefinition(
            table_name=table_name,
            comment=f"ODS 层表：{table_name}"
        )

        # 添加主键
        table.add_column(ColumnDefinition(
            name="id",
            data_type="BIGINT",
            nullable=False,
            is_auto_increment=True,
            is_primary_key=True,
            comment="主键"
        ))

        # 添加数据仓库审计字段
        table.add_column(ColumnDefinition(
            name="etl_time",
            data_type="DATETIME",
            nullable=False,
            default="CURRENT_TIMESTAMP",
            comment="ETL 加载时间"
        ))

        table.add_column(ColumnDefinition(
            name="source_table",
            data_type="VARCHAR",
            length=64,
            nullable=True,
            comment="源表名"
        ))

        table.add_column(ColumnDefinition(
            name="source_id",
            data_type="VARCHAR",
            length=64,
            nullable=True,
            comment="源数据主键"
        ))

        # 添加源表字段
        for col in source_columns:
            table.add_column(ColumnDefinition(
                name=col["name"],
                data_type=col.get("data_type", "VARCHAR"),
                length=col.get("length", 255),
                nullable=True,
                comment=col.get("comment", col["name"])
            ))

        # 添加软删除
        table.auto_add_soft_delete()

        return table

    @staticmethod
    def dwd_table(table_name: str, business_keys: List[str], attributes: List[Dict[str, Any]], dimension_refs: List[str] = None) -> TableDefinition:
        """
        创建 DWD 层表模板

        Args:
            table_name: 表名（建议以 dwd_ 开头）
            business_keys: 业务主键
            attributes: 属性字段
            dimension_refs: 关联的维度表外键

        Returns:
            TableDefinition 对象
        """
        table = TableDefinition(
            table_name=table_name,
            comment=f"DWD 层表：{table_name}"
        )

        # 添加主键
        table.add_column(ColumnDefinition(
            name="id",
            data_type="BIGINT",
            nullable=False,
            is_auto_increment=True,
            is_primary_key=True,
            comment="代理键"
        ))

        # 添加业务主键
        for key in business_keys:
            col = next((a for a in attributes if a["name"] == key), None)
            table.add_column(ColumnDefinition(
                name=key,
                data_type=col.get("data_type", "VARCHAR") if col else "VARCHAR",
                length=col.get("length", 64) if col else 64,
                nullable=False,
                comment=col.get("comment", key) if col else key
            ))

        # 添加维度外键
        for dim_key in (dimension_refs or []):
            table.add_column(ColumnDefinition(
                name=dim_key,
                data_type="BIGINT",
                nullable=False,
                comment=f"关联维度表外键：{dim_key}"
            ))

        # 添加属性字段
        for attr in attributes:
            if attr["name"] not in business_keys:
                table.add_column(ColumnDefinition(
                    name=attr["name"],
                    data_type=attr.get("data_type", "VARCHAR"),
                    length=attr.get("length", 255),
                    nullable=True,
                    comment=attr.get("comment", attr["name"])
                ))

        # 添加审计字段
        table.auto_add_timestamps()
        table.auto_add_soft_delete()

        return table


class DDLTemplateGenerator:
    """DDL 模板生成器"""

    def __init__(self, rules_config_path: str = None):
        self.generator = DDLGenerator(rules_config_path)
        self.template = TableTemplate()

    def create_dim_table(self, table_name: str, business_keys: List[str], attributes: List[Dict[str, Any]]) -> str:
        """创建维度表 DDL"""
        table = self.template.dim_table(table_name, business_keys, attributes)
        return self.generator.generate_create_table(table)

    def create_fact_table(self, table_name: str, facts: List[Dict[str, Any]], dimension_keys: List[str]) -> str:
        """创建事实表 DDL"""
        table = self.template.fact_table(table_name, facts, dimension_keys)
        return self.generator.generate_create_table(table)

    def create_ods_table(self, table_name: str, source_columns: List[Dict[str, Any]]) -> str:
        """创建 ODS 层表 DDL"""
        table = self.template.ods_table(table_name, source_columns)
        return self.generator.generate_create_table(table)

    def create_dwd_table(self, table_name: str, business_keys: List[str], attributes: List[Dict[str, Any]], dimension_refs: List[str] = None) -> str:
        """创建 DWD 层表 DDL"""
        table = self.template.dwd_table(table_name, business_keys, attributes, dimension_refs)
        return self.generator.generate_create_table(table)
