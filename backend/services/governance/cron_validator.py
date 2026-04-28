"""Cron 表达式格式校验"""

import re
from typing import Optional

# 标准 5 字段 Cron 格式：分 时 日 月 周
# 支持：* 、具体数值、步长(*/n)
# 格式: minute hour day month weekday
CRON_REGEX = re.compile(
    r'^(\*(/[0-9]+)?|([0-5]?\d)(/[0-9]+)?)\s+'
    r'(\*(/[0-9]+)?|([01]?\d|2[0-3])(/[0-9]+)?)\s+'
    r'(\*(/[0-9]+)?|([12]?\d|3[01])(/[0-9]+)?)\s+'
    r'(\*(/[0-9]+)?|([1-9]|1[0-2])(/[0-9]+)?)\s+'
    r'(\*(/[0-9]+)?|([0-6])(/[0-9]+)?)$'
)


def validate_cron(expression: Optional[str]) -> None:
    """校验 Cron 表达式格式是否合法"""
    if expression is None:
        return
    if not CRON_REGEX.match(expression.strip()):
        raise ValueError(f"Cron 表达式格式无效: {expression}")