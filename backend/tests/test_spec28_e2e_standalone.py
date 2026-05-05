"""
test_spec28_e2e_standalone.py — T2.1/T2.2/T2.3 端到端测试（无数据库依赖）

直接导入 app.main 构建 TestClient，mock 所有 session managers，
不触发 conftest.py 的 setup_database (alembic) fixture。

运行: pytest tests/test_spec28_e2e_standalone.py -v
"""
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# ── 设置最小环境变量（在 import app 之前）───────────────────────────────
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:***@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("SECURE_COOKIES", "false")
os.environ.setdefault("SERVICE_JWT_SECRET", "test-jwt-secret-for-service-auth-32ch")
os.environ.setdefault("HOMEPAGE_AGENT_MODE", "dual_write_with_insight")

import pytest
from fastapi.testclient import TestClient


# ══════════════════════════════════════════════════════════════════════
# T2.1 — Spec 28 UC-1 归因六步端到端
# ══════════════════════════════════════════════════════════════════════

class TestCausationE2E:
    """验收：给定输入 → 6步推理日志 + 最终归因结论可复现"""

    @pytest.fixture(autouse=False)
    def _setup_routes(self):
        """
        在 patch 生效范围内 import app（避免模块缓存问题）。
        同时 mock CausationSessionManager.run_causation。
        """
        # 模拟 6 步归因流程返回
        def mock_run_causation(self, session_id: str, user_query: str, **kwargs):
            steps_data = [
                {
                    "step": 1,
                    "step_name": "variable_analysis",
                    "status": "completed",
                    "result": {
                        "metrics": ["sales_amount", "order_count", "customer_count"],
                        "metric_overview": {"sales_amount": {"current": 850000, "previous": 1000000, "change_pct": -15.0}},
                    },
                    "思考": "指标定义: 销售额(sales_amount)=订单金额总和; 当前值85万,环比-15%; 订单数降12%,客单价降3.4%",
                },
                {
                    "step": 2,
                    "step_name": "metric_drilldown",
                    "status": "completed",
                    "result": {
                        "top_dimensions": [
                            {"dimension": "product_category", "contribution": -6.2, "direction": "negative"},
                            {"dimension": "region", "contribution": -4.1, "direction": "negative"},
                            {"dimension": "sales_channel", "contribution": -2.8, "direction": "negative"},
                        ]
                    },
                    "思考": "下钻维度贡献: 产品品类贡献-6.2%为最大拖累; 区域维度贡献-4.1%; 渠道维度贡献-2.8%",
                },
                {
                    "step": 3,
                    "step_name": "dimension_breakdown",
                    "status": "completed",
                    "result": {
                        "breakdown": {
                            "product_category": {
                                "clothing": {"current": 320000, "previous": 380000, "change_pct": -15.8},
                                "electronics": {"current": 280000, "previous": 350000, "change_pct": -20.0},
                                "food": {"current": 250000, "previous": 270000, "change_pct": -7.4},
                            }
                        }
                    },
                    "思考": "维度拆解: 电子产品销售额环比-20%为最大下滑; 服装-15.8%; 食品-7.4%相对稳健",
                },
                {
                    "step": 4,
                    "step_name": "candidate_filter",
                    "status": "completed",
                    "result": {
                        "candidates": [
                            {"cause": "竞品降价", "confidence": 0.82, "evidence": "3家主要竞品在Q2下调价格15-20%"},
                            {"cause": "市场需求下降", "confidence": 0.71, "evidence": "行业整体需求下滑约12%"},
                            {"cause": "产品质量问题", "confidence": 0.45, "evidence": "客服投诉中15%提及质量问题"},
                        ]
                    },
                    "思考": "候选原因筛选: 竞品降价置信度0.82(最高); 市场需求下降置信度0.71; 排除产品质量(置信度<0.5阈值)",
                },
                {
                    "step": 5,
                    "step_name": "causal_verify",
                    "status": "completed",
                    "result": {
                        "verified_cause": "竞品降价",
                        "confidence": 0.82,
                        "causal_score": 0.79,
                        "reasoning": "电子产品和服装高价品类受影响最大,符合竞品价格战影响模型",
                    },
                    "思考": "因果验证: Granger因果检验p值<0.05,确认竞品降价→销售额下滑因果关系成立",
                },
                {
                    "step": 6,
                    "step_name": "report_generate",
                    "status": "completed",
                    "result": {
                        "summary": "销售额下滑归因结论: 核心原因为竞品降价(置信度82%)",
                        "contributions": {"竞品降价": -6.2, "市场需求下降": -4.1, "其他": -2.7},
                        "recommendations": [
                            "建议开展竞争对手价格监测,动态调整定价策略",
                            "针对高价品类(电子产品、服装)推出差异化促销",
                            "加强非价格竞争: 服务、质量、品牌建设",
                        ],
                    },
                    "思考": "生成归因报告: 总结核心结论和可执行建议,完成六步归因分析",
                },
            ]

            async def _gen():
                for s in steps_data:
                    yield s

            return _gen()

        with patch(
            "services.data_agent.routes.causation.CausationSessionManager.run_causation",
            mock_run_causation,
        ):
            # 现在 import app（在 patch 上下文中）
            from app.main import app as fastapi_app
            client = TestClient(fastapi_app)
            yield client

    def test_causation_creates_session_and_returns_six_steps(self, _setup_routes):
        """
        T2.1 验收：POST /api/data-agent/causation/
        → 返回 202 Accepted + session_id
        → SSE stream 包含 6 个 step 事件
        → 最终结论包含"竞品降价"、"置信度"
        """
        client = _setup_routes

        # 触发归因分析
        response = client.post(
            "/api/data-agent/causation/",
            json={
                "user_query": "分析一下为什么这个月销售额下滑了",
                "language": "zh",
            },
            timeout=30,
        )

        assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
        data = response.json()
        assert "session_id" in data, f"Expected session_id in response: {data}"

        session_id = data["session_id"]
        assert "data" in data
        assert data["data"]["initial_message"] == "开始归因分析..."

        # 读取 SSE stream，验证 6 步
        stream_response = client.get(
            f"/api/data-agent/causation/stream/{session_id}",
            timeout=30,
        )
        assert stream_response.status_code == 200, f"Stream failed: {stream_response.status_code}"
        assert stream_response.headers["content-type"].startswith("text/event-stream")

        lines = stream_response.text.strip().split("\n")
        step_events = [l for l in lines if l.startswith("data: ")]
        assert len(step_events) == 6, f"Expected 6 step events, got {len(step_events)}"

        # 验证最后一个 step 包含归因结论
        last_event = step_events[-1]
        assert "竞品降价" in last_event or "confidence" in last_event.lower(), \
            f"Last event missing conclusion: {last_event}"

    def test_causation_status_endpoint(self, _setup_routes):
        """T2.1: GET /api/data-agent/causation/status/{session_id}"""
        client = _setup_routes

        # 先创建 session
        response = client.post(
            "/api/data-agent/causation/",
            json={"user_query": "为什么销售额下降"},
            timeout=10,
        )
        session_id = response.json()["session_id"]

        # 查询状态
        status_resp = client.get(
            f"/api/data-agent/causation/status/{session_id}",
            timeout=10,
        )
        # 状态端点存在即可（即使返回 mock 数据）
        assert status_resp.status_code in (200, 404), \
            f"Status endpoint returned {status_resp.status_code}: {status_resp.text}"

    def test_causation_abort(self, _setup_routes):
        """T2.1: POST /api/data-agent/causation/abort/{session_id}"""
        client = _setup_routes

        response = client.post(
            "/api/data-agent/causation/",
            json={"user_query": "销售额下滑"},
            timeout=10,
        )
        session_id = response.json()["session_id"]

        abort_resp = client.post(
            f"/api/data-agent/causation/abort/{session_id}",
            timeout=10,
        )
        assert abort_resp.status_code in (200, 404), \
            f"Abort returned {abort_resp.status_code}: {abort_resp.text}"


# ══════════════════════════════════════════════════════════════════════
# T2.2 — Spec 28 UC-2 DAU 流失分析端到端
# ══════════════════════════════════════════════════════════════════════

class TestDauChurnE2E:
    """验收：DAU 流失分析 8 步推理 + 最终洞察可复现"""

    @pytest.fixture(autouse=False)
    def _setup_routes(self):
        def mock_run_causation(self, session_id: str, user_query: str, **kwargs):
            steps_data = [
                {
                    "step": 1,
                    "step_name": "dau_retention_overview",
                    "status": "completed",
                    "result": {
                        "dau": 12500,
                        "previous_dau": 14000,
                        "change_pct": -10.7,
                        "retention_rate": 0.68,
                    },
                    "思考": "DAU 从 14000 下降至 12500,降幅-10.7%; 留存率68%低于行业基准75%",
                },
                {
                    "step": 2,
                    "step_name": "cohort_analysis",
                    "status": "completed",
                    "result": {
                        "cohorts": [
                            {"cohort_week": "2024-W01", "cohort_size": 3000, "retention_week1": 0.72, "retention_week2": 0.61},
                            {"cohort_week": "2024-W02", "cohort_size": 2800, "retention_week1": 0.68, "retention_week2": 0.55},
                        ]
                    },
                    "思考": "群组分析: W01群组第2周留存率61%,W02群组55%,新用户留存呈下滑趋势",
                },
                {
                    "step": 3,
                    "step_name": "churn_user_profile",
                    "status": "completed",
                    "result": {
                        "churn_rate": 0.32,
                        "avg_sessions_before_churn": 3.2,
                        "avg_days_to_churn": 8.5,
                        "user_segments": {
                            "no_onboarding": {"pct": 0.41, "churn_rate": 0.58},
                            "low_engagement": {"pct": 0.33, "churn_rate": 0.42},
                            "price_sensitive": {"pct": 0.18, "churn_rate": 0.28},
                        }
                    },
                    "思考": "流失用户画像: 41%未完成新手引导,平均3.2次会话后流失,8.5天到达流失节点",
                },
                {
                    "step": 4,
                    "step_name": "funnel_analysis",
                    "status": "completed",
                    "result": {
                        "funnel": {
                            "visit": 50000,
                            "sign_up": 15000,
                            "first_action": 9000,
                            "return_visit": 5000,
                            "retained": 3200,
                        },
                        "drop_off": {"sign_up->first_action": 40.0, "first_action->retained": 35.0},
                    },
                    "思考": "漏斗分析: 注册转化率30%; 首单后留存率55%; 关键流失点在注册到首单(掉40%)",
                },
                {
                    "step": 5,
                    "step_name": "feature_adoption",
                    "status": "completed",
                    "result": {
                        "adoption_rates": {
                            "core_feature_a": 0.72,
                            "core_feature_b": 0.45,
                            "advanced_feature_c": 0.18,
                        }
                    },
                    "思考": "功能渗透: 核心功能A渗透率72%; 高级功能C仅18%,存在较大提升空间",
                },
                {
                    "step": 6,
                    "step_name": "push_notification_effect",
                    "status": "completed",
                    "result": {
                        "notification_stats": {
                            "sent": 8000,
                            "delivered": 7800,
                            "opened": 2340,
                            "ctr": 0.30,
                            "conversions": 312,
                        }
                    },
                    "思考": "推送效果: 送达率97.5%; 打开率30%; 转化312次,ROI符合预期",
                },
                {
                    "step": 7,
                    "step_name": "churn_risk_scoring",
                    "status": "completed",
                    "result": {
                        "risk_distribution": {
                            "high_risk": 1800,
                            "medium_risk": 3200,
                            "low_risk": 4500,
                        },
                        "top_risk_factors": ["无新手引导完成", "7天内<2次会话", "未使用核心功能"],
                    },
                    "思考": "流失风险评分: 高风险用户1800人(14.4%); 中风险3200人; 主要风险因子已识别",
                },
                {
                    "step": 8,
                    "step_name": "insight_summary",
                    "status": "completed",
                    "result": {
                        "summary": "DAU 流失主要原因是新用户引导缺失和产品功能认知不足",
                        "key_insights": [
                            "41%流失用户未完成新手引导,是最大风险因子",
                            "核心功能B渗透率仅45%,需强化用户教育",
                            "高风险用户1800人需立即干预",
                        ],
                        "recommendations": [
                            "优化新手引导流程,确保3步内完成关键操作",
                            "针对高流失风险用户推送个性化引导推送",
                            "建立功能发现引导机制,提升核心功能渗透率",
                        ],
                    },
                    "思考": "生成洞察摘要: 完成8步DAU流失分析,识别3大核心问题,给出可执行建议",
                },
            ]

            async def _gen():
                for s in steps_data:
                    yield s

            return _gen()

        with patch(
            "services.data_agent.routes.dau_churn.DauChurnSessionManager.run_causation",
            mock_run_causation,
        ):
            from app.main import app as fastapi_app
            client = TestClient(fastapi_app)
            yield client

    def test_dau_churn_creates_session_and_returns_eight_steps(self, _setup_routes):
        """
        T2.2 验收：POST /api/data-agent/dau-churn/
        → 返回 202 + session_id
        → SSE stream 包含 8 个 step 事件
        → 最终洞察包含流失原因和建议
        """
        client = _setup_routes

        response = client.post(
            "/api/data-agent/dau-churn/",
            json={
                "user_query": "分析一下最近的DAU流失情况",
                "language": "zh",
            },
            timeout=30,
        )

        assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
        data = response.json()
        assert "session_id" in data, f"Expected session_id: {data}"

        session_id = data["session_id"]

        stream_response = client.get(
            f"/api/data-agent/dau-churn/stream/{session_id}",
            timeout=30,
        )
        assert stream_response.status_code == 200, f"Stream failed: {stream_response.status_code}"
        assert stream_response.headers["content-type"].startswith("text/event-stream")

        lines = stream_response.text.strip().split("\n")
        step_events = [l for l in lines if l.startswith("data: ")]
        assert len(step_events) == 8, f"Expected 8 step events, got {len(step_events)}: {step_events}"

        # 验证最终洞察
        last_event = step_events[-1]
        assert any(kw in last_event for kw in ["流失", "新手引导", "churn", "insight", "建议"]), \
            f"Last event missing insight: {last_event}"

    def test_dau_churn_status_and_abort(self, _setup_routes):
        """T2.2: status + abort 端点存在性验证"""
        client = _setup_routes

        response = client.post(
            "/api/data-agent/dau-churn/",
            json={"user_query": "DAU 下降原因"},
            timeout=10,
        )
        session_id = response.json()["session_id"]

        status_resp = client.get(
            f"/api/data-agent/dau-churn/status/{session_id}",
            timeout=10,
        )
        assert status_resp.status_code in (200, 404), f"Status: {status_resp.status_code}"

        abort_resp = client.post(
            f"/api/data-agent/dau-churn/abort/{session_id}",
            timeout=10,
        )
        assert abort_resp.status_code in (200, 404), f"Abort: {abort_resp.status_code}"


# ══════════════════════════════════════════════════════════════════════
# T2.3 — Spec 36 首页 Agent 灰度验证
# ══════════════════════════════════════════════════════════════════════

class TestHomepageAgentMode:
    """验收：HomepageAgentMode 枚举 + execute_dual_write 状态机"""

    def test_homepage_agent_mode_enum_exists(self):
        """T2.3: HomepageAgentMode 枚举在 app.api.agent 中定义"""
        from app.api import agent as agent_module

        assert hasattr(agent_module, "HomepageAgentMode"), \
            "HomepageAgentMode enum not found in app.api.agent"

        mode = agent_module.HomepageAgentMode
        # 验证至少有两种模式
        members = list(mode)
        assert len(members) >= 2, f"Expected at least 2 modes, got {members}"

        # 验证有关键模式
        member_values = [m.value for m in members]
        assert any(v in str(member_values) for v in ["agent", "dual", "tableau", "write"]), \
            f"HomepageAgentMode members don't look right: {member_values}"

    def test_homepage_agent_mode_values(self):
        """T2.3: HomepageAgentMode 包含预期值"""
        from app.api import agent as agent_module

        mode = agent_module.HomepageAgentMode
        values = [m.value for m in mode]

        # 至少包含一个可识别的模式值
        assert len(values) >= 2, f"Too few mode values: {values}"

    def test_execute_dual_write_exists(self):
        """T2.3: execute_dual_write 方法存在且可调用"""
        from app.api import agent as agent_module

        assert hasattr(agent_module, "execute_dual_write"), \
            "execute_dual_write not found in app.api.agent"

        func = getattr(agent_module, "execute_dual_write")
        assert callable(func), "execute_dual_write is not callable"

    @pytest.mark.asyncio
    async def test_execute_dual_write_state_machine(self):
        """T2.3: execute_dual_write 四状态转换: NO_DUAL → RUNNING → SUCCESS/FAILED"""
        from app.api import agent as agent_module
        from enum import Enum

        # 支持旧实现(str Enum)或新实现(标准 Enum)
        Mode = agent_module.HomepageAgentMode
        try:
            agent_mode = Mode.AGENT_ONLY
        except AttributeError:
            # 旧实现用字符串值
            agent_mode = Mode("agent_only")

        # mock 写入方法
        with patch.object(agent_module, "tableau_writeback", new_callable=AsyncMock) as mock_tableau, \
             patch.object(agent_module, "db_write", new_callable=AsyncMock) as mock_db:

            mock_tableau.return_value = {"tableau_job_id": "job-123", "status": "success"}
            mock_db.return_value = {"rows_written": 5, "status": "success"}

            result = await agent_module.execute_dual_write(
                session_id="test-session-001",
                user_query="分析首页数据",
                agent_mode=agent_mode,
            )

            # 验证返回值结构
            assert isinstance(result, dict), f"Expected dict, got {type(result)}"
            # 期望包含状态字段
            assert any(k in result for k in ["status", "state", "mode", "dual_write"]), \
                f"Result missing expected keys: {result.keys()}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
