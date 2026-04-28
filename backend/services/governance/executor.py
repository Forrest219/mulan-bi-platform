"""质量规则执行器"""

from typing import Any, Optional

from backend.services.governance.engine import QualitySQLEngine, SQLGenerationError
from backend.services.governance.sql_security import validate_custom_sql
from backend.services.governance.models import QualityRule


class RuleExecutor:
    """
    规则执行器：
    1. 生成检测 SQL
    2. 连接目标数据库执行
    3. 比较实际值与阈值
    4. 熔断保护
    """

    def __init__(self, datasource_conn_info: dict):
        """
        datasource_conn_info: 从 bi_data_sources.decrypt() 获取
        {
            "db_type": "postgresql",
            "host": "...",
            "port": ...,
            "database": "...",
            "username": "...",
            "password": "..."
        }
        """
        self.conn_info = datasource_conn_info
        self.db_type = datasource_conn_info.get("db_type", "postgresql")
        self.engine = QualitySQLEngine(db_type=self.db_type)

    def execute_rule(
        self,
        rule_type: str,
        table_name: str,
        column_name: str,
        threshold: dict,
        operator: str,
        field_name: Optional[str] = None,
    ) -> dict:
        """
        执行规则，返回检测结果。
        返回：{
            "passed": bool,
            "actual_value": float | None,
            "expected": str,
            "detail": dict,
            "error": str | None
        }
        """
        try:
            # 1. 生成 SQL
            if rule_type == "custom_sql":
                is_safe, err = validate_custom_sql(threshold.get("custom_sql", ""))
                if not is_safe:
                    return {
                        "passed": False,
                        "actual_value": None,
                        "expected": "安全 SQL",
                        "detail": {},
                        "error": err,
                    }
                sql = threshold["custom_sql"]
            else:
                rule_obj = QualityRule(
                    rule_type=rule_type,
                    table_name=table_name,
                    field_name=column_name or field_name,
                    threshold=threshold,
                )
                sql = self.engine.generate_sql(rule_obj)

            # 2. 连接目标数据库并执行
            actual_value = self._execute_sql(sql)

            # 3. 比较
            passed = self._compare(actual_value, operator, threshold, rule_type)

            return {
                "passed": passed,
                "actual_value": actual_value,
                "expected": self._format_expected(operator, threshold, rule_type),
                "detail": {"sql": sql[:500]},
                "error": None,
            }
        except Exception as e:
            return {
                "passed": False,
                "actual_value": None,
                "expected": "N/A",
                "detail": {},
                "error": str(e),
            }

    def _execute_sql(self, sql: str) -> Optional[float]:
        """通过 sql_agent executor 执行 SQL"""
        from backend.services.sql_agent.executor import get_executor

        executor = get_executor(
            db_type=self.db_type,
            datasource_config=self.conn_info,
            timeout_seconds=60,
        )
        rows, _ = executor.execute(sql)
        if rows and len(rows) > 0:
            first_row = rows[0]
            # 取第一行第一个值（dict 或 tuple 格式）
            if isinstance(first_row, dict):
                value = list(first_row.values())[0]
            else:
                value = first_row[0]
            return float(value) if value is not None else None
        return None

    def _compare(
        self,
        actual: Optional[float],
        operator: str,
        threshold: dict,
        rule_type: str,
    ) -> bool:
        """比较实际值与阈值"""
        if actual is None:
            return False

        ops = {
            "eq": lambda a, b: a == b,
            "ne": lambda a, b: a != b,
            "gt": lambda a, b: a > b,
            "gte": lambda a, b: a >= b,
            "lt": lambda a, b: a < b,
            "lte": lambda a, b: a <= b,
            "between": lambda a, b: b[0] <= a <= b[1],
        }

        if rule_type in ["null_rate", "duplicate_rate"]:
            # 比率类：actual <= threshold
            threshold_val = threshold.get(
                "max_rate", threshold.get("max", 0)
            )
            return actual <= threshold_val
        elif operator == "between":
            return ops["between"](
                actual, (threshold.get("min", 0), threshold.get("max", float("inf")))
            )
        else:
            threshold_val = threshold.get(
                "threshold",
                threshold.get("max", threshold.get("min", 0)),
            )
            op_fn = ops.get(operator, ops["lte"])
            return op_fn(actual, threshold_val)

    def _format_expected(
        self, operator: str, threshold: dict, rule_type: str
    ) -> str:
        if rule_type in ["null_rate", "duplicate_rate"]:
            return f"<= {threshold.get('max_rate', threshold.get('max', 0))}"
        elif operator == "between":
            return f"[{threshold.get('min', 0)}, {threshold.get('max', '∞')}]"
        else:
            return (
                f"{operator} "
                f"{threshold.get('threshold', threshold.get('max', threshold.get('min', 'N/A')))}"
            )