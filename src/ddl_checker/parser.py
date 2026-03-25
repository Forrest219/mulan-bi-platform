"""DDL 解析模块"""
import re
from typing import List, Dict, Any, Optional


class ColumnInfo:
    """列信息"""

    def __init__(
        self,
        name: str,
        data_type: str,
        nullable: bool = True,
        default: Optional[str] = None,
        comment: str = "",
        is_primary_key: bool = False,
        is_foreign_key: bool = False,
    ):
        self.name = name
        self.data_type = data_type.upper()
        self.nullable = nullable
        self.default = default
        self.comment = comment
        self.is_primary_key = is_primary_key
        self.is_foreign_key = is_foreign_key

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "default": self.default,
            "comment": self.comment,
            "is_primary_key": self.is_primary_key,
            "is_foreign_key": self.is_foreign_key,
        }


class IndexInfo:
    """索引信息"""

    def __init__(
        self,
        name: str,
        columns: List[str],
        is_unique: bool = False,
        is_primary: bool = False,
    ):
        self.name = name
        self.columns = columns
        self.is_unique = is_unique
        self.is_primary = is_primary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "columns": self.columns,
            "is_unique": self.is_unique,
            "is_primary": self.is_primary,
        }


class TableInfo:
    """表信息"""

    def __init__(
        self,
        name: str,
        columns: List[ColumnInfo],
        indexes: List[IndexInfo] = None,
        comment: str = "",
        database: str = "",
    ):
        self.name = name
        self.columns = columns
        self.indexes = indexes or []
        self.comment = comment
        self.database = database

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "columns": [col.to_dict() for col in self.columns],
            "indexes": [idx.to_dict() for idx in self.indexes],
            "comment": self.comment,
            "database": self.database,
        }

    def get_column_names(self) -> List[str]:
        """获取所有列名"""
        return [col.name for col in self.columns]

    def get_primary_key_columns(self) -> List[str]:
        """获取主键列名"""
        return [col.name for col in self.columns if col.is_primary_key]


class DDLParser:
    """DDL 解析器 - 解析 SQL 语句提取表结构"""

    @staticmethod
    def parse_create_table(sql: str) -> Optional[TableInfo]:
        """
        解析 CREATE TABLE 语句

        Args:
            sql: CREATE TABLE 语句

        Returns:
            TableInfo 对象，解析失败返回 None
        """
        sql = sql.strip()

        # 提取表名
        table_name = DDLParser._extract_table_name(sql)
        if not table_name:
            return None

        # 提取列定义
        columns = DDLParser._extract_columns(sql)

        # 提取索引定义
        indexes = DDLParser._extract_indexes(sql, table_name)

        return TableInfo(name=table_name, columns=columns, indexes=indexes)

    @staticmethod
    def _extract_table_name(sql: str) -> Optional[str]:
        """提取表名"""
        # 匹配 CREATE TABLE `table_name` 或 CREATE TABLE table_name
        pattern = r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?"
        match = re.search(pattern, sql, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_columns(sql: str) -> List[ColumnInfo]:
        """提取列定义"""
        columns = []

        # 移除表名和首尾括号
        sql_body = re.sub(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?\w+[`\"']?\s*\([^)]*\).*",
                          "", sql, flags=re.IGNORECASE | re.DOTALL)

        # 提取列定义部分
        paren_depth = 0
        col_start = -1
        in_columns = False

        for i, char in enumerate(sql):
            if char == "(":
                if paren_depth == 0:
                    col_start = i + 1
                    in_columns = True
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
                if paren_depth == 0 and in_columns:
                    column_section = sql[col_start:i]
                    break

        # 解析每一行列定义
        lines = DDLParser._split_sql_lines(column_section)
        for line in lines:
            line = line.strip().rstrip(",")
            if not line:
                continue

            # 跳过索引、主键、外键定义
            if re.match(r"(INDEX|KEY|PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CONSTRAINT)", line, re.IGNORECASE):
                continue

            column = DDLParser._parse_column_definition(line)
            if column:
                columns.append(column)

        return columns

    @staticmethod
    def _parse_column_definition(line: str) -> Optional[ColumnInfo]:
        """解析单行列定义"""
        # 匹配列名、数据类型、可选值等
        pattern = r"^[`\"']?(\w+)[`\"']?\s+(\w+(?:\([^)]+\))?)"
        match = re.match(pattern, line, re.IGNORECASE)
        if not match:
            return None

        name = match.group(1)
        data_type = match.group(2)

        # 检查是否为主键
        is_primary_key = bool(re.search(r"PRIMARY\s+KEY", line, re.IGNORECASE))

        # 检查是否为空
        nullable = "NOT NULL" not in line.upper()

        # 提取默认值
        default = None
        default_match = re.search(r"DEFAULT\s+([^\s,]+)", line, re.IGNORECASE)
        if default_match:
            default = default_match.group(1)

        # 提取注释
        comment = ""
        comment_match = re.search(r"COMMENT\s+['\"]([^'\"]*)['\"]", line, re.IGNORECASE)
        if comment_match:
            comment = comment_match.group(1)

        return ColumnInfo(
            name=name,
            data_type=data_type,
            nullable=nullable,
            default=default,
            comment=comment,
            is_primary_key=is_primary_key,
        )

    @staticmethod
    def _extract_indexes(sql: str, table_name: str) -> List[IndexInfo]:
        """提取索引定义"""
        indexes = []

        # 提取主键
        pk_pattern = r"PRIMARY\s+KEY\s*\(([^)]+)\)"
        pk_match = re.search(pk_pattern, sql, re.IGNORECASE)
        if pk_match:
            pk_columns = [col.strip().strip("`'\"") for col in pk_match.group(1).split(",")]
            indexes.append(IndexInfo(
                name=f"pk_{table_name}",
                columns=pk_columns,
                is_unique=True,
                is_primary=True
            ))

        # 提取索引
        index_patterns = [
            (r"(?:INDEX|KEY)\s+[`\"']?(\w+)[`\"']?\s*\(([^)]+)\)", False),
            (r"UNIQUE\s+(?:INDEX|KEY)\s+[`\"']?(\w+)[`\"']?\s*\(([^)]+)\)", True),
        ]

        for pattern, is_unique in index_patterns:
            for match in re.finditer(pattern, sql, re.IGNORECASE):
                index_name = match.group(1)
                index_columns = [col.strip().strip("`'\"") for col in match.group(2).split(",")]
                indexes.append(IndexInfo(
                    name=index_name,
                    columns=index_columns,
                    is_unique=is_unique
                ))

        return indexes

    @staticmethod
    def _split_sql_lines(sql: str) -> List[str]:
        """分割 SQL 语句为行"""
        lines = []
        current_line = ""
        paren_depth = 0

        for char in sql:
            if char == "(":
                paren_depth += 1
                current_line += char
            elif char == ")":
                paren_depth -= 1
                current_line += char
            elif char == "," and paren_depth == 0:
                lines.append(current_line)
                current_line = ""
            else:
                current_line += char

        if current_line.strip():
            lines.append(current_line)

        return lines
