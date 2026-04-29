"""SQL Agent — 安全校验模块（基于 sqlglot AST）"""

import sqlglot
from sqlglot import exp
from dataclasses import dataclass
from typing import List, Tuple, Optional


# -----------------------------------------------------------------------------
# 方言限制配置
# -----------------------------------------------------------------------------

DIALECT_LIMITS = {
    "starrocks": {"max_joins": 10, "max_subquery_depth": 5, "limit_default": 10_000},
    "mysql": {"max_joins": 8, "max_subquery_depth": 3, "limit_default": 1_000},
    "postgres": {"max_joins": 8, "max_subquery_depth": 3, "limit_default": 5_000},
    "postgresql": {"max_joins": 8, "max_subquery_depth": 3, "limit_default": 5_000},  # 别名
}

# sqlglot dialect 名称映射（项目 db_type → sqlglot dialect）
SQLGLOT_DIALECT_MAP = {
    "starrocks": "starrocks",
    "mysql": "mysql",
    "postgres": "postgres",
    "postgresql": "postgres",
}

# LIMIT 上限
LIMIT_CEILING = {
    "starrocks": 10_000,
    "mysql": 1_000,
    "postgres": 5_000,
    "postgresql": 5_000,
}

# 超时（秒）
QUERY_TIMEOUT = {
    "starrocks": 60,
    "mysql": 30,
    "postgres": 30,
    "postgresql": 30,
}

# MySQL 严格拦截的写操作
MYSQL_WRITE_BLOCKED = {"INSERT", "UPDATE", "DELETE"}

# 所有方言统一拦截的关键词
DANGEROUS_KEYWORDS = {"DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE", "LOAD_FILE", "INTO OUTFILE", "COPY TO"}

# MySQL 敏感系统表（精确表名）
MYSQL_SENSITIVE_TABLES = {
    "information_schema.processlist",
    "information_schema.security_users",
    "mysql.user",
    "mysql.db",
}

# PostgreSQL 敏感系统表（精确表名）
PG_SENSITIVE_TABLES = {
    "pg_roles",
    "pg_shadow",
    "pg_stat_activity",
    "pg_tablespace",
    "pg_file_settings",
}


# -----------------------------------------------------------------------------
# 校验结果
# -----------------------------------------------------------------------------

@dataclass
class ValidationResult:
    ok: bool
    action_type: str  # SELECT / INSERT / REJECTED
    reason: Optional[str] = None
    error_code: Optional[str] = None


# -----------------------------------------------------------------------------
# 安全校验器
# -----------------------------------------------------------------------------

class SQLSecurityValidator:
    """基于 sqlglot AST 的 SQL 安全校验器"""

    def __init__(self, db_type: str):
        if db_type not in DIALECT_LIMITS:
            raise ValueError(f"不支持的数据库类型: {db_type}")
        self.db_type = db_type
        self.sqlglot_dialect = SQLGLOT_DIALECT_MAP.get(db_type, db_type)
        self.limits = DIALECT_LIMITS[db_type]

    def validate(self, sql: str) -> ValidationResult:
        """
        执行完整的安全校验。
        顺序：语法解析 → 白名单扫描 → MySQL 写拦截 → 连表/子查询限制
        """
        # Step 1: 语法解析
        try:
            ast = sqlglot.parse(sql, dialect=self.sqlglot_dialect)
        except Exception:
            return ValidationResult(
                ok=False,
                action_type="REJECTED",
                reason="SQL 语法解析失败",
                error_code="SQLA_002",
            )

        if not ast:
            return ValidationResult(
                ok=False,
                action_type="REJECTED",
                reason="SQL 语法解析失败",
                error_code="SQLA_002",
            )

        # 取主语句（第一条）
        statement = ast[0]

        # Step 2: 白名单扫描（DDL / 危险关键词）
        ddl_result = self._check_ddl(statement)
        if not ddl_result.ok:
            return ddl_result

        # Step 3: MySQL 写操作拦截
        mysql_write_result = self._check_mysql_write(statement)
        if not mysql_write_result.ok:
            return mysql_write_result

        # Step 4: 敏感表访问拦截
        sensitive_result = self._check_sensitive_tables(statement)
        if not sensitive_result.ok:
            return sensitive_result

        # Step 5: 连表数量限制
        join_result = self._check_join_limit(statement)
        if not join_result.ok:
            return join_result

        # Step 6: 子查询深度限制
        subquery_result = self._check_subquery_depth(statement)
        if not subquery_result.ok:
            return subquery_result

        # Step 7: 识别 action_type
        action_type = self._detect_action_type(statement)

        return ValidationResult(ok=True, action_type=action_type)

    def _check_ddl(self, statement) -> ValidationResult:
        """拦截 DDL 和危险语句"""
        # 危险关键词集合（node type name 上限 → 实际 sqlglot 类型名）
        blocked_types = {"DROP", "TRUNCATETABLE", "ALTER", "CREATE", "GRANT", "REVOKE"}
        # 解析失败时降级为 Command 节点的 SQL 关键词
        blocked_command_keywords = {"GRANT", "REVOKE", "TRUNCATE", "LOAD DATA", "INTO OUTFILE", "COPY TO"}

        for node in statement.walk():
            node_type = type(node).__name__.upper()
            if node_type in blocked_types:
                return ValidationResult(
                    ok=False,
                    action_type="REJECTED",
                    reason=f"危险语句被拦截：{node_type}",
                    error_code="SQLA_001",
                )
            # 捕获解析器降级的 Command 节点
            if isinstance(node, exp.Command):
                cmd_name = node.args.get("this")
                if isinstance(cmd_name, str):
                    for kw in blocked_command_keywords:
                        if kw.upper() in cmd_name.upper():
                            return ValidationResult(
                                ok=False,
                                action_type="REJECTED",
                                reason=f"危险语句被拦截：{cmd_name.strip().upper()}",
                                error_code="SQLA_001",
                            )
            if isinstance(node, exp.LoadData):
                return ValidationResult(
                    ok=False,
                    action_type="REJECTED",
                    reason="LOAD DATA 被拦截",
                    error_code="SQLA_001",
                )
            # 拦截 INTO OUTFILE / COPY TO
            if isinstance(node, exp.Into):
                return ValidationResult(
                    ok=False,
                    action_type="REJECTED",
                    reason="INTO OUTFILE / COPY TO 被拦截",
                    error_code="SQLA_001",
                )
        return ValidationResult(ok=True, action_type="UNKNOWN")

    def _check_mysql_write(self, statement) -> ValidationResult:
        """MySQL 拦截写操作"""
        if self.db_type != "mysql":
            return ValidationResult(ok=True, action_type="UNKNOWN")
        for node in statement.walk():
            node_type = type(node).__name__.upper()
            if node_type in MYSQL_WRITE_BLOCKED:
                return ValidationResult(
                    ok=False,
                    action_type="REJECTED",
                    reason=f"{node_type} 操作在 MySQL 上不允许",
                    error_code="SQLA_001",
                )
        return ValidationResult(ok=True, action_type="UNKNOWN")

    def _check_sensitive_tables(self, statement) -> ValidationResult:
        """拦截敏感系统表访问"""
        # 用项目 db_type（而非 sqlglot dialect）做键
        blocked = {
            "mysql": MYSQL_SENSITIVE_TABLES,
            "postgresql": PG_SENSITIVE_TABLES,
            "postgres": PG_SENSITIVE_TABLES,
            "starrocks": set(),
        }.get(self.db_type, set())
        if not blocked:
            return ValidationResult(ok=True, action_type="UNKNOWN")

        for node in statement.walk():
            if isinstance(node, exp.Table):
                table_name = node.name.lower()
                db_obj = node.args.get("db")
                if isinstance(db_obj, str):
                    db_name = db_obj.lower()
                elif db_obj and hasattr(db_obj, "name"):
                    db_name = db_obj.name.lower()
                else:
                    db_name = ""
                full_name = f"{db_name}.{table_name}" if db_name else table_name
                if full_name in blocked or table_name in blocked:
                    return ValidationResult(
                        ok=False,
                        action_type="REJECTED",
                        reason=f"敏感对象访问被拦截：{full_name}",
                        error_code="SQLA_001",
                    )
        return ValidationResult(ok=True, action_type="UNKNOWN")

    def _check_join_limit(self, statement) -> ValidationResult:
        """检查 JOIN 数量是否超限"""
        max_joins = self.limits["max_joins"]
        join_count = sum(1 for node in statement.walk() if isinstance(node, exp.Join))
        if join_count > max_joins:
            return ValidationResult(
                ok=False,
                action_type="REJECTED",
                reason=f"连表数量 {join_count} 超出限制 {max_joins}",
                error_code="SQLA_003",
            )
        return ValidationResult(ok=True, action_type="UNKNOWN")

    def _check_subquery_depth(self, statement) -> ValidationResult:
        """
        检查子查询深度。
        深度计算：各 Select 节点的嵌套层数 = 其父 Subquery 链的长度。
        LIMIT_N 子查询层数 means depth < LIMIT_N, i.e. max_seen >= LIMIT_N -> BLOCK
        """
        max_depth = self.limits["max_subquery_depth"]

        def get_subquery_depth(node) -> int:
            """从 node 向上数有多少层 Subquery"""
            depth = 0
            current: exp.Expression = node
            while current is not None:
                parent = getattr(current, "parent", None)
                if isinstance(parent, exp.Subquery):
                    depth += 1
                current = parent
            return depth

        # 先收集所有 Select 节点，避免在遍历中调用 walk()（walk() 会修改 parent 引用）
        all_selects = [n for n in statement.walk() if isinstance(n, exp.Select)]

        max_seen = 0
        for sel in all_selects:
            depth = get_subquery_depth(sel)
            max_seen = max(max_seen, depth)

        # LIMIT N means depth >= N is blocked (depth 0 = outermost, depth 1 = first subquery)
        if max_seen >= max_depth:
            return ValidationResult(
                ok=False,
                action_type="REJECTED",
                reason=f"子查询深度 {max_seen} 超出限制 {max_depth}",
                error_code="SQLA_004",
            )
        return ValidationResult(ok=True, action_type="UNKNOWN")

    def _detect_action_type(self, statement) -> str:
        """识别 SQL 操作类型"""
        top = type(statement).__name__.upper()
        if top == "INSERT":
            return "INSERT"
        if top == "SELECT":
            return "SELECT"
        if top == "SHOW":
            return "SELECT"
        if top == "DESCRIBE":
            return "SELECT"
        if top == "EXPLAIN":
            return "SELECT"
        return "SELECT"
