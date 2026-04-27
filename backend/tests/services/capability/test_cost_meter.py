"""
单元测试：services/capability/cost_meter.py
覆盖：
- CostRecord 数据类
- CostMeter.record 日志记录
- CostMeter.aggregate_daily 返回结构
"""
from unittest import mock

import pytest

from services.capability.cost_meter import CostMeter, CostRecord


class TestCostRecord:
    """成本记录数据类"""

    def test_cost_record_defaults(self):
        rec = CostRecord(
            trace_id="abc123",
            principal_id=1,
            principal_role="analyst",
            capability="query_metric",
        )
        assert rec.input_tokens == 0
        assert rec.output_tokens == 0
        assert rec.latency_ms == 0
        assert rec.cached is False
        assert rec.error_code is None

    def test_cost_record_full(self):
        rec = CostRecord(
            trace_id="xyz",
            principal_id=42,
            principal_role="admin",
            capability="search_asset",
            input_tokens=500,
            output_tokens=100,
            latency_ms=1234,
            cached=True,
            error_code="CAP_005",
        )
        assert rec.input_tokens == 500
        assert rec.output_tokens == 100
        assert rec.latency_ms == 1234
        assert rec.cached is True


class TestCostMeterRecord:
    """成本记录 API"""

    def test_record_logs(self):
        meter = CostMeter()
        rec = CostRecord(
            trace_id="t1",
            principal_id=1,
            principal_role="analyst",
            capability="query_metric",
            latency_ms=150,
            cached=False,
        )

        with mock.patch("services.capability.cost_meter.logger") as mock_logger:
            meter.record(rec)
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0]
            assert "CostMeter" in call_args[0]
            assert "t1" in call_args[0]
            assert "query_metric" in call_args[0]

    def test_aggregate_daily_returns_dict(self):
        meter = CostMeter()
        result = meter.aggregate_daily()
        assert isinstance(result, dict)
