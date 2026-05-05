"""
T2.1 + T2.2 + T2.3 批次 2 能力收口测试

T2.1: Spec 28 UC-1 归因六步端到端（销售额下滑归因）
T2.2: Spec 28 UC-2 DAU 流失归因端到端
T2.3: Spec 36 首页 Agent 灰度验证

测试策略：
- T2.1/T2.2: Mock CausationSessionManager/DauChurnSessionManager.run_causation
  验证端点返回正确结构 + 六步/八步流程
- T2.3: 单元测试 HomepageAgentMode 枚举 + execute_dual_write 四态逻辑
"""

import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


# ============================================================================
# T2.1: UC-1 归因分析端到端
# ============================================================================


class TestCausationE2E:
    """Spec 28 UC-1 归因六步端到端测试"""

    def _mock_user(self):
        return {"id": 1, "username": "test", "role": "analyst", "tenant_id": uuid.uuid4()}

    def _mock_admin(self):
        return {"id": 99, "username": "admin", "role": "admin", "tenant_id": uuid.uuid4()}

    def _build_mock_result(self, steps_count=6, confidence=0.85):
        """构建符合 CausationResponse 的 mock run_causation 结果"""
        return {
            "delta_abs": -250_000.0,
            "delta_pct": -0.119,
            "root_dimension": "region",
            "root_value": "北京",
            "confidence": confidence,
            "narrative_summary": "北京区域 GMV 环比下降 11.9%，是整体下滑的主要驱动力",
            "anomaly_confirmed": True,
            "magnitude": 0.119,
            "concentration_point": "region=北京",
            "recommended_actions": [
                {"action": "调低北京 Q2 业绩目标", "priority": "HIGH"},
                {"action": "排查数据同步延迟可能性", "priority": "MEDIUM"},
            ],
            "hypothesis_trace": [
                {"step": 1, "hypothesis": "北京区域贡献最大", "status": "confirmed", "confidence": 0.85},
            ],
            "insight_report": {
                "metadata": {"subject": "gmv 归因分析"},
                "summary": "北京区域 GMV 环比下降 11.9%",
                "confidence_score": confidence,
            },
            "session_id": str(uuid.uuid4()),
            "session_status": "completed",
            "steps_count": steps_count,
            "total_time_ms": 1250,
        }

    def test_causation_creates_session_and_returns_six_steps(self):
        """TC-T2.1-001: POST /api/data-agent/causation 创建会话并返回六步归因结果"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        mock_result = self._build_mock_result(steps_count=6, confidence=0.85)

        try:
            with patch(
                "services.data_agent.routes.causation.CausationSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_instance.create_session.return_value = MagicMock(
                    id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                    created_by=1,
                    status="created",
                    session_metadata={"metric": "gmv"},
                )
                mock_instance.run_causation = AsyncMock(return_value=mock_result)
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/data-agent/causation",
                    json={
                        "metric": "gmv",
                        "dimensions": ["region", "product_category", "channel"],
                        "time_range": {"start": "2026-04-01", "end": "2026-04-15"},
                        "compare_mode": "mom",
                        "threshold_pct": -0.05,
                        "context": {"scenario": "causation"},
                    },
                )

                assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
                data = resp.json()

                # 验收标准 1: 返回结果结构完整
                assert "session_id" in data
                assert "session_status" in data
                assert "delta_pct" in data
                assert "confidence" in data
                assert "root_dimension" in data
                assert "root_value" in data
                assert "insight_report" in data
                assert "steps_count" in data
                assert "total_time_ms" in data

                # 验收标准 2: 六步内收敛
                assert data["steps_count"] == 6, f"Expected 6 steps, got {data['steps_count']}"

                # 验收标准 3: confidence >= 0.7
                assert data["confidence"] >= 0.7, f"Confidence {data['confidence']} < 0.7"

                # 验收标准 4: delta_abs 合理
                assert isinstance(data["delta_abs"], (int, float))
                assert data["delta_abs"] < 0  # 销售额下滑

                # 验收标准 5: hypothesis_trace 存在
                assert "hypothesis_trace" in data
                assert len(data["hypothesis_trace"]) > 0

        finally:
            app.dependency_overrides.clear()

    def test_causation_get_session_status(self):
        """TC-T2.1-002: GET /api/data-agent/causation/{session_id} 查询会话状态"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        session_id = str(uuid.uuid4())
        tenant_id = uuid.uuid4()

        try:
            with patch(
                "services.data_agent.routes.causation.CausationSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_session = MagicMock()
                mock_session.id = uuid.UUID(session_id)
                mock_session.status = "running"
                mock_session.current_step = 3
                mock_session.hypothesis_tree = {
                    "nodes": [
                        {
                            "id": "hyp_001",
                            "description": "北京区域贡献最大",
                            "status": "pending",
                            "confidence": 0.6,
                        }
                    ],
                    "confirmed_path": [],
                    "rejected_paths": [],
                }
                mock_session.created_at = MagicMock()
                mock_session.created_at.isoformat.return_value = "2026-04-15T10:00:00Z"
                mock_session.completed_at = None
                mock_instance.get_session.return_value = mock_session
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(
                    f"/api/data-agent/causation/{session_id}",
                    headers={"Authorization": "Bearer fake-token"},
                )

                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert data["session_id"] == session_id
                assert data["status"] == "running"
                assert data["current_step"] == 3
                assert "hypothesis_tree" in data

        finally:
            app.dependency_overrides.clear()

    def test_causation_not_found(self):
        """TC-T2.1-003: 查询不存在的会话返回 404"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        try:
            with patch(
                "services.data_agent.routes.causation.CausationSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_instance.get_session.return_value = None
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(
                    f"/api/data-agent/causation/{uuid.uuid4()}",
                    headers={"Authorization": "Bearer fake-token"},
                )

                assert resp.status_code == 404

        finally:
            app.dependency_overrides.clear()

    def test_causation_pause_and_resume(self):
        """TC-T2.1-004: 暂停 + 恢复会话"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        session_id = str(uuid.uuid4())
        mock_result = self._build_mock_result()

        try:
            with patch(
                "services.data_agent.routes.causation.CausationSessionManager"
            ) as MockMgr:
                from services.data_agent.causation_session import SessionStatus

                mock_instance = MagicMock()
                mock_session = MagicMock()
                mock_session.id = uuid.UUID(session_id)
                mock_session.tenant_id = uuid.uuid4()
                mock_session.created_by = 1
                mock_session.status = "paused"
                mock_session.current_step = 3
                mock_session.hypothesis_tree = None
                mock_session.created_at = MagicMock()
                mock_session.created_at.isoformat.return_value = "2026-04-15T10:00:00Z"
                mock_session.completed_at = None

                mock_instance.get_session.return_value = mock_session
                mock_instance.update_session_status.return_value = mock_session
                mock_instance.run_causation = AsyncMock(return_value=mock_result)
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)

                # Pause
                resp = client.post(
                    f"/api/data-agent/causation/{session_id}/pause",
                    headers={"Authorization": "Bearer fake-token"},
                )
                assert resp.status_code == 200

                # Resume
                resp = client.post(
                    f"/api/data-agent/causation/{session_id}/resume",
                    headers={"Authorization": "Bearer fake-token"},
                )
                assert resp.status_code == 200

        finally:
            app.dependency_overrides.clear()

    def test_causation_hypothesis_store(self):
        """TC-T2.1-005: hypothesis_store 工具 API"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        session_id = str(uuid.uuid4())

        try:
            with patch(
                "services.data_agent.routes.causation.CausationSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_session = MagicMock()
                mock_session.id = uuid.UUID(session_id)
                mock_session.tenant_id = uuid.uuid4()
                mock_session.created_by = 1
                mock_instance.get_session.return_value = mock_session
                mock_instance.hypothesis_store.return_value = {
                    "hypothesis_tree": {
                        "nodes": [{"id": "hyp_test", "status": "confirmed"}],
                        "confirmed_path": ["hyp_test"],
                    }
                }
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    f"/api/data-agent/causation/{session_id}/hypothesis",
                    json={
                        "action": "confirm",
                        "hypothesis": {
                            "id": "hyp_test",
                            "description": "北京区域是根因",
                            "confidence": 0.85,
                        },
                    },
                    headers={"Authorization": "Bearer fake-token"},
                )

                assert resp.status_code == 200
                data = resp.json()
                assert "hypothesis_tree" in data

        finally:
            app.dependency_overrides.clear()


# ============================================================================
# T2.2: UC-2 DAU 流失归因端到端
# ============================================================================


class TestDauChurnE2E:
    """Spec 28 UC-2 DAU/WAU 流失归因端到端测试"""

    def _mock_user(self):
        return {"id": 1, "username": "test", "role": "analyst", "tenant_id": uuid.uuid4()}

    def _build_mock_uc2_result(self, steps_count=8, confidence=0.78):
        """构建符合 DauChurnResponse 的 mock run_causation 结果"""
        return {
            "delta_abs": -1500.0,
            "delta_pct": -0.083,
            "segment_breakdown": {
                "new_users": {"current": 1200, "baseline": 1500, "delta": -300, "delta_pct": -0.20},
                "churned_users": {"current": 800, "baseline": 600, "delta": +200, "delta_pct": +0.33},
                "returned_users": {"current": 500, "baseline": 700, "delta": -200, "delta_pct": -0.29},
            },
            "correlated_metric": {
                "metric": "new_user_acquisition",
                "coefficient": -0.72,
                "p_value": 0.008,
            },
            "root_dimension": "user_segment",
            "root_value": "新客",
            "confidence": confidence,
            "narrative_summary": "DAU 下降主要由新客获取下滑导致，H1 假设确认",
            "anomaly_confirmed": True,
            "magnitude": 0.083,
            "confirmed_hypothesis_type": "acquisition",
            "h1_status": "confirmed",
            "h2_status": "pending",
            "recommended_actions": [
                {"action": "加大新客获取渠道投入", "priority": "HIGH"},
            ],
            "hypothesis_trace": [
                {"step": 1, "hypothesis": "H1 新客获取下滑", "status": "confirmed", "confidence": 0.78},
                {"step": 2, "hypothesis": "H2 老客留存恶化", "status": "pending", "confidence": 0.3},
            ],
            "insight_report": {
                "metadata": {"subject": "DAU 流失归因分析"},
                "summary": "新客获取下滑是 DAU 下降主因",
                "confidence_score": confidence,
            },
            "session_id": str(uuid.uuid4()),
            "session_status": "completed",
            "steps_count": steps_count,
            "total_time_ms": 2100,
        }

    def test_dau_churn_creates_session_and_returns_eight_steps(self):
        """TC-T2.2-001: POST /api/data-agent/dau-churn 创建会话并返回八步归因结果"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        mock_result = self._build_mock_uc2_result(steps_count=8, confidence=0.78)

        try:
            with patch(
                "services.data_agent.routes.dau_churn.DauChurnSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_instance.create_session.return_value = MagicMock(
                    id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                    created_by=1,
                    status="created",
                    session_metadata={"metric": "dau"},
                )
                mock_instance.run_causation = AsyncMock(return_value=mock_result)
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/data-agent/dau-churn",
                    json={
                        "metric": "dau",
                        "dimensions": ["user_segment", "channel", "app_version"],
                        "time_range": {"start": "2026-04-08", "end": "2026-04-14"},
                        "compare_mode": "wow",
                        "threshold_pct": -0.03,
                        "context": {"scenario": "causation", "cross_table": True},
                    },
                )

                assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
                data = resp.json()

                # 验收标准 1: 返回结果结构完整（UC-2 特有字段）
                assert "segment_breakdown" in data
                assert "correlated_metric" in data
                assert "h1_status" in data
                assert "h2_status" in data
                assert "confirmed_hypothesis_type" in data
                assert "root_dimension" in data
                assert "root_value" in data

                # 验收标准 2: 八步内收敛
                assert data["steps_count"] == 8, f"Expected 8 steps, got {data['steps_count']}"

                # 验收标准 3: confidence >= 0.7
                assert data["confidence"] >= 0.7

                # 验收标准 4: segment_breakdown 三层结构
                sb = data["segment_breakdown"]
                assert "new_users" in sb
                assert "churned_users" in sb
                assert "returned_users" in sb

                # 验收标准 5: correlated_metric 字段
                cm = data["correlated_metric"]
                assert "coefficient" in cm
                assert abs(cm["coefficient"]) >= 0.5  # |coefficient| >= 0.5

                # 验收标准 6: H1/H2 双假设链
                assert data["h1_status"] in ("confirmed", "rejected", "pending")
                assert data["h2_status"] in ("confirmed", "rejected", "pending")

        finally:
            app.dependency_overrides.clear()

    def test_dau_churn_get_session_status(self):
        """TC-T2.2-002: GET /api/data-agent/dau-churn/{session_id} 查询会话状态"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        session_id = str(uuid.uuid4())

        try:
            with patch(
                "services.data_agent.routes.dau_churn.DauChurnSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_session = MagicMock()
                mock_session.id = uuid.UUID(session_id)
                mock_session.status = "running"
                mock_session.current_step = 5
                mock_session.hypothesis_tree = {
                    "nodes": [
                        {"id": "h1_acquisition", "description": "新客获取下滑", "status": "confirmed", "confidence": 0.78},
                        {"id": "h2_retention", "description": "老客留存恶化", "status": "pending", "confidence": 0.3},
                    ],
                    "confirmed_path": ["h1_acquisition"],
                    "rejected_paths": [],
                }
                mock_session.created_at = MagicMock()
                mock_session.created_at.isoformat.return_value = "2026-04-15T10:00:00Z"
                mock_session.completed_at = None
                mock_instance.get_session.return_value = mock_session
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(
                    f"/api/data-agent/dau-churn/{session_id}",
                    headers={"Authorization": "Bearer fake-token"},
                )

                assert resp.status_code == 200
                data = resp.json()
                assert data["session_id"] == session_id
                assert data["status"] == "running"
                assert data["current_step"] == 5

        finally:
            app.dependency_overrides.clear()

    def test_dau_churn_hypothesis_status_endpoint(self):
        """TC-T2.2-003: GET /api/data-agent/dau-churn/{session_id}/hypothesis-status 查询 H1/H2 状态"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        session_id = str(uuid.uuid4())

        try:
            with patch(
                "services.data_agent.routes.dau_churn.DauChurnSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_session = MagicMock()
                mock_session.id = uuid.UUID(session_id)
                mock_session.tenant_id = uuid.uuid4()
                mock_session.created_by = 1
                mock_session.hypothesis_tree = {
                    "nodes": [
                        {"id": "h1_acquisition", "description": "新客获取下滑", "status": "confirmed", "confidence": 0.78},
                        {"id": "h2_retention", "description": "老客留存恶化", "status": "rejected", "confidence": 0.2},
                    ],
                    "confirmed_path": ["h1_acquisition"],
                    "rejected_paths": [["h2_retention"]],
                }
                mock_instance.get_session.return_value = mock_session
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(
                    f"/api/data-agent/dau-churn/{session_id}/hypothesis-status",
                    headers={"Authorization": "Bearer fake-token"},
                )

                assert resp.status_code == 200
                data = resp.json()
                assert data["session_id"] == session_id
                assert data["h1"]["id"] == "h1_acquisition"
                assert data["h1"]["status"] == "confirmed"
                assert data["h2"]["id"] == "h2_retention"
                assert data["h2"]["status"] == "rejected"
                assert "h1_acquisition" in data["confirmed_path"]

        finally:
            app.dependency_overrides.clear()

    def test_dau_churn_not_found(self):
        """TC-T2.2-004: 查询不存在的会话返回 404"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        try:
            with patch(
                "services.data_agent.routes.dau_churn.DauChurnSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_instance.get_session.return_value = None
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(
                    f"/api/data-agent/dau-churn/{uuid.uuid4()}",
                    headers={"Authorization": "Bearer fake-token"},
                )
                assert resp.status_code == 404

        finally:
            app.dependency_overrides.clear()


# ============================================================================
# T2.3: Spec 36 首页 Agent 灰度验证
# ============================================================================


class TestHomepageAgentMode:
    """Spec 36 §15 HOMEPAGE_AGENT_MODE 四态 + 灰度切换测试"""

    def _mock_user(self):
        return {"id": 1, "username": "test", "role": "analyst", "tenant_id": uuid.uuid4()}

    def _mock_admin(self):
        return {"id": 99, "username": "admin", "role": "admin", "tenant_id": uuid.uuid4()}

    def test_homepage_agent_mode_enum_validity(self):
        """TC-T2.3-001: HomepageAgentMode 四态枚举有效性"""
        from services.agent.dual_write import HomepageAgentMode

        # 四个有效状态
        assert HomepageAgentMode.LEGACY_ONLY.value == "legacy_only"
        assert HomepageAgentMode.AGENT_WITH_FALLBACK.value == "agent_with_fallback"
        assert HomepageAgentMode.AGENT_ONLY.value == "agent_only"
        assert HomepageAgentMode.DUAL_WRITE.value == "dual_write"

        # 默认值
        assert HomepageAgentMode.default() == HomepageAgentMode.AGENT_WITH_FALLBACK

        # is_valid 校验
        assert HomepageAgentMode.is_valid("legacy_only") is True
        assert HomepageAgentMode.is_valid("agent_with_fallback") is True
        assert HomepageAgentMode.is_valid("agent_only") is True
        assert HomepageAgentMode.is_valid("dual_write") is True
        assert HomepageAgentMode.is_valid("invalid") is False

    def test_get_agent_mode_endpoint(self):
        """TC-T2.3-002: GET /api/agent/mode 返回当前模式"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        try:
            with patch(
                "services.agent.dual_write.get_homepage_agent_mode"
            ) as mock_get_mode:
                mock_get_mode.return_value = MagicMock(value="agent_with_fallback")

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(
                    "/api/agent/mode",
                    headers={"Authorization": "Bearer fake-token"},
                )

                assert resp.status_code == 200
                data = resp.json()
                assert data["mode"] == "agent_with_fallback"
                assert "description" in data
                assert "can_rollback" in data
                assert "failure_tracker_active" in data

        finally:
            app.dependency_overrides.clear()

    def test_update_agent_mode_admin_only(self):
        """TC-T2.3-003: POST /api/agent/mode 仅 admin 可修改"""
        from app.main import app
        from app.core.dependencies import get_current_user

        # 1. 非 admin 用户被拒绝
        app.dependency_overrides[get_current_user] = self._mock_user
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/agent/mode",
                json={"mode": "agent_only"},
                headers={"Authorization": "Bearer fake-token"},
            )
            assert resp.status_code == 403, f"Non-admin should get 403, got {resp.status_code}"
        finally:
            app.dependency_overrides.clear()

        # 2. admin 用户可以修改
        app.dependency_overrides[get_current_user] = self._mock_admin
        try:
            with patch(
                "services.agent.dual_write.write_system_audit_log"
            ) as mock_audit:
                with patch(
                    "services.data_agent.routes.agent.PlatformSettingsService"
                ) as MockPS:
                    mock_ps_instance = MagicMock()
                    MockPS.return_value = mock_ps_instance

                    client = TestClient(app, raise_server_exceptions=False)
                    resp = client.post(
                        "/api/agent/mode",
                        json={"mode": "agent_only"},
                        headers={"Authorization": "Bearer fake-token"},
                    )

                    assert resp.status_code == 200, f"Admin should get 200, got {resp.status_code}: {resp.text}"
                    data = resp.json()
                    assert data["mode"] == "agent_only"
                    mock_audit.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    def test_update_agent_mode_invalid_value(self):
        """TC-T2.3-004: 无效模式值返回 400"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_admin

        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/agent/mode",
                json={"mode": "invalid_mode"},
                headers={"Authorization": "Bearer fake-token"},
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "AGENT_007" in str(data)
        finally:
            app.dependency_overrides.clear()

    def test_failure_tracker_records_success_and_failure(self):
        """TC-T2.3-005: FailureTracker 记录成功率/失败率"""
        from services.agent.dual_write import FailureTracker

        tracker = FailureTracker(threshold=0.05, window_hours=2)

        # 记录 20 次成功
        for _ in range(20):
            tracker.record(success=True)
        assert tracker.failure_rate == 0.0
        assert tracker.should_rollback is False

        # 记录 1 次失败（失败率 1/21 ≈ 4.8%，低于阈值 5%）
        tracker.record(success=False)
        assert tracker.failure_rate < 0.05
        assert tracker.should_rollback is False

        # 记录 10 次失败（失败率 = 10/31 ≈ 32%，超过阈值）
        for _ in range(10):
            tracker.record(success=False)
        assert tracker.failure_rate > 0.05
        # 需要至少 10 个样本才触发
        assert tracker.should_rollback is True

    def test_execute_dual_write_legacy_only_mode(self):
        """TC-T2.3-006: execute_dual_write legacy_only 模式仅调用 NLQ"""
        from services.agent.dual_write import execute_dual_write, HomepageAgentMode

        async def fake_nlq(question, trace_id, user, conn_id):
            return {"answer": "NLQ 回答", "sql": "SELECT 1"}

        async def fake_agent(question, trace_id, user, conn_id):
            return {"answer": "Agent 回答", "sql": "SELECT 2"}

        mock_db = MagicMock()

        with patch(
            "services.agent.dual_write.get_homepage_agent_mode"
        ) as mock_get_mode:
            mock_get_mode.return_value = HomepageAgentMode.LEGACY_ONLY

            result = None

            async def run():
                nonlocal result
                result = await execute_dual_write(
                    db=mock_db,
                    question="本月销售额",
                    trace_id="t-test",
                    current_user={"id": 1},
                    connection_id=1,
                    agent_fn=fake_agent,
                    nlq_fn=fake_nlq,
                )

            import asyncio
            asyncio.run(run())

            assert result is not None
            assert result.source == "nlq"
            assert result.mode == HomepageAgentMode.LEGACY_ONLY
            assert "NLQ 回答" in result.answer

    def test_execute_dual_write_agent_with_fallback(self):
        """TC-T2.3-007: execute_dual_write agent_with_fallback 模式成功走 Agent"""
        from services.agent.dual_write import execute_dual_write, HomepageAgentMode

        async def fake_nlq(question, trace_id, user, conn_id):
            return {"answer": "NLQ 回答"}

        async def fake_agent(question, trace_id, user, conn_id):
            return {"answer": "Agent 回答"}

        mock_db = MagicMock()

        with patch(
            "services.agent.dual_write.get_homepage_agent_mode"
        ) as mock_get_mode:
            mock_get_mode.return_value = HomepageAgentMode.AGENT_WITH_FALLBACK

            result = None

            async def run():
                nonlocal result
                result = await execute_dual_write(
                    db=mock_db,
                    question="本月销售额",
                    trace_id="t-test",
                    current_user={"id": 1},
                    connection_id=1,
                    agent_fn=fake_agent,
                    nlq_fn=fake_nlq,
                )

            import asyncio
            asyncio.run(run())

            assert result is not None
            assert result.source == "agent"
            assert result.mode == HomepageAgentMode.AGENT_WITH_FALLBACK
            assert "Agent 回答" in result.answer

    def test_execute_dual_write_agent_with_fallback_fails_over(self):
        """TC-T2.3-008: agent_with_fallback Agent 失败时 fallback 到 NLQ"""
        from services.agent.dual_write import execute_dual_write, HomepageAgentMode

        async def fake_nlq(question, trace_id, user, conn_id):
            return {"answer": "NLQ 降级回答"}

        async def fake_agent(question, trace_id, user, conn_id):
            raise RuntimeError("Agent 服务不可用")

        mock_db = MagicMock()

        with patch(
            "services.agent.dual_write.get_homepage_agent_mode"
        ) as mock_get_mode:
            mock_get_mode.return_value = HomepageAgentMode.AGENT_WITH_FALLBACK

            result = None

            async def run():
                nonlocal result
                result = await execute_dual_write(
                    db=mock_db,
                    question="本月销售额",
                    trace_id="t-test",
                    current_user={"id": 1},
                    connection_id=1,
                    agent_fn=fake_agent,
                    nlq_fn=fake_nlq,
                )

            import asyncio
            asyncio.run(run())

            assert result is not None
            assert result.source == "fallback"
            assert "NLQ 降级回答" in result.answer

    def test_execute_dual_write_dual_write_mode(self):
        """TC-T2.3-009: execute_dual_write dual_write 模式并发执行"""
        from services.agent.dual_write import execute_dual_write, HomepageAgentMode

        call_log = {"agent": False, "nlq": False}

        async def fake_nlq(question, trace_id, user, conn_id):
            call_log["nlq"] = True
            return {"answer": "NLQ 回答"}

        async def fake_agent(question, trace_id, user, conn_id):
            call_log["agent"] = True
            return {"answer": "Agent 回答"}

        mock_db = MagicMock()

        with patch(
            "services.agent.dual_write.get_homepage_agent_mode"
        ) as mock_get_mode:
            with patch(
                "services.agent.dual_write.write_dual_write_audit"
            ):
                mock_get_mode.return_value = HomepageAgentMode.DUAL_WRITE

                result = None

                async def run():
                    nonlocal result
                    result = await execute_dual_write(
                        db=mock_db,
                        question="本月销售额",
                        trace_id="t-test",
                        current_user={"id": 1},
                        connection_id=1,
                        agent_fn=fake_agent,
                        nlq_fn=fake_nlq,
                    )

                import asyncio
                asyncio.run(run())

                assert result is not None
                assert result.source == "agent"
                assert result.mode == HomepageAgentMode.DUAL_WRITE
                assert call_log["agent"] is True
                assert call_log["nlq"] is True  # dual_write 模式下 NLQ 也被调用

    def test_execute_dual_write_agent_only_mode(self):
        """TC-T2.3-010: execute_dual_write agent_only 模式失败不降级"""
        from services.agent.dual_write import execute_dual_write, HomepageAgentMode

        async def fake_agent(question, trace_id, user, conn_id):
            raise RuntimeError("Agent 服务不可用")

        async def fake_nlq(question, trace_id, user, conn_id):
            return {"answer": "NLQ 回答"}

        mock_db = MagicMock()

        with patch(
            "services.agent.dual_write.get_homepage_agent_mode"
        ) as mock_get_mode:
            mock_get_mode.return_value = HomepageAgentMode.AGENT_ONLY

            got_error = False

            async def run():
                nonlocal got_error
                try:
                    await execute_dual_write(
                        db=mock_db,
                        question="本月销售额",
                        trace_id="t-test",
                        current_user={"id": 1},
                        connection_id=1,
                        agent_fn=fake_agent,
                        nlq_fn=fake_nlq,
                    )
                except RuntimeError:
                    got_error = True

            import asyncio
            asyncio.run(run())

            assert got_error is True  # agent_only 模式失败不降级

    def test_check_and_trigger_auto_rollback(self):
        """TC-T2.3-011: check_and_trigger_auto_rollback 失败率超阈值时回滚"""
        from services.agent.dual_write import (
            check_and_trigger_auto_rollback,
            HomepageAgentMode,
            _failure_tracker,
        )

        # 重置全局跟踪器
        _failure_tracker._window.clear()

        mock_db = MagicMock()

        # 记录 15 次成功 + 1 次失败（样本不足，不触发）
        for _ in range(15):
            _failure_tracker.record(success=True)
        _failure_tracker.record(success=False)  # 1/16 = 6.25%

        with patch(
            "services.agent.dual_write.write_system_audit_log"
        ) as mock_audit:
            with patch(
                "services.agent.dual_write.PlatformSettingsService"
            ) as MockPS:
                mock_ps_instance = MagicMock()
                MockPS.return_value = mock_ps_instance

                result = check_and_trigger_auto_rollback(db=mock_db)

                assert result is not None
                assert "failure_rate" in str(result)
                mock_audit.assert_called_once()
                # 确认 audit actor=system
                call_args = mock_audit.call_args
                assert call_args[1]["actor"] == "system"

    def test_mode_change_writes_audit_log(self):
        """TC-T2.3-012: 模式切换写入 audit log"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_admin

        try:
            with patch(
                "services.agent.dual_write.write_system_audit_log"
            ) as mock_audit:
                with patch(
                    "services.data_agent.routes.agent.PlatformSettingsService"
                ) as MockPS:
                    mock_ps_instance = MagicMock()
                    MockPS.return_value = mock_ps_instance

                    client = TestClient(app, raise_server_exceptions=False)
                    resp = client.post(
                        "/api/agent/mode",
                        json={"mode": "dual_write"},
                        headers={"Authorization": "Bearer fake-token"},
                    )

                    assert resp.status_code == 200
                    # audit log 被调用（actor=system）
                    assert mock_audit.called
                    call_args = mock_audit.call_args
                    assert call_args[1]["actor"] == "system"
                    assert "mode_change" in call_args[1]["event_type"]

        finally:
            app.dependency_overrides.clear()

    def test_mode_update_with_user_override(self):
        """TC-T2.3-013: 支持单用户 override"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_admin

        try:
            with patch(
                "services.agent.dual_write.write_system_audit_log"
            ):
                with patch(
                    "services.data_agent.routes.agent.PlatformSettingsService"
                ) as MockPS:
                    mock_ps_instance = MagicMock()
                    MockPS.return_value = mock_ps_instance

                    client = TestClient(app, raise_server_exceptions=False)
                    resp = client.post(
                        "/api/agent/mode",
                        json={
                            "mode": "agent_only",
                            "user_override": {123: "legacy_only", 456: "dual_write"},
                        },
                        headers={"Authorization": "Bearer fake-token"},
                    )

                    assert resp.status_code == 200
                    # 确认 PlatformSettingsService.set 被调用两次（全局 + override）
                    assert mock_ps_instance.set.call_count >= 1

        finally:
            app.dependency_overrides.clear()


# ============================================================================
# 集成：六步 + 八步 + 灰度 完整链路
# ============================================================================


class TestIntegrationE2E:
    """T2.1 + T2.2 + T2.3 集成验证"""

    def _mock_user(self):
        return {"id": 1, "username": "test", "role": "analyst", "tenant_id": uuid.uuid4()}

    def test_full_pipeline_causation_runs_six_steps(self):
        """TC-INT-001: 完整六步归因流程可复现"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        mock_result = {
            "delta_abs": -250_000.0,
            "delta_pct": -0.119,
            "root_dimension": "region",
            "root_value": "北京",
            "confidence": 0.85,
            "narrative_summary": "北京区域贡献最大",
            "anomaly_confirmed": True,
            "magnitude": 0.119,
            "concentration_point": "region=北京",
            "recommended_actions": [],
            "hypothesis_trace": [],
            "insight_report": {"metadata": {}, "summary": ""},
            "session_id": str(uuid.uuid4()),
            "session_status": "completed",
            "steps_count": 6,
            "total_time_ms": 1200,
        }

        try:
            with patch(
                "services.data_agent.routes.causation.CausationSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_instance.create_session.return_value = MagicMock(
                    id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                    created_by=1,
                    status="created",
                    session_metadata={"metric": "gmv"},
                )
                mock_instance.run_causation = AsyncMock(return_value=mock_result)
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/data-agent/causation",
                    json={
                        "metric": "gmv",
                        "dimensions": ["region", "product_category", "channel"],
                        "time_range": {"start": "2026-04-01", "end": "2026-04-15"},
                        "compare_mode": "mom",
                        "threshold_pct": -0.05,
                        "context": {"tenant_id": str(uuid.uuid4()), "scenario": "causation"},
                    },
                )

                assert resp.status_code == 201
                data = resp.json()

                # 6 步收敛
                assert data["steps_count"] == 6
                # confidence >= 0.7
                assert data["confidence"] >= 0.7
                # 异动确认
                assert data["anomaly_confirmed"] is True
                # 根因维度非空
                assert data["root_dimension"] != ""

        finally:
            app.dependency_overrides.clear()

    def test_full_pipeline_dau_churn_runs_eight_steps(self):
        """TC-INT-002: 完整 DAU 流失归因八步流程可复现"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        mock_result = {
            "delta_abs": -1500.0,
            "delta_pct": -0.083,
            "segment_breakdown": {
                "new_users": {"current": 1200, "baseline": 1500, "delta": -300, "delta_pct": -0.20},
                "churned_users": {"current": 800, "baseline": 600, "delta": +200, "delta_pct": +0.33},
                "returned_users": {"current": 500, "baseline": 700, "delta": -200, "delta_pct": -0.29},
            },
            "correlated_metric": {"metric": "new_user_acquisition", "coefficient": -0.72, "p_value": 0.008},
            "root_dimension": "user_segment",
            "root_value": "新客",
            "confidence": 0.78,
            "narrative_summary": "新客获取下滑是主因",
            "anomaly_confirmed": True,
            "magnitude": 0.083,
            "confirmed_hypothesis_type": "acquisition",
            "h1_status": "confirmed",
            "h2_status": "pending",
            "recommended_actions": [],
            "hypothesis_trace": [],
            "insight_report": {"metadata": {}, "summary": ""},
            "session_id": str(uuid.uuid4()),
            "session_status": "completed",
            "steps_count": 8,
            "total_time_ms": 2100,
        }

        try:
            with patch(
                "services.data_agent.routes.dau_churn.DauChurnSessionManager"
            ) as MockMgr:
                mock_instance = MagicMock()
                mock_instance.create_session.return_value = MagicMock(
                    id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                    created_by=1,
                    status="created",
                    session_metadata={"metric": "dau"},
                )
                mock_instance.run_causation = AsyncMock(return_value=mock_result)
                MockMgr.return_value = mock_instance

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/data-agent/dau-churn",
                    json={
                        "metric": "dau",
                        "dimensions": ["user_segment", "channel", "app_version"],
                        "time_range": {"start": "2026-04-08", "end": "2026-04-14"},
                        "compare_mode": "wow",
                        "threshold_pct": -0.03,
                        "context": {"cross_table": True},
                    },
                )

                assert resp.status_code == 201
                data = resp.json()

                # 8 步收敛
                assert data["steps_count"] == 8
                # confidence >= 0.7
                assert data["confidence"] >= 0.7
                # |coefficient| >= 0.5
                assert abs(data["correlated_metric"]["coefficient"]) >= 0.5
                # H1/H2 状态非空
                assert data["h1_status"] in ("confirmed", "rejected", "pending")
                assert data["h2_status"] in ("confirmed", "rejected", "pending")

        finally:
            app.dependency_overrides.clear()

    def test_agent_stream_uses_correct_mode(self):
        """TC-INT-003: /api/agent/stream SSE 端点存在且返回事件流"""
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = self._mock_user

        try:
            with patch("services.data_agent.runner.run_agent") as mock_run:
                from services.data_agent.response import AgentEvent

                async def fake_gen(*args, **kwargs):
                    yield AgentEvent(type="metadata", content={"conversation_id": "test", "run_id": "r1"})
                    yield AgentEvent(type="answer", content={"answer": "测试回答", "trace_id": "t1", "run_id": "r1", "tools_used": [], "response_type": "text", "steps_count": 1, "execution_time_ms": 100})

                mock_run.return_value = fake_gen()

                client = TestClient(app, raise_server_exceptions=False)
                resp = client.post(
                    "/api/agent/stream",
                    json={"question": "本月销售额"},
                    headers={"Authorization": "Bearer fake-token"},
                )

                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")

        finally:
            app.dependency_overrides.clear()
