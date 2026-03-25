"""DDL 生成器核心"""
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path

from .models import TableDefinition, ColumnDefinition, IndexDefinition


class DDLGenerator:
    """DDL 语句生成器"""

    def __init__(self, rules_config_path: Optional[str] = None):
        """
        初始化生成器

        Args:
            rules_config_path: 规则配置文件路径
        """
        self.rules_config_path = rules_config_path
        self.rules: Dict[str, Any] = {}
        if rules_config_path:
            self._load_rules(rules_config_path)

    def _load_rules(self, config_path: str):
        """加载规则配置"""
        with open(config_path, "r", encoding="utf-8") as f:
            self.rules = yaml.safe_load(f)

    def generate_create_table(self, table: TableDefinition, db_type: str = "mysql") -> str:
        """
        生成 CREATE TABLE 语句

        Args:
            table: 表定义对象
            db_type: 数据库类型 (mysql/postgresql)

        Returns:
            CREATE TABLE SQL 语句
        """
        lines = []

        # 表名
        table_name = table.table_name
        lines.append(f"CREATE TABLE `{table_name}` (")

        # 列定义
        column_sqls = []
        for col in table.columns:
            col_sql = self._generate_column_sql(col, db_type)
            if col_sql:
                column_sqls.append(f"  {col_sql}")

        # 索引定义
        for idx in table.indexes:
            idx_sql = idx.to_sql(db_type)
            column_sqls.append(f"  {idx_sql}")

        # 闭合表定义
        lines.append(",\n".join(column_sqls))
        lines.append(")")

        # 表注释
        if table.comment:
            lines.append(f"COMMENT='{table.comment}'")

        # 字符集（MySQL）
        if db_type == "mysql":
            lines.append("ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")

        return "\n".join(lines) + ";"

    def _generate_column_sql(self, column: ColumnDefinition, db_type: str) -> str:
        """生成列的 SQL 定义"""
        parts = []

        # 列名 - 强制小写
        col_name = column.name.lower()
        parts.append(f"`{col_name}`")

        # 数据类型
        data_type = self._normalize_data_type(column, db_type)
        parts.append(data_type)

        # 主键处理
        if column.is_primary_key:
            if db_type == "mysql" and column.is_auto_increment:
                parts.append("NOT NULL AUTO_INCREMENT")
                return " ".join(parts)
            elif not column.nullable:
                parts.append("NOT NULL")
                return " ".join(parts)

        # 非空
        if not column.nullable:
            parts.append("NOT NULL")

        # 默认值
        if column.default:
            parts.append(f"DEFAULT {column.default}")

        # 自增
        if column.is_auto_increment and db_type == "mysql":
            parts.append("AUTO_INCREMENT")

        # 注释
        if column.comment:
            parts.append(f"COMMENT '{column.comment}'")

        return " ".join(parts)

    def _normalize_data_type(self, column: ColumnDefinition, db_type: str) -> str:
        """标准化数据类型"""
        data_type = column.data_type.upper()

        # 如果规则中有推荐类型，检查是否需要转换
        if self.rules:
            config = self.rules.get("data_type", {})
            recommended = [t.upper() for t in config.get("recommended_types", [])]
            deprecated = [t.upper() for t in config.get("deprecated_types", [])]

            # 如果使用了不推荐类型，给出警告
            if data_type in deprecated:
                pass  # 可以记录日志

        # 构建类型字符串
        if data_type in ("DECIMAL", "NUMERIC"):
            if column.length and column.decimal_length:
                return f"{data_type}({column.length},{column.decimal_length})"
            elif column.length:
                return f"{data_type}({column.length})"
            else:
                return f"{data_type}(10,2)"
        elif data_type in ("VARCHAR", "CHAR", "TEXT"):
            if column.length:
                return f"{data_type}({column.length})"
            elif data_type == "TEXT":
                return data_type
            else:
                return f"{data_type}(255)"
        elif data_type == "TINYINT":
            if column.length:
                return f"TINYINT({column.length})"
            return "TINYINT(1)"
        elif data_type == "INT":
            return "INT"
        elif data_type == "BIGINT":
            return "BIGINT"
        elif data_type in ("DATETIME", "DATE", "TIME", "TIMESTAMP"):
            return data_type
        elif data_type == "BOOLEAN":
            return "TINYINT(1)" if db_type == "mysql" else "SMALLINT"
        else:
            return data_type

    def validate_table_name(self, table_name: str) -> tuple:
        """
        验证表名是否符合规范

        Returns:
            (is_valid, message)
        """
        if not table_name:
            return False, "表名不能为空"

        # 长度检查
        max_length = self.rules.get("table_naming", {}).get("max_length", 64)
        if len(table_name) > max_length:
            return False, f"表名长度不能超过 {max_length} 字符"

        # 命名模式检查
        import re
        pattern = self.rules.get("table_naming", {}).get("pattern", r"^[a-z][a-z0-9_]*$")
        if not re.match(pattern, table_name):
            return False, "表名必须以小写字母开头，支持小写字母、数字、下划线"

        return True, "表名符合规范"

    def validate_column_name(self, column_name: str) -> tuple:
        """
        验证列名是否符合规范

        Returns:
            (is_valid, message)
        """
        if not column_name:
            return False, "列名不能为空"

        # 长度检查
        max_length = self.rules.get("column_naming", {}).get("max_length", 64)
        if len(column_name) > max_length:
            return False, f"列名长度不能超过 {max_length} 字符"

        # 命名模式检查
        import re
        pattern = self.rules.get("column_naming", {}).get("pattern", r"^[a-z][a-z0-9_]*$")
        if not re.match(pattern, column_name):
            return False, "列名必须以小写字母开头，支持小写字母、数字、下划线"

        return True, "列名符合规范"

    def generate_alter_table_add_column(self, table_name: str, column: ColumnDefinition, db_type: str = "mysql") -> str:
        """生成 ALTER TABLE ADD COLUMN 语句"""
        col_sql = self._generate_column_sql(column, db_type)
        return f"ALTER TABLE `{table_name}` ADD COLUMN {col_sql};"

    def generate_drop_table(self, table_name: str, db_type: str = "mysql") -> str:
        """生成 DROP TABLE 语句"""
        if db_type == "mysql":
            return f"DROP TABLE IF EXISTS `{table_name}`;"
        else:
            return f"DROP TABLE IF EXISTS {table_name};"

    def generate_rename_table(self, old_name: str, new_name: str, db_type: str = "mysql") -> str:
        """生成重命名表语句"""
        if db_type == "mysql":
            return f"ALTER TABLE `{old_name}` RENAME TO `{new_name}`;"
        else:
            return f"ALTER TABLE {old_name} RENAME TO {new_name};"
