"""
DDL Check Engine - 轻量级 DDL 规则引擎

提供纯规则的 DDL 检查功能，不连接数据库，不存储历史
"""

from typing import List, Optional
from dataclasses import dataclass, field
import json

from .parser import DDLParser, TableInfo
from .rules import BaseRule, CheckIssue, RiskLevel, get_default_rules


@dataclass
class CheckResult:
    """
    检查结果

    Attributes:
        passed: 是否通过检查
        score: 评分 (0-100)
        summary: 问题汇总
        issues: 问题列表
        executable: 是否允许执行
        table_name: 表名
        db_type: 数据库类型
    """
    passed: bool
    score: int
    summary: dict
    issues: List[dict]
    executable: bool
    table_name: str = ""
    db_type: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": self.score,
            "summary": self.summary,
            "issues": self.issues,
            "executable": self.executable
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class DDLCheckEngine:
    """
    DDL 检查引擎

    用法:
        engine = DDLCheckEngine()
        result = engine.check("CREATE TABLE ...")
    """

    def __init__(self, rules: Optional[List[BaseRule]] = None):
        """
        初始化检查引擎

        Args:
            rules: 规则列表，默认使用5条默认规则
        """
        self.rules = rules or get_default_rules()
        self.parser = DDLParser()

    def check(self, ddl_text: str, db_type: str = "mysql") -> CheckResult:
        """
        检查 DDL 语句

        Args:
            ddl_text: CREATE TABLE 语句
            db_type: 数据库类型 (mysql / sqlserver)

        Returns:
            CheckResult 检查结果
        """
        # 解析 DDL
        table_info = self.parser.parse(ddl_text)

        if not table_info:
            return CheckResult(
                passed=False,
                score=0,
                summary={"High": 0, "Medium": 0, "Low": 0},
                issues=[{
                    "rule_id": "PARSE_ERROR",
                    "risk_level": "High",
                    "object_type": "table",
                    "object_name": "",
                    "description": "无法解析 DDL 语句",
                    "suggestion": "请检查 CREATE TABLE 语法是否正确"
                }],
                executable=False,
                table_name="",
                db_type=db_type
            )

        # 执行检查
        all_issues = []
        for rule in self.rules:
            issues = rule.check(table_info)
            all_issues.extend(issues)

        # 计算评分
        score, summary = self._calculate_score(all_issues)

        # 判断是否允许执行：有 High 级问题或 score < 60 则不允许
        executable = score >= 60 and not any(
            issue.risk_level == RiskLevel.HIGH for issue in all_issues
        )

        # 判断是否通过
        passed = executable and score >= 80

        # 转换 issues 为 dict
        issues_dict = [self._issue_to_dict(issue) for issue in all_issues]

        return CheckResult(
            passed=passed,
            score=score,
            summary=summary,
            issues=issues_dict,
            executable=executable,
            table_name=table_info.name,
            db_type=db_type
        )

    def _calculate_score(self, issues: List[CheckIssue]) -> tuple:
        """
        计算评分

        Score = 100 - High*20 - Medium*5 - Low*1

        Returns:
            (score, summary_dict)
        """
        high_count = sum(1 for i in issues if i.risk_level == RiskLevel.HIGH)
        medium_count = sum(1 for i in issues if i.risk_level == RiskLevel.MEDIUM)
        low_count = sum(1 for i in issues if i.risk_level == RiskLevel.LOW)

        score = 100 - high_count * 20 - medium_count * 5 - low_count * 1
        score = max(0, min(100, score))  # 限制在 0-100

        summary = {
            "High": high_count,
            "Medium": medium_count,
            "Low": low_count
        }

        return score, summary

    @staticmethod
    def _issue_to_dict(issue: CheckIssue) -> dict:
        """将 CheckIssue 转换为 dict"""
        return {
            "rule_id": issue.rule_id,
            "risk_level": issue.risk_level.value,
            "object_type": issue.object_type,
            "object_name": issue.object_name,
            "description": issue.description,
            "suggestion": issue.suggestion
        }


# 快捷函数
def check_ddl(ddl_text: str, db_type: str = "mysql") -> CheckResult:
    """
    快捷检查函数

    Args:
        ddl_text: CREATE TABLE 语句
        db_type: 数据库类型

    Returns:
        CheckResult 检查结果
    """
    engine = DDLCheckEngine()
    return engine.check(ddl_text, db_type)
