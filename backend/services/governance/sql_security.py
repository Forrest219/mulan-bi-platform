"""Custom SQL 安全校验 — 黑名单关键字检测"""

import re

# 禁止的关键字（大小写不敏感）
FORBIDDEN_KEYWORDS = [
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "REVOKE",
    "COPY",
    "pg_read_file",
    "pg_execute_server_program",
    "pg_export_snapshot",
    "lo_import",
    "lo_export",
]

# 正则变种检测
FORBIDDEN_PATTERNS = [
    r"(/\*.*?\*/)",  # 注释插入
    r"(\b\d+\b\s+\b\d+\b)",  # 数字分隔符
]


def validate_custom_sql(sql: str) -> tuple[bool, str]:
    """
    校验 custom_sql 是否安全。
    返回：(is_safe, error_message)
    - 仅允许 SELECT 开头
    - 禁止关键字检测
    - 禁止注释/变形注入
    """
    sql_upper = sql.strip().upper()

    # 必须以 SELECT 开头
    if not sql_upper.startswith("SELECT"):
        return False, "custom_sql 必须以 SELECT 开头"

    # 检查禁止关键字（使用 IGNORECASE 匹配大小写）
    for kw in FORBIDDEN_KEYWORDS:
        pattern = r"\b" + kw + r"\b"
        if re.search(pattern, sql_upper, re.IGNORECASE):
            return False, f"禁止的关键字: {kw}"

    # 检查变形注入
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE):
            return False, f"检测到可疑模式: {pattern}"

    return True, ""