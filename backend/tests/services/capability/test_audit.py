"""
单元测试：services/capability/audit.py（P4 T5）

覆盖：
- write_audit 成功写入 Append-Only 记录
- 同一 trace_id 两条记录都写入（Append-Only，非 upsert）
- write_audit 内部异常不向上传播（fire-and-forget）
"""
import threading
from unittest import mock

import pytest

from services.capability.audit import (
    InvocationRecord,
    write_audit,
    new_trace_id,
    get_trace_id,
)


class TestAuditAppendOnly:
    """test_audit_append_only — 同一 trace_id 写两条记录，都成功（Append-Only）"""

    def test_same_trace_id_writes_two_rows(self):
        """Append-Only 语义：同 trace_id 不去重，两条记录都写入"""
        rec1 = InvocationRecord(
            trace_id="t1",
            principal_id=1,
            principal_role="analyst",
            capability="query_metric",
            status="ok",
        )
        rec2 = InvocationRecord(
            trace_id="t1",
            principal_id=1,
            principal_role="analyst",
            capability="query_metric",
            status="ok",
        )

        written: list = []

        def mock_execute(sql, params=None):
            written.append(params)

        mock_session = mock.Mock()
        mock_session.execute = mock_execute
        mock_session.commit = mock.Mock()
        mock_session.close = mock.Mock()

        with mock.patch(
            "services.capability.audit.SessionLocal",
            return_value=mock_session,
        ):
            write_audit(rec1)
            write_audit(rec2)

        assert len(written) == 2
        assert written[0]["trace_id"] == "t1"
        assert written[1]["trace_id"] == "t1"


class TestAuditFailureIsolation:
    """test_audit_failure_does_not_break_main_flow — write_audit 异常不向上传播"""

    def test_write_audit_swallows_exception(self):
        """审计写入失败不应影响主链路（fire-and-forget）"""
        rec = InvocationRecord(
            trace_id="t2",
            principal_id=1,
            principal_role="analyst",
            capability="query_metric",
            status="ok",
        )

        def failing_execute(sql, params=None):
            raise RuntimeError("DB connection failed")

        mock_session = mock.Mock()
        mock_session.execute = failing_execute

        with mock.patch(
            "services.capability.audit.SessionLocal",
            return_value=mock_session,
        ):
            # 不应抛出异常
            write_audit(rec)

    def test_audit_record_fields_correctly_bound(self):
        """InvocationRecord 所有字段正确传入 SQL"""
        rec = InvocationRecord(
            trace_id="abc123",
            principal_id=42,
            principal_role="data_admin",
            capability="query_metric",
            params_jsonb={"question_length": 10, "datasource_luid": "ds-1"},
            status="failed",
            error_code="NLQ_006",
            error_detail="MCP 调用失败",
            latency_ms=1234,
            mcp_call_id=999,
            llm_tokens_in=500,
            llm_tokens_out=100,
            redacted_fields=["salary", "bonus"],
        )

        bound_params: dict = {}

        def capture_execute(sql, params=None):
            bound_params.update(params)

        mock_session = mock.Mock()
        mock_session.execute = capture_execute
        mock_session.commit = mock.Mock()
        mock_session.close = mock.Mock()

        with mock.patch(
            "services.capability.audit.SessionLocal",
            return_value=mock_session,
        ):
            write_audit(rec)

        assert bound_params["trace_id"] == "abc123"
        assert bound_params["principal_id"] == 42
        assert bound_params["principal_role"] == "data_admin"
        assert bound_params["capability"] == "query_metric"
        assert bound_params["status"] == "failed"
        assert bound_params["error_code"] == "NLQ_006"
        assert bound_params["error_detail"] == "MCP 调用失败"
        assert bound_params["latency_ms"] == 1234
        assert bound_params["mcp_call_id"] == 999
        assert bound_params["llm_tokens_in"] == 500
        assert bound_params["llm_tokens_out"] == 100


class TestTraceIdContextvar:
    """test_trace_id_contextvar — trace_id 通过 contextvars 正确隔离"""

    def test_new_trace_id_sets_context(self):
        """new_trace_id() 生成并设置到 context"""
        tid = new_trace_id()
        assert tid is not None
        assert len(tid) == 16
        assert get_trace_id() == tid

    def test_trace_id_isolation_between_threads(self):
        """不同线程的 trace_id 互不干扰"""
        results: dict = {}

        def worker(thread_id):
            tid = new_trace_id()
            results[thread_id] = get_trace_id()

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results[1] != results[2]
        # Main thread's trace_id is unaffected
        assert get_trace_id() is None
