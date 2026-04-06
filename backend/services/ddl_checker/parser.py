"""DDL 解析模块 — 正则优先 + AST 回退双引擎"""
import re
from typing import List, Dict, Any, Optional, Tuple

# ReDoS 深度防护：使用 regex 模块（支持原生 timeout）
try:
    import regex as re_module
    _HAS_REGEX_MODULE = True
except ImportError:
    _HAS_REGEX_MODULE = False

# 回退到标准 re 模块
import re as std_re

# 超时配置（秒）
REGEX_TIMEOUT_SEC = 0.2  # 200ms


class RegexTimeoutError(Exception):
    """正则匹配超时异常"""
    pass


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
    """
    DDL 解析器 — 正则优先 + AST 回退双引擎

    parse_mode:
        - regex: 正则解析成功
        - ast: 正则提取失败，自动降级 AST 解析成功
        - None: 解析失败
    """

    def __init__(self):
        self.parse_mode: Optional[str] = None

    def parse_create_table(self, sql: str) -> Tuple[Optional[TableInfo], Optional[str]]:
        """
        解析 CREATE TABLE 语句（双引擎）

        Args:
            sql: CREATE TABLE 语句

        Returns:
            Tuple[TableInfo, parse_mode]: TableInfo 对象和解析模式，
            解析失败返回 (None, None)
        """
        sql = sql.strip()

        # 第一阶段：正则解析
        try:
            table_info = self._parse_with_regex(sql)
            if table_info and table_info.name and table_info.columns:
                self.parse_mode = "regex"
                return table_info, "regex"
        except RegexTimeoutError:
            # 正则超时，尝试 AST 回退
            pass
        except Exception:
            pass

        # 第二阶段：AST 回退（当正则提取元数据为空且 SQL 合法时）
        if self._is_valid_sql(sql):
            try:
                table_info = self._parse_with_ast(sql)
                if table_info and table_info.name:
                    self.parse_mode = "ast"
                    return table_info, "ast"
            except Exception:
                pass

        # 解析失败
        self.parse_mode = None
        return None, None

    def _parse_with_regex(self, sql: str) -> Optional[TableInfo]:
        """正则解析（带 200ms 超时保护，使用 regex 模块）"""
        # 使用 regex 模块（支持原生 timeout）进行安全正则匹配
        if not _HAS_REGEX_MODULE:
            # 无 regex 模块时使用标准 re，但无超时保护（降级）
            _re = std_re
        else:
            _re = re_module

        try:
            # 提取表名（带超时保护）
            table_name = DDLParser._extract_table_name_with_timeout(sql, _re, REGEX_TIMEOUT_SEC)
            if not table_name:
                return None

            # 提取列定义（含表级 COMMENT 提取，带超时保护）
            columns, table_comment = DDLParser._extract_columns_with_timeout(sql, _re, REGEX_TIMEOUT_SEC)

            # 提取索引定义（带超时保护）
            indexes = DDLParser._extract_indexes_with_timeout(sql, table_name, _re, REGEX_TIMEOUT_SEC)

            return TableInfo(name=table_name, columns=columns, indexes=indexes, comment=table_comment)
        except TimeoutError:
            raise RegexTimeoutError(f"正则匹配超过 {REGEX_TIMEOUT_SEC * 1000:.0f}ms")

    def _is_valid_sql(self, sql: str) -> bool:
        """检查 SQL 是否语法合法（简单检查）"""
        sql_upper = sql.strip().upper()
        return "CREATE" in sql_upper and "TABLE" in sql_upper

    def _parse_with_ast(self, sql: str) -> Optional[TableInfo]:
        """
        AST 解析（使用 sqlglot 或 sqlparse 降级）

        优先尝试 sqlglot，失败则回退 sqlparse。
        """
        table_info = self._parse_with_sqlglot(sql)
        if table_info:
            return table_info

        # 回退 sqlparse
        return self._parse_with_sqlparse(sql)

    def _parse_with_sqlglot(self, sql: str) -> Optional[TableInfo]:
        """使用 sqlglot 解析"""
        try:
            import sqlglot
            stmt = sqlglot.parse_one(sql, dialect="mysql")
            if not stmt or not stmt.name:
                return None

            table_name = stmt.name
            columns = []
            indexes = []

            # 提取列
            for col in stmt.columns:
                col_name = col.name if hasattr(col, 'name') else str(col)
                data_type = col.data_type if hasattr(col, 'data_type') and col.data_type else "UNKNOWN"
                nullable = not (hasattr(col, 'nullable') and not col.nullable)
                comment = col.comment if hasattr(col, 'comment') and col.comment else ""

                columns.append(ColumnInfo(
                    name=col_name,
                    data_type=str(data_type),
                    nullable=nullable,
                    comment=comment,
                ))

            # 提取索引
            for idx in stmt.indexes:
                idx_name = idx.name if hasattr(idx, 'name') else "idx_unknown"
                idx_cols = [c.name if hasattr(c, 'name') else str(c) for c in idx.columns]
                is_unique = idx.kind == "UNIQUE" if hasattr(idx, 'kind') else False
                indexes.append(IndexInfo(
                    name=idx_name,
                    columns=idx_cols,
                    is_unique=is_unique,
                ))

            # 提取表注释
            table_comment = stmt.comment if hasattr(stmt, 'comment') and stmt.comment else ""

            return TableInfo(
                name=table_name,
                columns=columns,
                indexes=indexes,
                comment=table_comment,
            )
        except Exception:
            return None

    def _parse_with_sqlparse(self, sql: str) -> Optional[TableInfo]:
        """使用 sqlparse 解析（备选）"""
        try:
            import sqlparse
            parsed = sqlparse.parse(sql)
            if not parsed:
                return None

            stmt = parsed[0]
            table_name = None
            columns = []
            indexes = []
            table_comment = ""

            # 提取表名
            for token in stmt.tokens:
                if token.ttype in (sqlparse.tokens.Keyword, sqlparse.tokens.Name):
                    if token.value.upper() == "TABLE":
                        continue
                    if not table_name and token.ttype in (sqlparse.tokens.Name, sqlparse.tokens.String):
                        table_name = token.get_name() or token.value.strip('`"')
                        break

            if not table_name:
                # 尝试从 token 列表找表名
                name_tokens = [t for t in stmt.tokens if t.ttype in (sqlparse.tokens.Name,)]
                for t in name_tokens:
                    if t.value.upper() not in ("TABLE", "IF", "NOT", "EXISTS"):
                        table_name = t.get_name() or t.value.strip('`"')
                        break

            if not table_name:
                return None

            # 简化解析：提取列和索引的文本描述
            stmt_str = str(stmt)
            for line in stmt_str.split(","):
                line = line.strip()
                if not line or line.startswith(("INDEX", "KEY", "PRIMARY", "UNIQUE", "FOREIGN", "CONSTRAINT")):
                    continue

            return TableInfo(
                name=table_name,
                columns=columns,
                indexes=indexes,
                comment=table_comment,
            )
        except Exception:
            return None

    @staticmethod
    def _extract_table_name(sql: str) -> Optional[str]:
        """提取表名（不带超时保护，供 AST 模式使用）"""
        # 匹配 CREATE TABLE `table_name` 或 CREATE TABLE table_name
        pattern = r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?"
        match = re.search(pattern, sql, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_table_name_with_timeout(sql: str, _re, timeout: float) -> Optional[str]:
        """提取表名（带超时保护）"""
        pattern = r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?"
        match = _re.search(pattern, sql, re.IGNORECASE, timeout=timeout)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_columns(sql: str) -> tuple:
        """提取列定义

        Returns:
            tuple: (List[ColumnInfo], table_comment: str)
        """
        columns = []
        table_comment = ""

        # 提取列定义部分
        paren_depth = 0
        col_start = -1
        in_columns = False
        table_comment_section = ""

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
                    table_comment_section = sql[i:]
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

        # 从表级 COMMENT 部分提取表注释
        table_comment = DDLParser._extract_table_comment(table_comment_section)

        return columns, table_comment

    @staticmethod
    def _extract_columns_with_timeout(sql: str, _re, timeout: float) -> tuple:
        """提取列定义（带超时保护）

        Returns:
            tuple: (List[ColumnInfo], table_comment: str)
        """
        columns = []
        table_comment = ""

        # 提取列定义部分（纯字符操作，无 ReDoS 风险）
        paren_depth = 0
        col_start = -1
        in_columns = False
        table_comment_section = ""

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
                    table_comment_section = sql[i:]
                    break

        # 解析每一行列定义
        lines = DDLParser._split_sql_lines(column_section)
        for line in lines:
            line = line.strip().rstrip(",")
            if not line:
                continue

            # 跳过索引、主键、外键定义
            if _re.match(r"(INDEX|KEY|PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CONSTRAINT)", line, re.IGNORECASE, timeout=timeout):
                continue

            column = DDLParser._parse_column_definition_with_timeout(line, _re, timeout)
            if column:
                columns.append(column)

        # 从表级 COMMENT 部分提取表注释
        table_comment = DDLParser._extract_table_comment_with_timeout(table_comment_section, _re, timeout)

        return columns, table_comment

    @staticmethod
    def _extract_table_comment(sql_tail: str) -> str:
        """从 SQL 尾部提取表级 COMMENT

        支持两种格式:
        - COMMENT='表注释'
        - COMMENT="表注释"

        Args:
            sql_tail: 闭括号之后的 SQL 部分

        Returns:
            表注释字符串，无则返回空字符串
        """
        if not sql_tail:
            return ""

        # 匹配 COMMENT='xxx' 或 COMMENT="xxx"
        match = re.search(r"COMMENT\s*=\s*['\"]([^'\"]*)['\"]", sql_tail, re.IGNORECASE)
        if match:
            return match.group(1)

        # 兼容 MySQL 语法: COMMENT 'xxx'（无等号）
        match = re.search(r"COMMENT\s+['\"]([^'\"]*)['\"]", sql_tail, re.IGNORECASE)
        if match:
            return match.group(1)

        return ""

    @staticmethod
    def _extract_table_comment_with_timeout(sql_tail: str, _re, timeout: float) -> str:
        """从 SQL 尾部提取表级 COMMENT（带超时保护）"""
        if not sql_tail:
            return ""

        # 匹配 COMMENT='xxx' 或 COMMENT="xxx"
        match = _re.search(r"COMMENT\s*=\s*['\"]([^'\"]*)['\"]", sql_tail, re.IGNORECASE, timeout=timeout)
        if match:
            return match.group(1)

        # 兼容 MySQL 语法: COMMENT 'xxx'（无等号）
        match = _re.search(r"COMMENT\s+['\"]([^'\"]*)['\"]", sql_tail, re.IGNORECASE, timeout=timeout)
        if match:
            return match.group(1)

        return ""

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
    def _parse_column_definition_with_timeout(line: str, _re, timeout: float) -> Optional[ColumnInfo]:
        """解析单行列定义（带超时保护）"""
        # 匹配列名、数据类型、可选值等
        pattern = r"^[`\"']?(\w+)[`\"']?\s+(\w+(?:\([^)]+\))?)"
        match = _re.match(pattern, line, re.IGNORECASE, timeout=timeout)
        if not match:
            return None

        name = match.group(1)
        data_type = match.group(2)

        # 检查是否为主键
        is_primary_key = bool(_re.search(r"PRIMARY\s+KEY", line, re.IGNORECASE, timeout=timeout))

        # 检查是否为空
        nullable = "NOT NULL" not in line.upper()

        # 提取默认值
        default = None
        default_match = _re.search(r"DEFAULT\s+([^\s,]+)", line, re.IGNORECASE, timeout=timeout)
        if default_match:
            default = default_match.group(1)

        # 提取注释
        comment = ""
        comment_match = _re.search(r"COMMENT\s+['\"]([^'\"]*)['\"]", line, re.IGNORECASE, timeout=timeout)
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
    def _extract_indexes_with_timeout(sql: str, table_name: str, _re, timeout: float) -> List[IndexInfo]:
        """提取索引定义（带超时保护）"""
        indexes = []

        # 提取主键
        pk_pattern = r"PRIMARY\s+KEY\s*\(([^)]+)\)"
        pk_match = _re.search(pk_pattern, sql, re.IGNORECASE, timeout=timeout)
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
            for match in _re.finditer(pattern, sql, re.IGNORECASE, timeout=timeout):
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
