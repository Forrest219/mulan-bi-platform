"""检查报告生成模块"""
import json
from typing import List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from .validator import Violation, ViolationLevel


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
    def generate(validation_results: Dict[str, List[Violation]]) -> CheckReport:
        """
        生成检查报告

        Args:
            validation_results: 验证结果，{表名: [违规列表]}

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
