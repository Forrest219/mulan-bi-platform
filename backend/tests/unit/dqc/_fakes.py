"""DQC 单元测试共用 fake 工具"""
from types import SimpleNamespace
from typing import Any, List


class FakeResult:
    """mock SQLAlchemy Result"""

    def __init__(self, rows: List[tuple]):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    """按调用顺序返回预置结果的假连接。"""

    def __init__(self, results: List[List[tuple]]):
        # results 每个元素是一个 fetchone/fetchall 可读取的行列表
        self._queue = list(results)
        self.executed_stmts: List[Any] = []

    def execute(self, stmt, *args, **kwargs):
        self.executed_stmts.append(stmt)
        if not self._queue:
            return FakeResult([])
        return FakeResult(self._queue.pop(0))

    def close(self):
        pass


def make_asset(**overrides):
    base = dict(
        id=1,
        datasource_id=1,
        schema_name="dws",
        table_name="dws_order_daily",
        display_name="订单日汇总表",
        description=None,
        dimension_weights={},
        signal_thresholds={},
        profile_json={},
        status="enabled",
        owner_id=1,
        created_by=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def make_rule(**overrides):
    base = dict(
        id=1,
        asset_id=1,
        name="test_rule",
        description=None,
        dimension="completeness",
        rule_type="null_rate",
        rule_config={},
        is_active=True,
        is_system_suggested=False,
        suggested_by_llm_analysis_id=None,
        created_by=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)
