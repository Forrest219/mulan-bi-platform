"""
语义维护模块 - 回滚服务 (Spec 19)

提供针对 sm_publish_log 的完整回滚能力：
- field_mapping 变更回滚 → 恢复旧映射
- metric_definition 变更回滚 → 恢复旧定义
- status 变更回滚 → 恢复旧 status

回滚前快照当前状态到 previous_version_snapshot，
回滚后记录 action='rollback' 到 sm_publish_log。
"""
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from app.core.database import SessionLocal

from .models import (
    PublishStatus,
    SemanticStatus,
    TableauDatasourceSemantics,
    TableauFieldSemantics,
    TableauPublishLog,
)
from .database import SemanticMaintenanceDatabase

logger = logging.getLogger(__name__)


class RollbackService:
    """发布日志回滚服务"""

    def __init__(self):
        self.db = SemanticMaintenanceDatabase()

    def _get_session(self):
        return SessionLocal()

    def get_publish_log(self, log_id: int) -> Optional[TableauPublishLog]:
        """获取发布日志"""
        session = self._get_session()
        try:
            return session.query(TableauPublishLog).filter(
                TableauPublishLog.id == log_id
            ).first()
        finally:
            session.close()

    def get_current_object_state(self, log: TableauPublishLog) -> Dict[str, Any]:
        """
        根据 log 的 object_type 和 object_id 获取当前状态的快照。
        用于回滚前保存现场。
        """
        session = self._get_session()
        try:
            if log.object_type == "datasource":
                obj = session.query(TableauDatasourceSemantics).filter(
                    TableauDatasourceSemantics.id == log.object_id
                ).first()
                if obj:
                    return {
                        "semantic_name": obj.semantic_name,
                        "semantic_name_zh": obj.semantic_name_zh,
                        "semantic_description": obj.semantic_description,
                        "business_definition": obj.business_definition,
                        "usage_scenarios": obj.usage_scenarios,
                        "owner": obj.owner,
                        "steward": obj.steward,
                        "sensitivity_level": obj.sensitivity_level,
                        "status": obj.status,
                        "tags_json": obj.tags_json,
                        "published_to_tableau": obj.published_to_tableau,
                    }
            elif log.object_type == "field":
                obj = session.query(TableauFieldSemantics).filter(
                    TableauFieldSemantics.id == log.object_id
                ).first()
                if obj:
                    return {
                        "semantic_name": obj.semantic_name,
                        "semantic_name_zh": obj.semantic_name_zh,
                        "semantic_definition": obj.semantic_definition,
                        "metric_definition": obj.metric_definition,
                        "dimension_definition": obj.dimension_definition,
                        "unit": obj.unit,
                        "enum_desc_json": obj.enum_desc_json,
                        "tags_json": obj.tags_json,
                        "synonyms_json": obj.synonyms_json,
                        "sensitivity_level": obj.sensitivity_level,
                        "is_core_field": obj.is_core_field,
                        "status": obj.status,
                        "published_to_tableau": obj.published_to_tableau,
                    }
            return {}
        finally:
            session.close()

    def can_rollback(self, log: TableauPublishLog) -> Tuple[bool, str]:
        """
        验证当前状态是否允许回滚。
        非 deprecated 等 terminal 状态可回滚。
        """
        # 可回滚的状态：success
        if log.status == PublishStatus.SUCCESS:
            return True, ""
        # 已回滚的不能再回滚
        if log.status == PublishStatus.ROLLED_BACK:
            return False, f"该发布日志已回滚（status={log.status}）"
        # pending / failed / not_supported 状态不允许回滚
        return False, f"只有 success 状态的发布日志可回滚，当前状态：{log.status}"

    def determine_rollback_type(self, log: TableauPublishLog) -> str:
        """
        根据 diff_json 内容判断回滚类型：
        - field_mapping 变更 → 恢复旧映射
        - metric_definition 变更 → 恢复旧定义
        - status 变更 → 恢复旧status
        """
        if not log.diff_json:
            return "unknown"

        diff = log.diff_json if isinstance(log.diff_json, dict) else {}

        # 判断是否包含字段映射相关变更
        field_mapping_keys = {"caption", "description"}
        metric_keys = {"metric_definition"}
        status_keys = {"status"}

        diff_keys = set(diff.keys())

        # 移除 rollback 嵌套
        if "rollback" in diff_keys:
            diff_keys = diff_keys - {"rollback"}
            rollback_keys = set(diff.get("rollback", {}).keys()) if isinstance(diff.get("rollback"), dict) else set()
            if rollback_keys & field_mapping_keys:
                return "field_mapping"
            if rollback_keys & metric_keys:
                return "metric_definition"
            if rollback_keys & status_keys:
                return "status"

        if diff_keys & field_mapping_keys:
            return "field_mapping"
        if diff_keys & metric_keys:
            return "metric_definition"
        if diff_keys & status_keys:
            return "status"

        return "unknown"

    def execute_rollback(
        self,
        log_id: int,
        operator: int = None,
        connection_id: int = None,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        执行回滚操作。

        流程：
        1. 验证发布日志存在
        2. 验证当前状态允许回滚
        3. 快照当前状态到 previous_version_snapshot
        4. 根据 rollback_type 恢复字段/metric/status
        5. 创建 rollback 发布日志（action='rollback'）
        6. 更新原日志状态为 ROLLED_BACK

        Returns: (result_dict, error_message)
        """
        session = self._get_session()
        try:
            # Step 1: 获取发布日志
            log = session.query(TableauPublishLog).filter(
                TableauPublishLog.id == log_id
            ).first()

            if not log:
                return {}, "发布日志不存在"

            # connection_id 校验
            if connection_id is not None and log.connection_id != connection_id:
                return {}, "连接 ID 不匹配"

            # Step 2: 状态验证
            can_rollback, reason = self.can_rollback(log)
            if not can_rollback:
                return {}, reason

            # Step 3: 快照当前状态
            current_state = self._get_current_object_state_from_session(log, session)
            previous_version_snapshot = json.dumps(current_state, ensure_ascii=False) if current_state else "{}"

            # Step 4: 解析 diff，执行回滚
            rollback_type = self.determine_rollback_type(log)

            if log.object_type == "datasource":
                success, err = self._rollback_datasource(log, session)
            elif log.object_type == "field":
                success, err = self._rollback_field(log, session)
            else:
                return {}, f"未知对象类型: {log.object_type}"

            if not success:
                return {}, err

            # Step 5: 创建回滚日志
            diff_for_rollback = log.diff_json
            if isinstance(diff_for_rollback, dict) and "rollback" not in diff_for_rollback:
                diff_for_rollback = {"rollback": diff_for_rollback}

            rollback_log = TableauPublishLog(
                connection_id=log.connection_id,
                object_type=log.object_type,
                object_id=log.object_id,
                tableau_object_id=log.tableau_object_id,
                diff_json=diff_for_rollback,
                publish_payload_json=log.publish_payload_json,
                status=PublishStatus.SUCCESS,
                response_summary=f"回滚成功（类型：{rollback_type}）",
                operator=operator,
                action="rollback",
                previous_version_snapshot=json.loads(previous_version_snapshot) if previous_version_snapshot != "{}" else {},
            )
            session.add(rollback_log)

            # Step 6: 更新原日志状态
            log.status = PublishStatus.ROLLED_BACK
            log.response_summary = f"已被 log_id={rollback_log.id} 回滚"

            session.commit()

            return {
                "rollback_log_id": rollback_log.id,
                "original_log_id": log_id,
                "rollback_type": rollback_type,
                "previous_version_snapshot": json.loads(previous_version_snapshot) if previous_version_snapshot != "{}" else {},
                "status": "success",
                "message": "回滚成功",
            }, None

        except Exception as e:
            session.rollback()
            logger.error("execute_rollback exception: log_id=%s, error=%s", log_id, e, exc_info=True)
            return {}, f"回滚异常: {e}"
        finally:
            session.close()

    def _get_current_object_state_from_session(
        self, log: TableauPublishLog, session
    ) -> Dict[str, Any]:
        """从给定 session 获取当前对象状态（用于快照）"""
        if log.object_type == "datasource":
            obj = session.query(TableauDatasourceSemantics).filter(
                TableauDatasourceSemantics.id == log.object_id
            ).first()
            if obj:
                return {
                    "semantic_name": obj.semantic_name,
                    "semantic_name_zh": obj.semantic_name_zh,
                    "semantic_description": obj.semantic_description,
                    "business_definition": obj.business_definition,
                    "usage_scenarios": obj.usage_scenarios,
                    "owner": obj.owner,
                    "steward": obj.steward,
                    "sensitivity_level": obj.sensitivity_level,
                    "status": obj.status,
                    "tags_json": obj.tags_json,
                    "published_to_tableau": obj.published_to_tableau,
                }
        elif log.object_type == "field":
            obj = session.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.id == log.object_id
            ).first()
            if obj:
                return {
                    "semantic_name": obj.semantic_name,
                    "semantic_name_zh": obj.semantic_name_zh,
                    "semantic_definition": obj.semantic_definition,
                    "metric_definition": obj.metric_definition,
                    "dimension_definition": obj.dimension_definition,
                    "unit": obj.unit,
                    "enum_desc_json": obj.enum_desc_json,
                    "tags_json": obj.tags_json,
                    "synonyms_json": obj.synonyms_json,
                    "sensitivity_level": obj.sensitivity_level,
                    "is_core_field": obj.is_core_field,
                    "status": obj.status,
                    "published_to_tableau": obj.published_to_tableau,
                }
        return {}

    def _rollback_datasource(
        self, log: TableauPublishLog, session
    ) -> Tuple[bool, Optional[str]]:
        """回滚数据源语义"""
        if not log.diff_json:
            return False, "无差异记录，无法回滚"

        diff = log.diff_json
        if isinstance(diff, str):
            try:
                diff = json.loads(diff)
            except json.JSONDecodeError:
                return False, "差异数据损坏"

        # 逆向 diff
        rollback_data = diff.get("rollback", {}) if isinstance(diff, dict) else diff

        ds = session.query(TableauDatasourceSemantics).filter(
            TableauDatasourceSemantics.id == log.object_id
        ).first()

        if not ds:
            return False, "数据源语义记录不存在"

        # 恢复字段
        restored_fields = {}
        for key, tableau_val in rollback_data.items():
            if hasattr(ds, key):
                old_val = getattr(ds, key)
                setattr(ds, key, tableau_val)
                restored_fields[key] = {"from": old_val, "to": tableau_val}
                logger.info("Datasource rollback: %s: %s -> %s", key, old_val, tableau_val)

        session.commit()
        return True, None

    def _rollback_field(
        self, log: TableauPublishLog, session
    ) -> Tuple[bool, Optional[str]]:
        """回滚字段语义"""
        if not log.diff_json:
            return False, "无差异记录，无法回滚"

        diff = log.diff_json
        if isinstance(diff, str):
            try:
                diff = json.loads(diff)
            except json.JSONDecodeError:
                return False, "差异数据损坏"

        rollback_data = diff.get("rollback", {}) if isinstance(diff, dict) else diff

        field = session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.id == log.object_id
        ).first()

        if not field:
            return False, "字段语义记录不存在"

        restored_fields = {}
        for key, tableau_val in rollback_data.items():
            if hasattr(field, key):
                old_val = getattr(field, key)
                setattr(field, key, tableau_val)
                restored_fields[key] = {"from": old_val, "to": tableau_val}
                logger.info("Field rollback: %s: %s -> %s", key, old_val, tableau_val)

        session.commit()
        return True, None


# 导出便捷函数
def rollback_publish_log(
    log_id: int,
    operator: int = None,
    connection_id: int = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """执行发布日志回滚的便捷函数"""
    service = RollbackService()
    return service.execute_rollback(log_id, operator, connection_id)
