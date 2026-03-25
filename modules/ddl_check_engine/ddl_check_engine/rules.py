"""DDL 检查规则"""
from typing import List, Callable, Optional
from dataclasses import dataclass
from enum import Enum

from .parser import TableInfo, ColumnInfo


class RiskLevel(Enum):
    """风险等级"""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


@dataclass
class CheckIssue:
    """检查问题"""
    rule_id: str
    risk_level: RiskLevel
    object_type: str  # table / column
    object_name: str
    description: str
    suggestion: str


class BaseRule:
    """规则基类"""

    def __init__(self, rule_id: str, name: str, risk_level: RiskLevel):
        self.rule_id = rule_id
        self.name = name
        self.risk_level = risk_level

    def check(self, table: TableInfo) -> List[CheckIssue]:
        raise NotImplementedError


class TableNamingRule(BaseRule):
    """表命名规范（High）"""

    def __init__(self):
        super().__init__("RULE_001", "表命名规范", RiskLevel.HIGH)
        self.pattern = r'^[a-z][a-z0-9_]*$'
        self.max_length = 64

    def check(self, table: TableInfo) -> List[CheckIssue]:
        issues = []
        table_name = table.name

        # 检查长度
        if len(table_name) > self.max_length:
            issues.append(CheckIssue(
                rule_id=self.rule_id,
                risk_level=self.risk_level,
                object_type="table",
                object_name=table_name,
                description=f"表名长度 {len(table_name)} 超过限制 {self.max_length}",
                suggestion=f"将表名控制在 {self.max_length} 字符以内"
            ))

        # 检查命名模式
        import re
        if not re.match(self.pattern, table_name):
            issues.append(CheckIssue(
                rule_id=self.rule_id,
                risk_level=self.risk_level,
                object_type="table",
                object_name=table_name,
                description="表名不符合命名规范",
                suggestion="表名必须以小写字母开头，支持小写字母、数字、下划线"
            ))

        return issues


class ColumnCommentRule(BaseRule):
    """字段必须有注释（High）"""

    def __init__(self):
        super().__init__("RULE_002", "字段必须有注释", RiskLevel.HIGH)

    def check(self, table: TableInfo) -> List[CheckIssue]:
        issues = []

        for col in table.columns:
            if not col.comment or not col.comment.strip():
                issues.append(CheckIssue(
                    rule_id=self.rule_id,
                    risk_level=self.risk_level,
                    object_type="column",
                    object_name=col.name,
                    description=f"字段 '{col.name}' 缺少注释",
                    suggestion=f"为字段 '{col.name}' 添加 COMMENT 说明其含义"
                ))

        return issues


class AmountTypeRule(BaseRule):
    """金额字段类型（Medium）"""

    def __init__(self):
        super().__init__("RULE_003", "金额字段类型", RiskLevel.MEDIUM)
        self.amount_keywords = ['amount', 'price', 'cost', 'total', 'money', 'fee', 'balance']
        self.bad_types = ['FLOAT', 'DOUBLE', 'DECIMAL']  # DECIMAL is acceptable, but we warn if precision not specified

    def check(self, table: TableInfo) -> List[CheckIssue]:
        issues = []

        for col in table.columns:
            col_name_lower = col.name.lower()

            # 检查是否包含金额相关关键词
            if any(keyword in col_name_lower for keyword in self.amount_keywords):
                # 检查数据类型
                if col.data_type.upper() in self.bad_types:
                    if col.data_type.upper() == 'DECIMAL':
                        # DECIMAL 需要指定精度
                        if '(' not in col.data_type:
                            issues.append(CheckIssue(
                                rule_id=self.rule_id,
                                risk_level=self.risk_level,
                                object_type="column",
                                object_name=col.name,
                                description=f"金额字段 '{col.name}' 使用 DECIMAL 但未指定精度",
                                suggestion=f"建议使用 DECIMAL(18,2) 等明确精度"
                            ))
                    else:
                        issues.append(CheckIssue(
                            rule_id=self.rule_id,
                            risk_level=self.risk_level,
                            object_type="column",
                            object_name=col.name,
                            description=f"金额字段 '{col.name}' 使用了不推荐的数据类型 {col.data_type}",
                            suggestion="建议使用 DECIMAL(p,s) 类型确保精度"
                        ))

        return issues


class CreateTimeRule(BaseRule):
    """必须包含 create_time（High）"""

    def __init__(self):
        super().__init__("RULE_004", "必须包含 create_time", RiskLevel.HIGH)

    def check(self, table: TableInfo) -> List[CheckIssue]:
        issues = []

        column_names = [col.name.lower() for col in table.columns]
        if 'create_time' not in column_names:
            issues.append(CheckIssue(
                rule_id=self.rule_id,
                risk_level=self.risk_level,
                object_type="table",
                object_name=table.name,
                description=f"表 '{table.name}' 缺少 create_time 字段",
                suggestion="添加 create_time DATETIME 字段记录创建时间"
            ))

        return issues


class UpdateTimeRule(BaseRule):
    """必须包含 update_time（High）"""

    def __init__(self):
        super().__init__("RULE_005", "必须包含 update_time", RiskLevel.HIGH)

    def check(self, table: TableInfo) -> List[CheckIssue]:
        issues = []

        column_names = [col.name.lower() for col in table.columns]
        if 'update_time' not in column_names:
            issues.append(CheckIssue(
                rule_id=self.rule_id,
                risk_level=self.risk_level,
                object_type="table",
                object_name=table.name,
                description=f"表 '{table.name}' 缺少 update_time 字段",
                suggestion="添加 update_time DATETIME 字段记录更新时间"
            ))

        return issues


def get_default_rules() -> List[BaseRule]:
    """获取默认规则列表"""
    return [
        TableNamingRule(),
        ColumnCommentRule(),
        AmountTypeRule(),
        CreateTimeRule(),
        UpdateTimeRule(),
    ]
