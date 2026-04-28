"""Metrics Agent — formula 安全校验

对 metric.formula 做正则白名单校验，防止 SQL 注入。
consistency.py 和 anomaly_service.py 在拼装 SQL 前调用。
"""

import re

_MAX_FORMULA_LENGTH = 512

_DANGEROUS_KEYWORDS_RE = re.compile(
    r"\b("
    r"SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|"
    r"GRANT|REVOKE|UNION|INTO|FROM|WHERE|HAVING|ORDER|GROUP|LIMIT|OFFSET|"
    r"EXEC|EXECUTE|LOAD_FILE|OUTFILE|DUMPFILE|BENCHMARK|SLEEP|"
    r"INFORMATION_SCHEMA|PG_CATALOG|SYS\.|SYSIBM|"
    r"USER\s*\(|DATABASE\s*\(|VERSION\s*\(|CURRENT_USER|SESSION_USER"
    r")\b",
    re.IGNORECASE,
)

_SEMICOLON_RE = re.compile(r";")
_COMMENT_RE = re.compile(r"(--|/\*|\*/)")

_ALLOWED_TOKEN_RE = re.compile(
    r"^["
    r"a-zA-Z0-9_\.\s"
    r"\+\-\*/%"
    r"\(\),"
    r"'\""
    r"]*$"
)

_ALLOWED_FUNCTIONS = {
    "SUM", "AVG", "COUNT", "COUNT_DISTINCT", "MAX", "MIN",
    "ABS", "ROUND", "CEIL", "CEILING", "FLOOR", "POWER", "SQRT", "MOD",
    "COALESCE", "NULLIF", "IF", "IIF", "IFNULL",
    "CASE", "WHEN", "THEN", "ELSE", "END",
    "CAST", "CONVERT",
    "DISTINCT", "AS",
    "AND", "OR", "NOT",
    "IS", "NULL", "IN", "BETWEEN", "LIKE",
    "TRUE", "FALSE",
    "DATE", "YEAR", "MONTH", "DAY",
}

_FUNCTION_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

_STRING_LITERAL_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def validate_formula(formula: str) -> str:
    """校验 formula 安全性，通过返回原值，不通过抛 ValueError。"""
    if not formula or not formula.strip():
        raise ValueError("formula 不能为空")

    if len(formula) > _MAX_FORMULA_LENGTH:
        raise ValueError(f"formula 长度超限（最大 {_MAX_FORMULA_LENGTH} 字符）")

    if _SEMICOLON_RE.search(formula):
        raise ValueError("formula 不允许包含分号")

    if _COMMENT_RE.search(formula):
        raise ValueError("formula 不允许包含 SQL 注释符（-- 或 /* */）")

    if _DANGEROUS_KEYWORDS_RE.search(formula):
        match = _DANGEROUS_KEYWORDS_RE.search(formula)
        raise ValueError(f"formula 包含禁止的 SQL 关键字：{match.group() if match else '未知'}")

    stripped = _STRING_LITERAL_RE.sub("", formula)

    for m in _FUNCTION_CALL_RE.finditer(stripped):
        func_name = m.group(1).upper()
        if func_name not in _ALLOWED_FUNCTIONS:
            raise ValueError(f"formula 包含不允许的函数调用：{m.group(1)}")

    return formula
