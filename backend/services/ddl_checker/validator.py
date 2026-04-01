"""DDL 规范验证模块"""
import re
import yaml
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from .parser import TableInfo, ColumnInfo


class ViolationLevel(Enum):
    """违规级别"""
    ERROR = "error"      # 严重违规
    WARNING = "warning"  # 警告
    INFO = "info"        # 提示


@dataclass
class Violation:
    """违规项"""
    level: ViolationLevel
    rule_name: str
    message: str
    table_name: str = ""
    column_name: str = ""
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "rule_name": self.rule_name,
            "message": self.message,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "suggestion": self.suggestion,
        }


class RulesConfig:
    """规则配置"""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(section, {}).get(key, default)

    def is_enabled(self, section: str) -> bool:
        """检查规则是否启用"""
        return self.config.get(section, {}).get("enabled", True)


class TableValidator:
    """表级验证器"""

    def __init__(self, rules: RulesConfig):
        self.rules = rules

    def validate(self, table: TableInfo) -> List[Violation]:
        """验证表"""
        violations = []

        violations.extend(self._check_naming(table))
        violations.extend(self._check_comment(table))
        violations.extend(self._check_primary_key(table))
        violations.extend(self._check_timestamp_fields(table))
        violations.extend(self._check_soft_delete(table))
        violations.extend(self._check_indexes(table))

        return violations

    def _check_naming(self, table: TableInfo) -> List[Violation]:
        """检查表命名规范"""
        violations = []
        if not self.rules.is_enabled("table_naming"):
            return violations

        config = self.rules.config.get("table_naming", {})
        pattern = config.get("pattern", r"^[a-z][a-z0-9_]*$")
        max_length = config.get("max_length", 64)
        prefix_whitelist = config.get("prefix_whitelist", [])

        table_name = table.name

        # 检查长度
        if len(table_name) > max_length:
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="table_naming",
                message=f"表名 '{table_name}' 长度超过 {max_length} 字符",
                table_name=table_name,
                suggestion=f"将表名控制在 {max_length} 字符以内"
            ))

        # 检查命名模式
        if not re.match(pattern, table_name):
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="table_naming",
                message=f"表名 '{table_name}' 不符合命名规范",
                table_name=table_name,
                suggestion=f"表名必须以小写字母开头，支持小写字母、数字、下划线"
            ))

        # 检查前缀
        if prefix_whitelist and not any(table_name.startswith(p) for p in prefix_whitelist):
            violations.append(Violation(
                level=ViolationLevel.WARNING,
                rule_name="table_naming",
                message=f"表名 '{table_name}' 不使用标准前缀",
                table_name=table_name,
                suggestion=f"建议使用以下前缀之一: {', '.join(prefix_whitelist)}"
            ))

        return violations

    def _check_comment(self, table: TableInfo) -> List[Violation]:
        """检查表注释"""
        violations = []
        if not self.rules.is_enabled("comment"):
            return violations

        config = self.rules.config.get("comment", {})
        if config.get("require_table_comment", True) and not table.comment:
            violations.append(Violation(
                level=ViolationLevel.WARNING,
                rule_name="table_comment",
                message=f"表 '{table.name}' 缺少注释",
                table_name=table.name,
                suggestion="为表添加注释说明其用途"
            ))

        return violations

    def _check_primary_key(self, table: TableInfo) -> List[Violation]:
        """检查主键"""
        violations = []
        if not self.rules.is_enabled("primary_key"):
            return violations

        config = self.rules.config.get("primary_key", {})
        pk_columns = table.get_primary_key_columns()

        if config.get("require_primary_key", True) and not pk_columns:
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="primary_key",
                message=f"表 '{table.name}' 缺少主键",
                table_name=table.name,
                suggestion="为表添加主键，建议使用 id 字段"
            ))

        return violations

    def _check_timestamp_fields(self, table: TableInfo) -> List[Violation]:
        """检查时间戳字段"""
        violations = []
        if not self.rules.is_enabled("timestamp"):
            return violations

        config = self.rules.config.get("timestamp", {})
        column_names = table.get_column_names()

        if config.get("require_create_time", True):
            if "create_time" not in column_names:
                violations.append(Violation(
                    level=ViolationLevel.WARNING,
                    rule_name="create_time",
                    message=f"表 '{table.name}' 缺少 create_time 字段",
                    table_name=table.name,
                    suggestion="添加 create_time DATETIME 字段记录创建时间"
                ))

        if config.get("require_update_time", True):
            if "update_time" not in column_names:
                violations.append(Violation(
                    level=ViolationLevel.WARNING,
                    rule_name="update_time",
                    message=f"表 '{table.name}' 缺少 update_time 字段",
                    table_name=table.name,
                    suggestion="添加 update_time DATETIME 字段记录更新时间"
                ))

        return violations

    def _check_soft_delete(self, table: TableInfo) -> List[Violation]:
        """检查软删除字段"""
        violations = []
        if not self.rules.is_enabled("soft_delete"):
            return violations

        config = self.rules.config.get("soft_delete", {})
        column_names = table.get_column_names()

        if config.get("require_is_deleted", True):
            if "is_deleted" not in column_names:
                violations.append(Violation(
                    level=ViolationLevel.WARNING,
                    rule_name="soft_delete",
                    message=f"表 '{table.name}' 缺少 is_deleted 字段",
                    table_name=table.name,
                    suggestion="添加 is_deleted TINYINT 字段支持软删除"
                ))

        return violations

    def _check_indexes(self, table: TableInfo) -> List[Violation]:
        """检查索引"""
        violations = []
        if not self.rules.is_enabled("index"):
            return violations

        config = self.rules.config.get("index", {})
        max_count = config.get("max_index_count_per_table", 10)

        if len(table.indexes) > max_count:
            violations.append(Violation(
                level=ViolationLevel.WARNING,
                rule_name="index_count",
                message=f"表 '{table.name}' 索引数量 ({len(table.indexes)}) 超过限制 ({max_count})",
                table_name=table.name,
                suggestion=f"减少索引数量，保留必要的索引"
            ))

        return violations


class ColumnValidator:
    """列级验证器"""

    def __init__(self, rules: RulesConfig):
        self.rules = rules

    def validate(self, table: TableInfo) -> List[Violation]:
        """验证表的所有列"""
        violations = []

        for column in table.columns:
            violations.extend(self._validate_column(table, column))

        return violations

    def _validate_column(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """验证单个列"""
        violations = []

        violations.extend(self._check_naming(table, column))
        violations.extend(self._check_data_type(table, column))
        violations.extend(self._check_comment(table, column))

        return violations

    def _check_naming(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """检查列命名"""
        violations = []
        if not self.rules.is_enabled("column_naming"):
            return violations

        config = self.rules.config.get("column_naming", {})
        pattern = config.get("pattern", r"^[a-z][a-z0-9_]*$")
        max_length = config.get("max_length", 64)
        reserved_words = config.get("reserved_words", [])

        col_name = column.name
        if col_name is None:
            col_name = ""

        # 检查长度
        if len(col_name) > max_length:
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="column_naming",
                message=f"列名 '{col_name}' 长度超过 {max_length} 字符",
                table_name=table.name,
                column_name=col_name,
                suggestion=f"将列名控制在 {max_length} 字符以内"
            ))

        # 检查命名模式
        if not re.match(pattern, col_name):
            violations.append(Violation(
                level=ViolationLevel.ERROR,
                rule_name="column_naming",
                message=f"列名 '{col_name}' 不符合命名规范",
                table_name=table.name,
                column_name=col_name,
                suggestion="列名必须以小写字母开头，支持小写字母、数字、下划线"
            ))

        # 检查保留字
        if col_name.lower() in [w.lower() for w in reserved_words]:
            violations.append(Violation(
                level=ViolationLevel.INFO,
                rule_name="column_naming",
                message=f"列名 '{col_name}' 是保留字",
                table_name=table.name,
                column_name=col_name,
                suggestion="考虑使用更明确的列名"
            ))

        return violations

    def _check_data_type(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """检查数据类型"""
        violations = []
        if not self.rules.is_enabled("data_type"):
            return violations

        config = self.rules.config.get("data_type", {})
        deprecated_types = config.get("deprecated_types", [])
        recommended_types = config.get("recommended_types", [])

        # 防御性检查：确保 data_type 不为 None
        if column.data_type is None:
            return violations

        # 检查是否是不推荐类型
        for dep_type in deprecated_types:
            if column.data_type.upper() == dep_type.upper():
                violations.append(Violation(
                    level=ViolationLevel.WARNING,
                    rule_name="data_type",
                    message=f"列 '{column.name}' 使用不推荐的数据类型 {column.data_type}",
                    table_name=table.name,
                    column_name=column.name,
                    suggestion=f"建议使用 {', '.join(recommended_types)} 之一"
                ))

        return violations

    def _check_comment(self, table: TableInfo, column: ColumnInfo) -> List[Violation]:
        """检查列注释"""
        violations = []
        if not self.rules.is_enabled("comment"):
            return violations

        config = self.rules.config.get("comment", {})
        if config.get("require_column_comment", True) and not column.comment:
            violations.append(Violation(
                level=ViolationLevel.WARNING,
                rule_name="column_comment",
                message=f"列 '{column.name}' 缺少注释",
                table_name=table.name,
                column_name=column.name,
                suggestion="为列添加注释说明其含义"
            ))

        return violations


class DDLValidator:
    """DDL 验证器 - 整合表级和列级验证"""

    def __init__(self, rules_config: str):
        """
        初始化验证器

        Args:
            rules_config: 规则配置文件路径
        """
        self.rules = RulesConfig(rules_config)
        self.table_validator = TableValidator(self.rules)
        self.column_validator = ColumnValidator(self.rules)

    def validate_table(self, table: TableInfo) -> List[Violation]:
        """验证单个表"""
        violations = []
        violations.extend(self.table_validator.validate(table))
        violations.extend(self.column_validator.validate(table))
        return violations

    def validate_tables(self, tables: List[TableInfo]) -> Dict[str, List[Violation]]:
        """验证多个表"""
        results = {}
        for table in tables:
            results[table.name] = self.validate_table(table)
        return results
