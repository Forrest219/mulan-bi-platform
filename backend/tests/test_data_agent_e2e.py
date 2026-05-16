"""
TC-E2E: Data Agent 端到端测试

覆盖从 API 端点 → Router → controlled_path (MCP Main) → SSE 响应 的完整链路。
使用 mock controlled_path 函数，验证事件流格式和数据完整性。
包括 Phase 3 可观测性（bi_agent_runs/steps/feedback）冒烟测试。

注意：自 2026-05-16 起，Data Agent 路由架构已变更：
- 低置信问题不再走 ReActEngine.run（mock 不触发）
- 新路由：router guardrail → controlled_path (run_mcp_first_main_path)
- 测试 patch 目标改为 services.data_agent.runner.run_mcp_first_main_path
- 测试固定 DATA_AGENT_CHAIN_MODE=legacy_queryspec，避免环境变量切到 MCP proxy
"""

import json
import uuid
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user


def _mock_user():
    return {"id": 1, "username": "test", "role": "analyst"}


@pytest.fixture(autouse=True)
def _force_legacy_controlled_chain(monkeypatch):
    """Keep E2E mocks on run_mcp_first_main_path regardless of local env."""
    monkeypatch.setenv("DATA_AGENT_CHAIN_MODE", "legacy_queryspec")
    monkeypatch.delenv("DATA_AGENT_MCP_PROXY_ENABLED", raising=False)


# ---------------------------------------------------------------------------
# TestDataAgentE2E: API → controlled_path → SSE 事件流
# ---------------------------------------------------------------------------
class TestDataAgentE2E:
    """端到端测试：API → Router → controlled_path → SSE 事件流"""

    def _parse_sse_events(self, response) -> list:
        """从 SSE 响应中解析事件列表"""
        events = []
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        return events

    def test_e2e_stream_direct_answer(self):
        """TC-E2E-001: 直接回答 → metadata + thinking + done"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="thinking", content="这是一个简单问候")
            yield AgentEvent(type="answer", content="你好！我是 Data Agent。")

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额是多少"},
                )
                assert resp.status_code == 200

                events = self._parse_sse_events(resp)
                event_types = [e["type"] for e in events]

                assert "metadata" in event_types
                # token 事件由 done 事件序列化时逐字发出，解析后看不到独立 token type
                assert "done" in event_types

                metadata_event = next(e for e in events if e["type"] == "metadata")
                assert "conversation_id" in metadata_event

                done_event = next(e for e in events if e["type"] == "done")
                assert "answer" in done_event
                assert "trace_id" in done_event
                assert "你好" in done_event["answer"]
        finally:
            app.dependency_overrides.clear()

    def test_e2e_stream_with_tool_call(self):
        """TC-E2E-002: 工具调用 → metadata + thinking + tool_call + tool_result + done"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="thinking", content="需要查询数据")
            yield AgentEvent(
                type="tool_call",
                content={"tool": "query", "params": {"sql": "SELECT 1"}},
            )
            yield AgentEvent(
                type="tool_result",
                content={
                    "tool": "query",
                    "result": {"data": {"rows": [{"v": 1}], "fields": ["v"]}},
                },
            )
            yield AgentEvent(type="answer", content="查询结果为 1。")

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "Q4销售额"},
                )
                assert resp.status_code == 200

                events = self._parse_sse_events(resp)
                event_types = [e["type"] for e in events]

                assert "metadata" in event_types
                assert "thinking" in event_types
                assert "tool_call" in event_types
                assert "tool_result" in event_types
                assert "done" in event_types

                tool_call_event = next(e for e in events if e["type"] == "tool_call")
                assert tool_call_event["tool"] == "query"

                done_event = next(e for e in events if e["type"] == "done")
                assert done_event["response_type"] == "table"
                assert "execution_time_ms" in done_event
        finally:
            app.dependency_overrides.clear()

    def test_e2e_stream_error_handling(self):
        """TC-E2E-003: 引擎错误 → metadata + thinking + error 事件"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="thinking", content="准备执行...")
            yield AgentEvent(
                type="error",
                content={
                    "error_code": "AGENT_001",
                    "message": "Agent 执行超时",
                },
            )

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额异常场景"},
                )
                assert resp.status_code == 200

                events = self._parse_sse_events(resp)
                error_events = [e for e in events if e["type"] == "error"]
                assert len(error_events) >= 1
                assert error_events[0]["error_code"] == "AGENT_001"
        finally:
            app.dependency_overrides.clear()

    def test_e2e_conversation_lifecycle(self):
        """TC-E2E-004: 会话全生命周期 — 创建 → 列表 → 消息查询 → 归档"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="answer", content="测试回答")

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)

                # Step 1: 创建会话（通过 stream）
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额测试问题"},
                )
                assert resp.status_code == 200
                events = self._parse_sse_events(resp)
                metadata = next(
                    (e for e in events if e["type"] == "metadata"), None
                )
                assert metadata is not None
                conversation_id = metadata["conversation_id"]
                assert conversation_id

                # Step 2: 列出会话
                resp = client.get("/api/agent/conversations")
                assert resp.status_code == 200
                convs = resp.json()
                assert isinstance(convs, list)
                conv_ids = [c["id"] for c in convs]
                assert conversation_id in conv_ids

                # Step 3: 获取消息
                resp = client.get(
                    f"/api/agent/conversations/{conversation_id}/messages"
                )
                assert resp.status_code == 200
                msgs = resp.json()
                assert isinstance(msgs, list)
                assert len(msgs) >= 2  # user + assistant
                roles = [m["role"] for m in msgs]
                assert "user" in roles
                assert "assistant" in roles

                # Step 4: 归档会话
                resp = client.delete(
                    f"/api/agent/conversations/{conversation_id}"
                )
                assert resp.status_code == 200
                assert resp.json()["status"] == "archived"

                # Step 5: 归档后不在 active 列表
                resp = client.get("/api/agent/conversations")
                assert resp.status_code == 200
                active_ids = [c["id"] for c in resp.json()]
                assert conversation_id not in active_ids
        finally:
            app.dependency_overrides.clear()

    def test_e2e_sse_event_format_compliance(self):
        """TC-E2E-005: SSE 事件格式验证 — 所有事件符合 Spec 36 §5.2"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="thinking", content="分析中")
            yield AgentEvent(
                type="tool_call",
                content={"tool": "schema", "params": {"table_name": "t"}},
            )
            yield AgentEvent(
                type="tool_result",
                content={"tool": "schema", "result": {"data": {"tables": []}}},
            )
            yield AgentEvent(type="answer", content="没有找到表。")

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额有哪些表"},
                )
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")

                events = self._parse_sse_events(resp)
                for event in events:
                    assert "type" in event, f"event missing 'type': {event}"

                done_events = [e for e in events if e["type"] == "done"]
                assert len(done_events) == 1
                done = done_events[0]
                required_fields = ["answer", "trace_id", "tools_used", "response_type", "steps_count", "execution_time_ms"]
                for field in required_fields:
                    assert field in done, f"done event missing '{field}'"
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestObservabilitySmoke: bi_agent_runs / bi_agent_steps / bi_agent_feedback
# ---------------------------------------------------------------------------
class TestObservabilitySmoke:
    """Phase 3 可观测性冒烟测试：bi_agent_runs / bi_agent_steps / bi_agent_feedback"""

    def _parse_sse_events(self, response) -> list:
        events = []
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        return events

    def test_run_id_in_sse_events(self):
        """TC-OBS-001: metadata 和 done 事件都包含 run_id"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="answer", content="测试回答")

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额测试"},
                )
                assert resp.status_code == 200

                events = self._parse_sse_events(resp)

                metadata = next((e for e in events if e["type"] == "metadata"), None)
                assert metadata is not None
                assert "run_id" in metadata
                assert metadata["run_id"]  # non-empty

                done = next((e for e in events if e["type"] == "done"), None)
                assert done is not None
                assert "run_id" in done
                assert done["run_id"] == metadata["run_id"]
        finally:
            app.dependency_overrides.clear()

    def test_agent_run_record_created(self):
        """TC-OBS-002: 流结束后 bi_agent_runs 表有 completed 记录"""
        from app.main import app
        from services.data_agent.models import BiAgentRun

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="thinking", content="分析中")
            yield AgentEvent(type="answer", content="回答")

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额测试观测"},
                )
                assert resp.status_code == 200

                events = self._parse_sse_events(resp)
                run_id = next(e for e in events if e["type"] == "metadata")["run_id"]

                db = next(get_db())
                try:
                    run = db.query(BiAgentRun).filter(
                        BiAgentRun.id == run_id
                    ).first()
                    assert run is not None
                    assert run.status == "completed"
                    assert run.question == "查询销售额测试观测"
                    assert run.execution_time_ms is not None
                    assert run.completed_at is not None
                finally:
                    db.close()
        finally:
            app.dependency_overrides.clear()

    def test_agent_step_records_created(self):
        """TC-OBS-003: 完整 MCP Main 链路产生预期步骤"""
        from app.main import app
        from services.data_agent.models import BiAgentRun, BiAgentStep

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            # 模拟 controlled_path 发出的完整步骤序列
            yield AgentEvent(type="thinking", content="思考中")
            yield AgentEvent(type="tool_call", content={"tool": "context_resolver", "params": {}})
            yield AgentEvent(type="tool_result", content={"tool": "context_resolver", "result": {}})
            yield AgentEvent(
                type="tool_call",
                content={"tool": "queryspec_fallback", "params": {"reason": "semantic_operator_preflight"}},
            )
            yield AgentEvent(
                type="tool_result",
                content={"tool": "queryspec_fallback", "result": {"event": "fallback_triggered", "data": {}}},
            )
            yield AgentEvent(type="answer", content="完成")

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额步骤测试"},
                )
                assert resp.status_code == 200

                events = self._parse_sse_events(resp)
                run_id = next(e for e in events if e["type"] == "metadata")["run_id"]

                db = next(get_db())
                try:
                    steps = db.query(BiAgentStep).filter(
                        BiAgentStep.run_id == run_id
                    ).order_by(BiAgentStep.step_number).all()

                    # mock 发出了 6 个事件：thinking(1) + context_resolver(2,3) + queriespec_fallback(4,5) + answer(6)
                    # 外加 intent_classifier thinking(step 0 via run_agent)
                    assert len(steps) == 7
                    step_types = [s.step_type for s in steps]
                    assert "thinking" in step_types
                    assert "tool_call" in step_types
                    assert "tool_result" in step_types
                    assert "answer" in step_types
                finally:
                    db.close()
        finally:
            app.dependency_overrides.clear()

    def test_error_run_marked_failed(self):
        """TC-OBS-004: 引擎 error 事件 → run.status = 'failed'"""
        from app.main import app
        from services.data_agent.models import BiAgentRun

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="thinking", content="准备执行...")
            yield AgentEvent(
                type="error",
                content={"error_code": "AGENT_001", "message": "超时"},
            )

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额会失败"},
                )
                assert resp.status_code == 200

                events = self._parse_sse_events(resp)
                run_id = next(e for e in events if e["type"] == "metadata")["run_id"]

                db = next(get_db())
                try:
                    run = db.query(BiAgentRun).filter(BiAgentRun.id == run_id).first()
                    assert run is not None
                    assert run.status == "failed"
                    assert run.error_code == "AGENT_001"
                finally:
                    db.close()
        finally:
            app.dependency_overrides.clear()

    def test_feedback_create_and_update(self):
        """TC-OBS-005: 提交反馈 → created，再次提交 → updated"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user

        async def mock_path(*args, **kwargs):
            from services.data_agent.response import AgentEvent

            yield AgentEvent(type="answer", content="好的")

        try:
            with patch("services.data_agent.runner.run_mcp_first_main_path", mock_path):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "查询销售额反馈测试"},
                )
                events = self._parse_sse_events(resp)
                run_id = next(e for e in events if e["type"] == "metadata")["run_id"]

            # 提交反馈 — 首次创建
            resp = client.post(
                "/api/agent/feedback",
                json={"run_id": run_id, "rating": "up", "comment": "很好"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "created"
            assert "feedback_id" in body

            # 再次提交 — 更新
            resp = client.post(
                "/api/agent/feedback",
                json={"run_id": run_id, "rating": "down", "comment": "改主意了"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "updated"
        finally:
            app.dependency_overrides.clear()

    def test_feedback_invalid_run_id(self):
        """TC-OBS-006: 无效 run_id 返回 400"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/agent/feedback",
                json={"run_id": "not-a-uuid", "rating": "up"},
            )
            assert resp.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_feedback_run_not_found(self):
        """TC-OBS-007: run 不存在返回 404"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/agent/feedback",
                json={"run_id": str(uuid.uuid4()), "rating": "up"},
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_feedback_invalid_rating(self):
        """TC-OBS-008: rating 非 up/down 返回 422"""
        from app.main import app

        app.dependency_overrides[get_current_user] = _mock_user
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/agent/feedback",
                json={"run_id": str(uuid.uuid4()), "rating": "meh"},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_feedback_requires_auth(self):
        """TC-OBS-009: 未认证返回 401"""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/agent/feedback",
            json={"run_id": str(uuid.uuid4()), "rating": "up"},
        )
        assert resp.status_code in (401, 403)
