"""
语义维护 - 回滚服务单元测试 (Spec 19)

测试发布 → 回滚 → 验证字段/metric/status 恢复到前一版本

覆盖范围：
- RollbackService.execute_rollback：正常回滚流程
- RollbackService.can_rollback：状态验证
- RollbackService.determine_rollback_type：回滚类型判断
- POST /publish-logs/{log_id}/rollback API 端点
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from services.semantic_maintenance.models import (
    PublishStatus,
    SemanticStatus,
    TableauDatasourceSemantics,
    TableauFieldSemantics,
    TableauPublishLog,
)
from services.semantic_maintenance.rollback_service import RollbackService


# -------------------------------------------------------------------------
# 辅助函数
# -------------------------------------------------------------------------

def _create_datasource_log(session, connection_id=1, object_id=1,
                            diff_json=None, status=PublishStatus.SUCCESS, operator=1):
    """创建测试用数据源发布日志"""
    if diff_json is None:
        diff_json = {"description": {"tableau": "old desc", "mulan": "new desc"}}
    log = TableauPublishLog(
        connection_id=connection_id,
        object_type="datasource",
        object_id=object_id,
        tableau_object_id="test-ds-luid",
        diff_json=diff_json,
        status=status,
        operator=operator,
    )
    session.add(log)
    session.flush()
    return log


def _create_field_log(session, connection_id=1, object_id=2,
                       diff_json=None, status=PublishStatus.SUCCESS, operator=1):
    """创建测试用字段发布日志"""
    if diff_json is None:
        diff_json = {
            "semantic_definition": {"tableau": "old def", "mulan": "new def"},
            "metric_definition": {"tableau": "old metric", "mulan": "new metric"},
        }
    log = TableauPublishLog(
        connection_id=connection_id,
        object_type="field",
        object_id=object_id,
        tableau_object_id="test-field-luid",
        diff_json=diff_json,
        status=status,
        operator=operator,
    )
    session.add(log)
    session.flush()
    return log


def _create_datasource_semantics(session, connection_id=1, ds_id=1,
                                  semantic_description="current desc",
                                  status=SemanticStatus.APPROVED):
    """创建测试用数据源语义记录"""
    ds = TableauDatasourceSemantics(
        id=ds_id,
        connection_id=connection_id,
        tableau_datasource_id="test-ds-luid",
        semantic_name="Test DS",
        semantic_description=semantic_description,
        status=status,
        sensitivity_level="low",
        published_to_tableau=True,
        current_version=1,
    )
    session.add(ds)
    session.flush()
    return ds


def _create_field_semantics(session, connection_id=1, field_id=2,
                             semantic_definition="current definition",
                             metric_definition="current metric",
                             status=SemanticStatus.APPROVED):
    """创建测试用字段语义记录"""
    field = TableauFieldSemantics(
        id=field_id,
        connection_id=connection_id,
        tableau_field_id="test-field-luid",
        semantic_name="Test Field",
        semantic_definition=semantic_definition,
        metric_definition=metric_definition,
        status=status,
        sensitivity_level="low",
        published_to_tableau=True,
        version=1,
    )
    session.add(field)
    session.flush()
    return field


# -------------------------------------------------------------------------
# RollbackService 单元测试
# -------------------------------------------------------------------------

class TestRollbackServiceCanRollback:
    """测试 can_rollback 状态验证"""

    def test_success_status_can_rollback(self, db_session):
        """SUCCESS 状态可以回滚"""
        log = _create_datasource_log(db_session, status=PublishStatus.SUCCESS)
        svc = RollbackService()
        can, reason = svc.can_rollback(log)
        assert can is True
        assert reason == ""

    def test_rolled_back_status_cannot_rollback(self, db_session):
        """ROLLED_BACK 状态不能再次回滚"""
        log = _create_datasource_log(db_session, status=PublishStatus.ROLLED_BACK)
        svc = RollbackService()
        can, reason = svc.can_rollback(log)
        assert can is False
        assert "已回滚" in reason

    def test_pending_status_cannot_rollback(self, db_session):
        """PENDING 状态不能回滚"""
        log = _create_datasource_log(db_session, status=PublishStatus.PENDING)
        svc = RollbackService()
        can, reason = svc.can_rollback(log)
        assert can is False
        assert "只能回滚 success" in reason

    def test_failed_status_cannot_rollback(self, db_session):
        """FAILED 状态不能回滚"""
        log = _create_datasource_log(db_session, status=PublishStatus.FAILED)
        svc = RollbackService()
        can, reason = svc.can_rollback(log)
        assert can is False
        assert "只能回滚 success" in reason


class TestRollbackServiceDetermineType:
    """测试 determine_rollback_type 回滚类型判断"""

    def test_field_mapping_type(self, db_session):
        """caption/description 变更 → field_mapping"""
        log = _create_field_log(db_session, diff_json={
            "caption": {"tableau": "old", "mulan": "new"},
            "description": {"tableau": "old desc", "mulan": "new desc"},
        })
        svc = RollbackService()
        t = svc.determine_rollback_type(log)
        assert t == "field_mapping"

    def test_metric_definition_type(self, db_session):
        """metric_definition 变更 → metric_definition"""
        log = _create_field_log(db_session, diff_json={
            "metric_definition": {"tableau": "old metric", "mulan": "new metric"},
        })
        svc = RollbackService()
        t = svc.determine_rollback_type(log)
        assert t == "metric_definition"

    def test_status_type(self, db_session):
        """status 变更 → status"""
        log = _create_datasource_log(db_session, diff_json={
            "status": {"tableau": "published", "mulan": "approved"},
        })
        svc = RollbackService()
        t = svc.determine_rollback_type(log)
        assert t == "status"

    def test_rollback_nested_diff(self, db_session):
        """带 rollback 嵌套的 diff"""
        log = _create_field_log(db_session, diff_json={
            "rollback": {
                "caption": "old caption",
                "description": "old desc",
            }
        })
        svc = RollbackService()
        t = svc.determine_rollback_type(log)
        assert t == "field_mapping"


class TestRollbackServiceExecuteRollback:
    """测试 execute_rollback 完整回滚流程"""

    def test_rollback_datasource_success(self, db_session):
        """数据源回滚成功"""
        # 1. 创建数据源语义记录（当前状态）
        ds = _create_datasource_semantics(
            db_session, ds_id=1,
            semantic_description="new desc after publish",
        )

        # 2. 创建发布日志（SUCCESS 状态，diff 记录了发布前的值）
        log = _create_datasource_log(
            db_session, object_id=1, status=PublishStatus.SUCCESS,
            diff_json={
                "description": {"tableau": "old desc before publish", "mulan": "new desc after publish"},
                "rollback": {"description": "old desc before publish"},
            }
        )
        db_session.flush()
        log_id = log.id

        # 3. 执行回滚
        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log_id, operator=1)

        # 4. 验证回滚成功
        assert err is None, f"回滚失败: {err}"
        assert result["status"] == "success"
        assert result["rollback_log_id"] > 0
        assert result["original_log_id"] == log_id

        # 5. 验证 previous_version_snapshot
        snapshot = result.get("previous_version_snapshot", {})
        assert "semantic_description" in snapshot

        # 6. 验证数据源语义已恢复
        db_session.expire_all()
        ds_restored = db_session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.id == 1
        ).first()
        assert ds_restored.semantic_description == "old desc before publish"

        # 7. 验证原日志状态已更新
        db_session.expire_all()
        log_updated = db_session.query(TableauPublishLog).filter(
            TableauPublishLog.id == log_id
        ).first()
        assert log_updated.status == PublishStatus.ROLLED_BACK

    def test_rollback_field_success(self, db_session):
        """字段回滚成功"""
        # 1. 创建字段语义记录
        field = _create_field_semantics(
            db_session, field_id=2,
            semantic_definition="new definition after publish",
            metric_definition="new metric after publish",
        )

        # 2. 创建发布日志
        log = _create_field_log(
            db_session, object_id=2, status=PublishStatus.SUCCESS,
            diff_json={
                "semantic_definition": {"tableau": "old def", "mulan": "new definition after publish"},
                "metric_definition": {"tableau": "old metric", "mulan": "new metric after publish"},
                "rollback": {
                    "semantic_definition": "old def",
                    "metric_definition": "old metric",
                }
            }
        )
        db_session.flush()
        log_id = log.id

        # 3. 执行回滚
        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log_id, operator=1)

        # 4. 验证
        assert err is None, f"回滚失败: {err}"
        assert result["status"] == "success"
        assert result["rollback_type"] in ("field_mapping", "metric_definition", "unknown")

        # 5. 验证字段语义已恢复
        db_session.expire_all()
        field_restored = db_session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.id == 2
        ).first()
        assert field_restored.semantic_definition == "old def"
        assert field_restored.metric_definition == "old metric"

    def test_rollback_nonexistent_log(self, db_session):
        """回滚不存在的日志"""
        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=999999, operator=1)
        assert result == {}
        assert "不存在" in err

    def test_rollback_invalid_status(self, db_session):
        """回滚非 success 状态日志"""
        # 创建 FAILED 状态的日志
        log = _create_datasource_log(db_session, status=PublishStatus.FAILED)
        db_session.flush()

        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log.id, operator=1)
        assert result == {}
        assert "只能回滚 success" in err

    def test_rollback_connection_id_mismatch(self, db_session):
        """回滚时 connection_id 不匹配"""
        log = _create_datasource_log(db_session, connection_id=1, status=PublishStatus.SUCCESS)
        db_session.flush()

        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log.id, operator=1, connection_id=999)
        assert result == {}
        assert "不匹配" in err


class TestRollbackServiceSnapshot:
    """测试回滚前快照功能"""

    def test_snapshot_captures_current_state(self, db_session):
        """回滚前快照正确捕获当前状态"""
        # 创建带完整信息的字段
        field = _create_field_semantics(
            db_session, field_id=3,
            semantic_definition="current def",
            metric_definition="current metric",
        )

        # 创建日志
        log = _create_field_log(
            db_session, object_id=3, status=PublishStatus.SUCCESS,
            diff_json={"rollback": {"semantic_definition": "old def"}}
        )
        db_session.flush()
        log_id = log.id

        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log_id, operator=1)

        assert err is None
        snapshot = result.get("previous_version_snapshot", {})
        # 快照应包含当前状态
        assert "semantic_definition" in snapshot
        assert "metric_definition" in snapshot


# -------------------------------------------------------------------------
# API 端点测试
# -------------------------------------------------------------------------

class TestRollbackAPIEndpoint:
    """测试 POST /publish-logs/{log_id}/rollback 端点"""

    def test_rollback_unauthenticated(self, client: TestClient):
        """未登录时返回 401"""
        client.cookies.clear()
        resp = client.post("/api/semantic-maintenance/publish-logs/1/rollback", json={})
        assert resp.status_code == 401

    def test_rollback_non_admin_forbidden(self, analyst_client: TestClient):
        """analyst 角色尝试回滚返回 403"""
        resp = analyst_client.post(
            "/api/semantic-maintenance/publish-logs/1/rollback",
            json={}
        )
        assert resp.status_code == 403

    def test_rollback_nonexistent_log_returns_404(self, admin_client: TestClient):
        """回滚不存在的日志返回 404"""
        resp = admin_client.post(
            "/api/semantic-maintenance/publish-logs/999999/rollback",
            json={}
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data.get("detail", {}).get("error_code") == "SM_020"

    def test_rollback_invalid_status_returns_409(self, admin_client: TestClient, db_session):
        """回滚非 success 状态返回 409"""
        # 创建一个 FAILED 状态的日志
        log = _create_datasource_log(db_session, status=PublishStatus.FAILED)
        db_session.flush()

        resp = admin_client.post(
            f"/api/semantic-maintenance/publish-logs/{log.id}/rollback",
            json={}
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data.get("detail", {}).get("error_code") == "SM_027"

    def test_rollback_success_response(self, admin_client: TestClient, db_session):
        """成功回滚返回 200 和正确结构"""
        # 创建数据源 + 成功日志
        ds = _create_datasource_semantics(
            db_session, ds_id=10,
            semantic_description="desc after publish",
        )
        log = _create_datasource_log(
            db_session, object_id=10, status=PublishStatus.SUCCESS,
            diff_json={"rollback": {"description": "old desc"}}
        )
        db_session.flush()

        resp = admin_client.post(
            f"/api/semantic-maintenance/publish-logs/{log.id}/rollback",
            json={}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["rollback_log_id"] > 0
        assert data["original_log_id"] == log.id
        assert "previous_version_snapshot" in data

    def test_rollback_with_connection_id(self, admin_client: TestClient, db_session):
        """带 connection_id 的回滚请求"""
        ds = _create_datasource_semantics(db_session, ds_id=11, connection_id=1)
        log = _create_datasource_log(
            db_session, object_id=11, connection_id=1, status=PublishStatus.SUCCESS,
            diff_json={"rollback": {"description": "old desc"}}
        )
        db_session.flush()

        resp = admin_client.post(
            f"/api/semantic-maintenance/publish-logs/{log.id}/rollback",
            json={"connection_id": 1}
        )
        assert resp.status_code == 200


# -------------------------------------------------------------------------
# 集成测试：发布 → 回滚 → 验证
# -------------------------------------------------------------------------

class TestPublishRollbackIntegration:
    """发布 → 回滚 → 验证字段/metric/status 恢复到前一版本"""

    def test_datasource_field_mapping_rollback(self, db_session):
        """
        场景：数据源 semantic_description 变更发布后回滚
        期望：semantic_description 恢复到发布前值
        """
        # 1. 发布前状态
        old_desc = "description before publish"
        ds = _create_datasource_semantics(
            db_session, ds_id=20,
            semantic_description=old_desc,
        )

        # 2. 模拟发布：更新为新值
        ds.semantic_description = "description after publish"
        db_session.commit()

        # 3. 创建发布日志（diff 记录了发布前的值）
        log = _create_datasource_log(
            db_session, object_id=20, status=PublishStatus.SUCCESS,
            diff_json={
                "description": {"tableau": old_desc, "mulan": "description after publish"},
                "rollback": {"description": old_desc},
            }
        )
        db_session.flush()

        # 4. 执行回滚
        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log.id, operator=1)

        # 5. 验证
        assert err is None
        assert result["status"] == "success"

        # 验证数据源语义已恢复到发布前
        db_session.expire_all()
        ds_restored = db_session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.id == 20
        ).first()
        assert ds_restored.semantic_description == old_desc

    def test_field_metric_definition_rollback(self, db_session):
        """
        场景：字段 metric_definition 变更发布后回滚
        期望：metric_definition 恢复到发布前值
        """
        # 1. 发布前状态
        old_metric = "metric before publish"
        field = _create_field_semantics(
            db_session, field_id=30,
            metric_definition=old_metric,
        )

        # 2. 模拟发布：更新为新值
        field.metric_definition = "metric after publish"
        db_session.commit()

        # 3. 创建发布日志
        log = _create_field_log(
            db_session, object_id=30, status=PublishStatus.SUCCESS,
            diff_json={
                "metric_definition": {"tableau": old_metric, "mulan": "metric after publish"},
                "rollback": {"metric_definition": old_metric},
            }
        )
        db_session.flush()

        # 4. 执行回滚
        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log.id, operator=1)

        # 5. 验证
        assert err is None
        db_session.expire_all()
        field_restored = db_session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.id == 30
        ).first()
        assert field_restored.metric_definition == old_metric

    def test_status_rollback(self, db_session):
        """
        场景：datasource status 变更发布后回滚
        期望：status 恢复到发布前值
        """
        # 1. 发布前状态
        old_status = SemanticStatus.APPROVED
        ds = _create_datasource_semantics(
            db_session, ds_id=40,
            status=old_status,
        )

        # 2. 模拟发布：更新为新值
        ds.status = SemanticStatus.PUBLISHED
        db_session.commit()

        # 3. 创建发布日志
        log = _create_datasource_log(
            db_session, object_id=40, status=PublishStatus.SUCCESS,
            diff_json={
                "status": {"tableau": old_status, "mulan": SemanticStatus.PUBLISHED},
                "rollback": {"status": old_status},
            }
        )
        db_session.flush()

        # 4. 执行回滚
        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log.id, operator=1)

        # 5. 验证
        assert err is None
        db_session.expire_all()
        ds_restored = db_session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.id == 40
        ).first()
        assert ds_restored.status == old_status

    def test_rollback_log_has_action_and_snapshot(self, db_session):
        """
        验证回滚日志包含 action='rollback' 和 previous_version_snapshot
        """
        ds = _create_datasource_semantics(db_session, ds_id=50)
        log = _create_datasource_log(
            db_session, object_id=50, status=PublishStatus.SUCCESS,
            diff_json={"rollback": {"description": "old"}}
        )
        db_session.flush()

        svc = RollbackService()
        result, err = svc.execute_rollback(log_id=log.id, operator=1)
        assert err is None

        # 验证回滚日志的 action 和 snapshot
        db_session.expire_all()
        rollback_log = db_session.query(TableauPublishLog).filter(
            TableauPublishLog.id == result["rollback_log_id"]
        ).first()
        assert rollback_log is not None
        assert rollback_log.action == "rollback"
        assert rollback_log.previous_version_snapshot is not None
        assert isinstance(rollback_log.previous_version_snapshot, dict)
