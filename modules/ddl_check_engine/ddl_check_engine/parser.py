"""DDL 解析器"""
import re
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class ColumnInfo:
    """列信息"""
    name: str
    data_type: str
    nullable: bool = True
    default: Optional[str] = None
    comment: Optional[str] = None
    is_primary_key: bool = False


@dataclass
class TableInfo:
    """表信息"""
    name: str
    columns: List[ColumnInfo]
    comment: Optional[str] = None


class DDLParser:
    """DDL 解析器"""

    @staticmethod
    def parse(sql: str) -> Optional[TableInfo]:
        """
        解析 CREATE TABLE 语句

        Args:
            sql: CREATE TABLE SQL 语句

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

        # 提取表注释
        comment = DDLParser._extract_table_comment(sql)

        return TableInfo(name=table_name, columns=columns, comment=comment)

    @staticmethod
    def _extract_table_name(sql: str) -> Optional[str]:
        """提取表名"""
        patterns = [
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?",
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _extract_columns(sql: str) -> List[ColumnInfo]:
        """提取列定义"""
        columns = []

        # 提取括号内的内容
        match = re.search(r'\(([\s\S]+)\)\s*(?:ENGINE|CHARSET|USER|PROPERTIES|$)', sql, re.IGNORECASE)
        if not match:
            return columns

        body = match.group(1)

        # 按逗号分割，但忽略括号内的逗号
        lines = DDLParser._split_by_comma(body)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 跳过主键、索引、外键定义
            if re.match(r'(PRIMARY\s+KEY|INDEX|KEY|UNIQUE|FOREIGN\s+KEY|CONSTRAINT)', line, re.IGNORECASE):
                continue

            column = DDLParser._parse_column(line)
            if column:
                columns.append(column)

        return columns

    @staticmethod
    def _parse_column(line: str) -> Optional[ColumnInfo]:
        """解析单列定义"""
        # 匹配: column_name data_type [nullable] [default] [comment] [primary_key]
        # 示例: `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID' PRIMARY KEY

        # 提取列名
        name_match = re.match(r'[`"\']?(\w+)[`"\']?\s+', line, re.IGNORECASE)
        if not name_match:
            return None
        name = name_match.group(1)

        # 提取数据类型
        rest_after_name = line[name_match.end():]
        type_match = re.match(r'(\w+(?:\([^)]+\))?)', rest_after_name, re.IGNORECASE)
        if not type_match:
            return None
        data_type = type_match.group(1).upper()

        rest = rest_after_name[type_match.end():]

        # 检查是否为空
        nullable = 'NOT NULL' not in rest.upper()

        # 检查是否为主键
        is_primary_key = 'PRIMARY KEY' in rest.upper()

        # 提取默认值
        default = None
        default_match = re.search(r"DEFAULT\s+([^\s,]+)", rest, re.IGNORECASE)
        if default_match:
            default = default_match.group(1)

        # 提取注释
        comment = None
        comment_match = re.search(r"COMMENT\s+['\"]([^'\"]*)['\"]", rest, re.IGNORECASE)
        if comment_match:
            comment = comment_match.group(1)

        return ColumnInfo(
            name=name,
            data_type=data_type,
            nullable=nullable,
            default=default,
            comment=comment,
            is_primary_key=is_primary_key
        )

    @staticmethod
    def _extract_table_comment(sql: str) -> Optional[str]:
        """提取表注释"""
        match = re.search(r"COMMENT\s*=\s*['\"]([^'\"]*)['\"]", sql, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _split_by_comma(text: str) -> List[str]:
        """按逗号分割，忽略括号内的逗号"""
        result = []
        current = ""
        depth = 0

        for char in text:
            if char == '(':
                depth += 1
                current += char
            elif char == ')':
                depth -= 1
                current += char
            elif char == ',' and depth == 0:
                result.append(current)
                current = ""
            else:
                current += char

        if current.strip():
            result.append(current)

        return result
