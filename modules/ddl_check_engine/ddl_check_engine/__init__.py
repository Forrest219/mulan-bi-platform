"""
DDL Check Engine - 轻量级 DDL 规则引擎

用于校验建表 SQL 是否符合公司规范的规则引擎工具

功能：
- DDL 文本解析
- 规则校验
- 结果输出

不做：
- 不连接数据库
- 不执行 SQL
- 不存储历史
"""

from .engine import DDLCheckEngine, CheckResult, CheckIssue, check_ddl

__all__ = ["DDLCheckEngine", "CheckResult", "CheckIssue", "check_ddl"]
__version__ = "1.0.0"
