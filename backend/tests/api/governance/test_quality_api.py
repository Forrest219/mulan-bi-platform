"""数据质量 API 集成测试 — Spec 15

需要 PostgreSQL 运行，使用 tests/conftest.py 提供的 fixtures。
认证 fixtures: admin_client (admin), analyst_client (analyst role)
"""
import pytest
from httpx import AsyncClient


class TestQualityRulesCRUD:
    """质量规则 CRUD API 测试"""

    @pytest.mark.asyncio
    async def test_create_rule_requires_auth(self, client):
        """未认证用户不能创建规则"""
        response = await client.post(
            "/api/governance/quality/rules",
            json={
                "name": "test_null_rate",
                "datasource_id": 1,
                "table_name": "users",
                "field_name": "email",
                "rule_type": "null_rate",
                "threshold": {"max_rate": 0.05},
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_rule_unauthorized_for_analyst(self, analyst_client):
        """analyst 角色不能创建规则（需要 admin/data_admin）"""
        response = await analyst_client.post(
            "/api/governance/quality/rules",
            json={
                "name": "test_rule",
                "datasource_id": 1,
                "table_name": "users",
                "field_name": "email",
                "rule_type": "null_rate",
                "threshold": {"max_rate": 0.05},
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_rule_invalid_rule_type(self, admin_client):
        """无效的 rule_type 返回 400"""
        response = await admin_client.post(
            "/api/governance/quality/rules",
            json={
                "name": "test_invalid_type",
                "datasource_id": 1,
                "table_name": "users",
                "field_name": "email",
                "rule_type": "invalid_type",
                "threshold": {"max_rate": 0.05},
            },
        )
        assert response.status_code == 400
        assert "GOV_003" in response.text or "不支持的规则类型" in response.text

    @pytest.mark.asyncio
    async def test_create_rule_duplicate_returns_gov_006(self, admin_client):
        """重复规则返回 GOV_006"""
        # 先创建一个规则
        rule_payload = {
            "name": "邮箱唯一性",
            "datasource_id": 1,
            "table_name": "users",
            "field_name": "email",
            "rule_type": "unique_count",
            "threshold": {"min": 1},
        }
        response1 = await admin_client.post(
            "/api/governance/quality/rules",
            json=rule_payload,
        )
        # 如果数据源不存在，跳过此测试
        if response1.status_code == 400 and "GOV_010" in response1.text:
            pytest.skip("数据源不存在，跳过重复规则测试")

        assert response1.status_code == 201

        # 尝试创建相同规则
        response2 = await admin_client.post(
            "/api/governance/quality/rules",
            json=rule_payload,
        )
        assert response2.status_code == 409
        assert "GOV_006" in response2.text

    @pytest.mark.asyncio
    async def test_create_rule_success(self, admin_client):
        """admin 创建规则成功"""
        response = await admin_client.post(
            "/api/governance/quality/rules",
            json={
                "name": "邮箱空值率",
                "datasource_id": 1,
                "table_name": "users",
                "field_name": "email",
                "rule_type": "null_rate",
                "threshold": {"max_rate": 0.05},
            },
        )
        # 数据源不存在时跳过
        if response.status_code == 400 and "GOV_010" in response.text:
            pytest.skip("数据源不存在，跳过创建测试")
        assert response.status_code == 201
        data = response.json()
        assert "rule" in data
        assert data["rule"]["name"] == "邮箱空值率"

    @pytest.mark.asyncio
    async def test_list_rules(self, client):
        """已认证用户可以查看规则列表"""
        response = await client.get("/api/governance/quality/rules")
        assert response.status_code == 200
        data = response.json()
        assert "rules" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_rules_filter_by_datasource(self, client):
        """规则列表支持按 datasource_id 筛选"""
        response = await client.get("/api/governance/quality/rules?datasource_id=1")
        assert response.status_code == 200
        data = response.json()
        assert "rules" in data

    @pytest.mark.asyncio
    async def test_list_rules_pagination(self, client):
        """规则列表支持分页"""
        response = await client.get("/api/governance/quality/rules?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    @pytest.mark.asyncio
    async def test_get_rule_not_found(self, client):
        """获取不存在的规则返回 404"""
        response = await client.get("/api/governance/quality/rules/999999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_rule_not_found(self, admin_client):
        """更新不存在的规则返回 404"""
        response = await admin_client.put(
            "/api/governance/quality/rules/999999",
            json={"name": "updated_name"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_rule_success(self, admin_client):
        """更新规则成功"""
        # 先创建规则
        create_resp = await admin_client.post(
            "/api/governance/quality/rules",
            json={
                "name": "待更新规则",
                "datasource_id": 1,
                "table_name": "users",
                "field_name": "email",
                "rule_type": "null_rate",
                "threshold": {"max_rate": 0.05},
            },
        )
        if create_resp.status_code == 400 and "GOV_010" in create_resp.text:
            pytest.skip("数据源不存在，跳过")

        assert create_resp.status_code == 201
        rule_id = create_resp.json()["rule"]["id"]

        # 更新规则
        update_resp = await admin_client.put(
            f"/api/governance/quality/rules/{rule_id}",
            json={"name": "已更新规则", "severity": "HIGH"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["rule"]["name"] == "已更新规则"
        assert update_resp.json()["rule"]["severity"] == "HIGH"

    @pytest.mark.asyncio
    async def test_delete_rule_not_found(self, admin_client):
        """删除不存在的规则返回 404"""
        response = await admin_client.delete("/api/governance/quality/rules/999999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_rule_not_found(self, admin_client):
        """切换不存在的规则返回 404"""
        response = await admin_client.put("/api/governance/quality/rules/999999/toggle")
        assert response.status_code == 404


class TestQualityResults:
    """检测结果 API 测试"""

    @pytest.mark.asyncio
    async def test_list_results_requires_auth(self, client):
        """未认证不能查看结果"""
        response = await client.get("/api/governance/quality/results")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_results(self, client):
        """已认证可以查看结果列表"""
        response = await client.get("/api/governance/quality/results")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    @pytest.mark.asyncio
    async def test_list_results_filter_by_passed(self, client):
        """结果列表支持按 passed 筛选"""
        response = await client.get("/api/governance/quality/results?passed=true")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_results_pagination(self, client):
        """结果列表支持分页"""
        response = await client.get("/api/governance/quality/results?page=1&page_size=20")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 20

    @pytest.mark.asyncio
    async def test_get_latest_results(self, client):
        """获取最新检测结果"""
        response = await client.get("/api/governance/quality/results/latest")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data


class TestQualityScores:
    """质量评分 API 测试"""

    @pytest.mark.asyncio
    async def test_get_scores_requires_auth(self, client):
        """未认证不能查看评分"""
        response = await client.get("/api/governance/quality/scores?datasource_id=1")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_score_trend(self, client):
        """评分趋势 API"""
        response = await client.get("/api/governance/quality/scores/trend?datasource_id=1&days=7")
        assert response.status_code == 200
        data = response.json()
        assert "trend" in data
        assert data["datasource_id"] == 1
        assert data["days"] == 7


class TestQualityDashboard:
    """质量看板 API 测试"""

    @pytest.mark.asyncio
    async def test_dashboard_requires_auth(self, client):
        """未认证不能查看看板"""
        response = await client.get("/api/governance/quality/dashboard")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_dashboard(self, client):
        """看板 API 返回汇总数据"""
        response = await client.get("/api/governance/quality/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "datasource_scores" in data or "top_failures" in data


class TestQualityExecute:
    """检测执行 API 测试"""

    @pytest.mark.asyncio
    async def test_execute_requires_admin(self, analyst_client):
        """analyst 不能触发检测"""
        response = await analyst_client.post(
            "/api/governance/quality/execute",
            json={"datasource_id": 1},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_execute_requires_datasource_or_rule_ids(self, admin_client):
        """execute 必须提供 datasource_id 或 rule_ids"""
        response = await admin_client.post(
            "/api/governance/quality/execute",
            json={},
        )
        assert response.status_code == 400
        assert "GOV_002" in response.text

    @pytest.mark.asyncio
    async def test_execute_single_rule_not_found(self, admin_client):
        """执行不存在的规则返回 404"""
        response = await admin_client.post("/api/governance/quality/execute/rule/999999")
        assert response.status_code == 404
