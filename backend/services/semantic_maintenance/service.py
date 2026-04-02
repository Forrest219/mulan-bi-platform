"""语义维护模块 - 业务逻辑层"""
import json
import logging
from typing import Dict, Any, Optional, List

from .database import SemanticMaintenanceDatabase
from .models import (
    SemanticStatus,
    SemanticSource,
    SensitivityLevel,
)

logger = logging.getLogger(__name__)


class SemanticMaintenanceService:
    """语义维护业务逻辑服务"""

    def __init__(self, db_path: str = None):
        self.db = SemanticMaintenanceDatabase(db_path=db_path)

    # ============================================================
    # 数据源语义
    # ============================================================

    def get_or_create_datasource_semantics(
        self,
        connection_id: int,
        tableau_datasource_id: str,
        user_id: int = None,
        initial_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """获取或创建数据源语义记录"""
        existing = self.db.get_datasource_semantics(connection_id, tableau_datasource_id)
        if existing:
            return existing.to_dict()

        data = initial_data or {}
        obj = self.db.upsert_datasource_semantics(
            connection_id=connection_id,
            tableau_datasource_id=tableau_datasource_id,
            user_id=user_id,
            **data
        )
        return obj.to_dict()

    def update_datasource_semantics(
        self,
        ds_id: int,
        user_id: int = None,
        **fields
    ) -> tuple:
        """更新数据源语义字段"""
        ds = self.db.get_datasource_semantics_by_id(ds_id)
        if not ds:
            return False, "记录不存在"

        # 如果更新了 source 以外的字段，标记 source 为 manual
        updatable = {
            "semantic_name", "semantic_name_zh", "semantic_description",
            "business_definition", "usage_scenarios", "owner", "steward",
            "sensitivity_level", "tags_json",
        }
        has_manual_edit = any(k in updatable and k in fields for k in fields)
        if has_manual_edit:
            fields["source"] = SemanticSource.MANUAL

        success = self.db.update_datasource_semantics(ds_id, user_id=user_id, change_reason="manual_update", **fields)
        if not success:
            return False, "更新失败"
        updated = self.db.get_datasource_semantics_by_id(ds_id)
        return True, updated.to_dict()

    def submit_datasource_for_review(self, ds_id: int, user_id: int = None) -> tuple:
        """提交数据源语义审核（draft/ai_generated → reviewed）"""
        return self.db.transition_datasource_status(ds_id, SemanticStatus.REVIEWED, user_id)

    def approve_datasource(self, ds_id: int, user_id: int = None) -> tuple:
        """审核通过数据源语义（reviewed → approved）"""
        return self.db.transition_datasource_status(ds_id, SemanticStatus.APPROVED, user_id)

    def reject_datasource(self, ds_id: int, user_id: int = None, reason: str = None) -> tuple:
        """驳回数据源语义（reviewed → rejected → draft）"""
        success, err = self.db.transition_datasource_status(ds_id, SemanticStatus.REJECTED, user_id)
        if not success:
            return success, err
        # rejected → draft 由前端引导，这里只处理到 rejected
        return True, None

    def list_datasource_semantics(
        self,
        connection_id: int,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        items, total = self.db.list_datasource_semantics(
            connection_id, status=status, page=page, page_size=page_size
        )
        return [item.to_dict() for item in items], total

    def get_datasource_semantic_history(self, ds_id: int) -> List[Dict[str, Any]]:
        """获取数据源语义版本历史"""
        ds = self.db.get_datasource_semantics_by_id(ds_id)
        if not ds:
            return []
        versions = self.db.get_datasource_semantic_history(ds.id)
        return [v.to_dict() for v in versions]

    def rollback_datasource_semantic(
        self, ds_id: int, version_id: int, user_id: int = None
    ) -> tuple:
        """回滚数据源语义到指定版本"""
        success, err = self.db.rollback_datasource_semantic(ds_id, version_id, user_id)
        if not success:
            return False, err
        updated = self.db.get_datasource_semantics_by_id(ds_id)
        return True, updated.to_dict()

    # ============================================================
    # 字段语义
    # ============================================================

    def get_or_create_field_semantics(
        self,
        connection_id: int,
        tableau_field_id: str,
        field_registry_id: int = None,
        user_id: int = None,
        initial_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """获取或创建字段语义记录"""
        if field_registry_id:
            existing = self.db.get_field_semantics_by_reg_id(field_registry_id)
            if existing:
                return existing.to_dict()

        from semantic_maintenance.models import TableauFieldSemantics
        existing = self.db.session.query(TableauFieldSemantics).filter(
            TableauFieldSemantics.connection_id == connection_id,
            TableauFieldSemantics.tableau_field_id == tableau_field_id,
        ).first()
        if existing:
            return existing.to_dict()

        data = initial_data or {}
        if field_registry_id is not None:
            obj = self.db.upsert_field_semantics_by_reg_id(
                field_registry_id=field_registry_id,
                connection_id=connection_id,
                tableau_field_id=tableau_field_id,
                user_id=user_id,
                **data
            )
        else:
            obj = self.db.upsert_field_semantics(
                connection_id=connection_id,
                tableau_field_id=tableau_field_id,
                user_id=user_id,
                **data
            )
        return obj.to_dict()

    def update_field_semantics(
        self,
        field_id: int,
        user_id: int = None,
        change_reason: str = None,
        **fields
    ) -> tuple:
        """更新字段语义（创建版本快照）"""
        field = self.db.get_field_semantics_by_id(field_id)
        if not field:
            return False, "记录不存在"

        # 手动编辑标记 source 为 manual
        updatable = {
            "semantic_name", "semantic_name_zh", "semantic_definition",
            "metric_definition", "dimension_definition", "unit",
            "enum_desc_json", "tags_json", "synonyms_json",
            "sensitivity_level", "is_core_field",
        }
        has_manual_edit = any(k in updatable and k in fields for k in fields)
        if has_manual_edit:
            fields["source"] = SemanticSource.MANUAL

        success = self.db.update_field_semantics(
            field_id, user_id=user_id, change_reason=change_reason or "manual_update", **fields
        )
        if not success:
            return False, "更新失败"
        updated = self.db.get_field_semantics_by_id(field_id)
        return True, updated.to_dict()

    def submit_field_for_review(self, field_id: int, user_id: int = None) -> tuple:
        """提交字段语义审核"""
        return self.db.transition_field_status(field_id, SemanticStatus.REVIEWED, user_id)

    def approve_field(self, field_id: int, user_id: int = None) -> tuple:
        """审核通过字段语义"""
        return self.db.transition_field_status(field_id, SemanticStatus.APPROVED, user_id)

    def reject_field(self, field_id: int, user_id: int = None) -> tuple:
        """驳回字段语义"""
        return self.db.transition_field_status(field_id, SemanticStatus.REJECTED, user_id)

    def list_field_semantics(
        self,
        connection_id: int,
        ds_id: int = None,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        items, total = self.db.list_field_semantics(
            connection_id, ds_id=ds_id, status=status, page=page, page_size=page_size
        )
        return [item.to_dict() for item in items], total

    def get_field_semantic_history(self, field_id: int) -> List[Dict[str, Any]]:
        """获取字段语义版本历史"""
        field = self.db.get_field_semantics_by_id(field_id)
        if not field:
            return []
        versions = self.db.get_field_semantic_history(field.id)
        return [v.to_dict() for v in versions]

    def rollback_field_semantic(
        self, field_id: int, version_id: int, user_id: int = None
    ) -> tuple:
        """回滚字段语义到指定版本"""
        success, err = self.db.rollback_field_semantic(field_id, version_id, user_id)
        if not success:
            return False, err
        updated = self.db.get_field_semantics_by_id(field_id)
        return True, updated.to_dict()

    # ============================================================
    # AI 语义生成（Phase 1）
    # ============================================================

    def generate_ai_draft_datasource(
        self, ds_id: int, user_id: int = None,
        ds_name: str = None, description: str = None,
        field_context: List[Dict] = None,
    ) -> tuple:
        """AI 生成数据源语义草稿"""
        try:
            from services.llm.service import LLMService
        except ImportError:
            return False, "LLM 服务未配置"

        ds = self.db.get_datasource_semantics_by_id(ds_id)
        if not ds:
            return False, "记录不存在"

        # 构建字段上下文文本
        field_text = ""
        if field_context:
            field_lines = []
            for f in field_context:
                name = f.get("field_name", "")
                caption = f.get("field_caption", "")
                role = f.get("role", "")
                dtype = f.get("data_type", "")
                formula = f.get("formula", "")
                line = f"- {name}"
                if caption:
                    line += f" ({caption})"
                line += f" [{dtype}] [{role}]"
                if formula:
                    line += f" 公式: {formula}"
                field_lines.append(line)
            field_text = "\n".join(field_lines)

        prompt = f"""你是一个 BI 数据语义专家。请为以下数据源生成业务语义建议。

## 数据源信息
名称：{ds_name or ds.tableau_datasource_id}
描述：{description or ds.semantic_description or '无'}
现有语义名：{ds.semantic_name or '无'}
现有中文名：{ds.semantic_name_zh or '无'}

## 字段列表
{field_text or '无字段信息'}

请以 JSON 格式输出语义建议，包含以下字段：
- semantic_name: 英文语义名
- semantic_name_zh: 中文语义名（必填）
- semantic_description: 语义描述（必填）
- business_definition: 业务定义
- owner: 责任人建议
- sensitivity_level: 敏感级别（low/medium/high/confidential）
- tags_json: JSON 格式标签数组
- ai_confidence: AI 置信度 0~1

只输出 JSON，不要有其他文字。"""

        try:
            llm = LLMService()
            result = llm.complete(prompt, system="你是一个专业的 BI 数据语义专家。", timeout=30)
        except Exception as e:
            return False, f"LLM 调用失败: {e}"

        if "error" in result:
            return False, result["error"]

        content = result["content"].strip()
        # 尝试提取 JSON
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        try:
            import json as _json
            parsed = _json.loads(content)
        except Exception:
            return False, f"AI 返回格式异常（非 JSON）：{content[:200]}"

        # 更新记录
        self.db.update_datasource_semantics(
            ds_id,
            user_id=user_id,
            change_reason="ai_generated",
            semantic_name=parsed.get("semantic_name"),
            semantic_name_zh=parsed.get("semantic_name_zh"),
            semantic_description=parsed.get("semantic_description"),
            business_definition=parsed.get("business_definition"),
            owner=parsed.get("owner"),
            sensitivity_level=parsed.get("sensitivity_level"),
            tags_json=_json.dumps(parsed.get("tags_json", []), ensure_ascii=False) if parsed.get("tags_json") else None,
            status=SemanticStatus.AI_GENERATED,
            source=SemanticSource.AI,
        )
        updated = self.db.get_datasource_semantics_by_id(ds_id)
        return True, updated.to_dict()

    def generate_ai_draft_field(
        self, field_id: int, user_id: int = None,
        field_name: str = None, data_type: str = None,
        role: str = None, formula: str = None,
        enum_values: List[str] = None,
    ) -> tuple:
        """AI 生成字段语义草稿"""
        try:
            from services.llm.service import LLMService
        except ImportError:
            return False, "LLM 服务未配置"

        field = self.db.get_field_semantics_by_id(field_id)
        if not field:
            return False, "记录不存在"

        enum_text = ""
        if enum_values:
            enum_text = "\n".join([f"- {v}" for v in enum_values[:20]])

        prompt = f"""你是一个 BI 字段语义专家。请为以下字段生成语义建议。

## 字段信息
字段名：{field_name or field.tableau_field_id}
数据类型：{data_type or field.data_type or '未知'}
角色：{role or field.role or '未知'}
公式：{formula or field.formula or '无'}
现有语义名：{field.semantic_name or '无'}
现有中文名：{field.semantic_name_zh or '无'}
枚举值示例：\n{enum_text or '无'}

请以 JSON 格式输出语义建议：
- semantic_name: 英文语义名
- semantic_name_zh: 中文语义名（必填）
- semantic_definition: 语义定义（必填）
- metric_definition: 指标口径（若为 measure 字段必填）
- dimension_definition: 维度解释（若为 dimension 字段必填）
- unit: 单位（如金额、百分比、人次等）
- synonyms_json: JSON 同义词数组
- sensitivity_level: 敏感级别（low/medium/high/confidential）
- is_core_field: 是否为核心字段（true/false）
- ai_confidence: AI 置信度 0~1
- tags_json: JSON 标签数组

只输出 JSON，不要有其他文字。"""

        try:
            llm = LLMService()
            result = llm.complete(prompt, system="你是一个专业的 BI 字段语义专家。", timeout=30)
        except Exception as e:
            return False, f"LLM 调用失败: {e}"

        if "error" in result:
            return False, result["error"]

        content = result["content"].strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        try:
            import json as _json
            parsed = _json.loads(content)
        except Exception:
            return False, f"AI 返回格式异常（非 JSON）：{content[:200]}"

        self.db.update_field_semantics(
            field_id,
            user_id=user_id,
            change_reason="ai_generated",
            semantic_name=parsed.get("semantic_name"),
            semantic_name_zh=parsed.get("semantic_name_zh"),
            semantic_definition=parsed.get("semantic_definition"),
            metric_definition=parsed.get("metric_definition"),
            dimension_definition=parsed.get("dimension_definition"),
            unit=parsed.get("unit"),
            synonyms_json=_json.dumps(parsed.get("synonyms_json", []), ensure_ascii=False) if parsed.get("synonyms_json") else None,
            tags_json=_json.dumps(parsed.get("tags_json", []), ensure_ascii=False) if parsed.get("tags_json") else None,
            sensitivity_level=parsed.get("sensitivity_level"),
            is_core_field=parsed.get("is_core_field", False),
            ai_confidence=parsed.get("ai_confidence"),
            status=SemanticStatus.AI_GENERATED,
            source=SemanticSource.AI,
        )
        updated = self.db.get_field_semantics_by_id(field_id)
        return True, updated.to_dict()

    # ============================================================
    # 发布日志
    # ============================================================

    def list_publish_logs(
        self,
        connection_id: int,
        object_type: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        items, total = self.db.list_publish_logs(
            connection_id, object_type=object_type, status=status,
            page=page, page_size=page_size
        )
        return [item.to_dict() for item in items], total

    def get_publish_log(self, log_id: int) -> Optional[Dict[str, Any]]:
        log = self.db.get_publish_log(log_id)
        return log.to_dict() if log else None
