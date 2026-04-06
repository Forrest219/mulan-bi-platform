"""检查报告生成模块"""
import json
import re
from typing import List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from .validator import Violation, ViolationLevel


# 敏感关键词列表（匹配列名或表名时脱敏）
SENSITIVE_KEYWORDS = [
    r"phone", r"mobile", r"tel",
    r"id_card", r"idcard", r"identity", r"身份证",
    r"password", r"pwd", r"passwd", r"secret",
    r"bank", r"card", r"账号", r"账户",
    r"credit", r"debit", r"cvv", r"cvc",
    r"social", r"security", r"社保",
    r"salary", r"wage", r"工资",
    r"address", r"addr", r"地址",
]

# 脱敏替换符
MASK_CHAR = "*"
MASK_PATTERN = re.compile(r"(" + "|".join(SENSITIVE_KEYWORDS) + r")", re.IGNORECASE)


def mask_value(value: str) -> str:
    """
    对敏感值进行脱敏处理。

    规则：
    - 保留首字符
    - 保留末字符
    - 中间字符替换为 *
    - 总长度 >= 8 时保留首尾各 2 字符
    """
    if not value or len(value) < 4:
        return MASK_CHAR * len(value) if value else ""

    if len(value) <= 6:
        # 短字符串：保留首尾
        return value[0] + MASK_CHAR * (len(value) - 2) + value[-1]

    # 长字符串：保留首2尾2
    return value[:2] + MASK_CHAR * (len(value) - 4) + value[-2:]


def mask_column_name(name: str) -> str:
    """
    对列名进行脱敏。

    若列名命中敏感关键词，返回脱敏后的列名。
    """
    if not name:
        return name

    # 检查是否命中敏感关键词
    if MASK_PATTERN.search(name):
        # 保留原始结构信息，只替换敏感部分
        return MASK_PATTERN.sub(lambda m: mask_value(m.group(1)), name, count=1)

    return name


def mask_violation_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    对单条违规记录进行脱敏处理。

    规则：
    - column_name 命中敏感词时脱敏
    - table_name 命中敏感词时脱敏
    - message 中的敏感内容脱敏
    """
    masked = record.copy()

    # 脱敏列名
    if "column_name" in masked and masked["column_name"]:
        masked["column_name"] = mask_column_name(masked["column_name"])

    # 脱敏表名
    if "table_name" in masked and masked["table_name"]:
        if MASK_PATTERN.search(masked["table_name"]):
            parts = masked["table_name"].split("_")
            masked["table_name"] = "_".join(mask_column_name(p) for p in parts)

    # 脱敏消息（如果有）
    if "message" in masked and masked["message"]:
        msg = masked["message"]
        # 脱敏引号内的值
        msg = re.sub(r"'([^']+)'", lambda m: f"'{mask_value(m.group(1))}'", msg)
        masked["message"] = msg

    return masked


def mask_results(results: Any) -> Any:
    """
    对扫描结果进行递归脱敏处理。

    支持：
    - Dict: 递归处理每个 key-value
    - List: 递归处理每个元素
    - str: 检查是否需要脱敏
    """
    if isinstance(results, dict):
        return {k: mask_results(v) for k, v in results.items()}
    elif isinstance(results, list):
        return [mask_results(item) for item in results]
    elif isinstance(results, str):
        # 字符串值检查是否包含需要脱敏的内容
        if MASK_PATTERN.search(results):
            # 简单处理：返回脱敏标记
            return MASK_PATTERN.sub(lambda m: mask_value(m.group(1)), results)
        return results
    else:
        return results


@dataclass
class CheckReport:
    """检查报告"""
    check_time: str
    total_tables: int
    total_violations: int
    error_count: int
    warning_count: int
    info_count: int
    table_results: Dict[str, List[Dict[str, Any]]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def get_summary(self) -> str:
        """获取报告摘要"""
        return (
            f"检查时间: {self.check_time}\n"
            f"检查表数: {self.total_tables}\n"
            f"违规总数: {self.total_violations}\n"
            f"  - 错误: {self.error_count}\n"
            f"  - 警告: {self.warning_count}\n"
            f"  - 提示: {self.info_count}"
        )


class ReportGenerator:
    """报告生成器"""

    @staticmethod
    def generate(validation_results: Dict[str, List[Violation]], mask: bool = True) -> CheckReport:
        """
        生成检查报告

        Args:
            validation_results: 验证结果，{表名: [违规列表]}
            mask: 是否对结果进行脱敏处理，默认 True

        Returns:
            CheckReport 对象
        """
        table_results = {}
        total_violations = 0
        error_count = 0
        warning_count = 0
        info_count = 0

        for table_name, violations in validation_results.items():
            violations_dict = [v.to_dict() for v in violations]

            # 脱敏处理
            if mask:
                violations_dict = [mask_violation_record(v) for v in violations_dict]

            table_results[table_name] = violations_dict

            total_violations += len(violations)
            error_count += sum(1 for v in violations if v.level == ViolationLevel.ERROR)
            warning_count += sum(1 for v in violations if v.level == ViolationLevel.WARNING)
            info_count += sum(1 for v in violations if v.level == ViolationLevel.INFO)

        return CheckReport(
            check_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_tables=len(validation_results),
            total_violations=total_violations,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            table_results=table_results,
        )

    @staticmethod
    def export_json(report: CheckReport, output_path: str):
        """导出 JSON 格式报告"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report.to_json())

    @staticmethod
    def export_html(report: CheckReport, output_path: str):
        """导出 HTML 格式报告"""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>DDL 规范检查报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .summary-item {{ display: inline-block; margin-right: 20px; }}
        .error {{ color: #d32f2f; font-weight: bold; }}
        .warning {{ color: #f57c00; font-weight: bold; }}
        .info {{ color: #1976d2; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .level-error {{ background-color: #ffebee; }}
        .level-warning {{ background-color: #fff3e0; }}
        .level-info {{ background-color: #e3f2fd; }}
    </style>
</head>
<body>
    <h1>DDL 规范检查报告</h1>
    <div class="summary">
        <div class="summary-item"><strong>检查时间:</strong> {report.check_time}</div>
        <div class="summary-item"><strong>检查表数:</strong> {report.total_tables}</div>
        <div class="summary-item"><strong>违规总数:</strong> {report.total_violations}</div>
        <div class="summary-item"><span class="error">错误: {report.error_count}</span></div>
        <div class="summary-item"><span class="warning">警告: {report.warning_count}</span></div>
        <div class="summary-item"><span class="info">提示: {report.info_count}</span></div>
    </div>
"""

        for table_name, violations in report.table_results.items():
            if not violations:
                continue

            html += f"""
    <h2>表: {table_name}</h2>
    <table>
        <tr>
            <th>级别</th>
            <th>规则</th>
            <th>列名</th>
            <th>消息</th>
            <th>建议</th>
        </tr>
"""
            for v in violations:
                level_class = f"level-{v['level']}"
                level_text = {"error": "错误", "warning": "警告", "info": "提示"}.get(v["level"], v["level"])
                html += f"""
        <tr class="{level_class}">
            <td class="{v['level']}">{level_text}</td>
            <td>{v['rule_name']}</td>
            <td>{v['column_name'] or '-'}</td>
            <td>{v['message']}</td>
            <td>{v['suggestion']}</td>
        </tr>
"""
            html += """
    </table>
"""

        html += """
</body>
</html>
"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
