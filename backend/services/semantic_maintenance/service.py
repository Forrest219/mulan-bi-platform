"""语义维护模块 - 业务逻辑层（Spec 12 §2.2 边界）"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, List

from .database import SemanticMaintenanceDatabase
from .models import (
    SemanticStatus,
    SemanticSource,
    SensitivityLevel,
)
from .context_assembler import (
    ContextAssembler,
    BLOCKED_FOR_LLM,
    sanitize_fields_for_llm,
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
    # AI 语义生成（Spec 12 §5 — ContextAssembler 驱动）
    # ============================================================

    def _pre_llm_sensitivity_check(
        self,
        sensitivity_level: str = None,
        is_datasource: bool = False,
    ) -> Optional[str]:
        """
        LLM 调用前置敏感度检查（Spec 12 §9.1 / SLI_005）。

        Returns:
            None 表示通过检查；返回错误消息字符串表示不通过。
        """
        if sensitivity_level is None:
            return None
        level = sensitivity_level.lower()
        if level in BLOCKED_FOR_LLM:
            obj_type = "数据源" if is_datasource else "字段"
            return f"SLI_005: 敏感级别为 {level} 的{obj_type}禁止 AI 处理"
        return None

    def _parse_llm_json_response(self, content: str) -> Dict[str, Any]:
        """
        解析 LLM 返回内容中的 JSON（Spec 12 §7.2）。

        支持 ``` 代码块包裹格式。重试策略在调用方处理。
        """
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(content)

    def generate_ai_draft_datasource(
        self, ds_id: int, user_id: int = None,
        ds_name: str = None, description: str = None,
        field_context: List[Dict] = None,
    ) -> tuple:
        """AI 生成数据源语义草稿（Spec 12 §5）"""
        try:
            from services.llm.service import LLMService
            from services.llm.prompts import AI_SEMANTIC_DS_TEMPLATE
        except ImportError:
            return False, "LLM 服务未配置"

        ds = self.db.get_datasource_semantics_by_id(ds_id)
        if not ds:
            return False, "记录不存在"

        # §9.1 SLI_005 前置敏感度检查
        sensitivity_err = self._pre_llm_sensitivity_check(
            getattr(ds, "sensitivity_level", None),
            is_datasource=True,
        )
        if sensitivity_err:
            return False, sensitivity_err

        # §3 上下文组装：使用 ContextAssembler
        assembler = ContextAssembler()

        # field_context 净化（移除 HIGH/CONFIDENTIAL 字段）
        sanitized_fields = assembler.sanitize_fields(field_context or [])

        # 构建字段上下文（序列化 + 截断）
        field_context_text = assembler.build_field_context(sanitized_fields)

        prompt = AI_SEMANTIC_DS_TEMPLATE.format(
            ds_name=ds_name or ds.tableau_datasource_id,
            description=description or ds.semantic_description or "无",
            existing_semantic_name=ds.semantic_name or "无",
            existing_semantic_name_zh=ds.semantic_name_zh or "无",
            field_context=field_context_text,
        )
        system = "你是一个专业的 BI 数据语义专家。"

        try:
            llm = LLMService()
            # v1.2 §4.2: 强制 temperature=0.1，OpenAI 启用 json_object 响应格式
            # 使用 asyncio.run() 桥接异步 LLM 调用（service 层保持同步接口）
            result = asyncio.run(llm.complete_for_semantic(prompt, system=system, timeout=30))
        except Exception as e:
            return False, f"LLM 调用失败: {e}"

        if "error" in result:
            return False, result["error"]

        # JSON 解析 + v1.2 §6.2 重试策略：首次失败追加错误反馈重试 1 次
        try:
            parsed = self._parse_llm_json_response(result["content"].strip())
        except json.JSONDecodeError as first_err:
            # 重试 1 次：追加 JSON 解析错误反馈
            retry_prompt = (
                f"{prompt}\n\n"
                f"[修正要求] 你上次生成的格式有误，JSON 解析报错信息为：{first_err.msg}。"
                f"请严格按照 JSON 规范重新生成，不要包含任何 Markdown 标记（如 ```json），只输出纯 JSON。"
            )
            result_retry = asyncio.run(llm.complete_for_semantic(retry_prompt, system=system, timeout=30))
            if "error" in result_retry:
                return False, result_retry["error"]
            try:
                parsed = self._parse_llm_json_response(result_retry["content"].strip())
            except json.JSONDecodeError:
                return False, "AI 返回格式异常（重试后仍非有效 JSON）"

        # 写入语义记录
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
            tags_json=json.dumps(parsed.get("tags_json", []), ensure_ascii=False) if parsed.get("tags_json") else None,
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
        """AI 生成字段语义草稿（Spec 12 §5）"""
        try:
            from services.llm.service import LLMService
            from services.llm.prompts import AI_SEMANTIC_FIELD_TEMPLATE
        except ImportError:
            return False, "LLM 服务未配置"

        field = self.db.get_field_semantics_by_id(field_id)
        if not field:
            return False, "记录不存在"

        # §9.1 SLI_005 前置敏感度检查
        sensitivity_err = self._pre_llm_sensitivity_check(
            getattr(field, "sensitivity_level", None),
            is_datasource=False,
        )
        if sensitivity_err:
            return False, sensitivity_err

        # 枚举值截断（Spec 12 §5.1：最多 20 个）
        enum_text = "\n".join([f"- {v}" for v in (enum_values or [])[:20]]) or "无"

        # 组装字段元数据（传入 AI_SEMANTIC_FIELD_TEMPLATE 所需的格式）
        # 注意：field_context 由 API 调用方构造后传入
        # 此处直接构建 prompt，使用 ContextAssembler 净化字段（如果 API 传入了字段上下文）
        # 但 generate_ai_draft_field 主要接收单个字段信息，field_context 不适用
        prompt = AI_SEMANTIC_FIELD_TEMPLATE.format(
            field_name=field_name or field.tableau_field_id,
            data_type=data_type or getattr(field, "data_type", "未知"),
            role=role or getattr(field, "role", "未知"),
            formula=formula or getattr(field, "formula", "无"),
            existing_semantic_name=field.semantic_name or "无",
            existing_semantic_name_zh=field.semantic_name_zh or "无",
            enum_values=enum_text,
        )
        system = "你是一个专业的 BI 字段语义专家。"

        try:
            llm = LLMService()
            # v1.2 §4.2: 强制 temperature=0.1，OpenAI 启用 json_object 响应格式
            result = asyncio.run(llm.complete_for_semantic(prompt, system=system, timeout=30))
        except Exception as e:
            return False, f"LLM 调用失败: {e}"

        if "error" in result:
            return False, result["error"]

        # JSON 解析 + v1.2 §6.2 重试策略：首次失败追加错误反馈重试 1 次
        try:
            parsed = self._parse_llm_json_response(result["content"].strip())
        except json.JSONDecodeError as first_err:
            # 重试 1 次：追加 JSON 解析错误反馈
            retry_prompt = (
                f"{prompt}\n\n"
                f"[修正要求] 你上次生成的格式有误，JSON 解析报错信息为：{first_err.msg}。"
                f"请严格按照 JSON 规范重新生成，不要包含任何 Markdown 标记（如 ```json），只输出纯 JSON。"
            )
            result_retry = asyncio.run(llm.complete_for_semantic(retry_prompt, system=system, timeout=30))
            if "error" in result_retry:
                return False, result_retry["error"]
            try:
                parsed = self._parse_llm_json_response(result_retry["content"].strip())
            except json.JSONDecodeError:
                return False, "AI 返回格式异常（重试后仍非有效 JSON）"

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
            synonyms_json=json.dumps(parsed.get("synonyms_json", []), ensure_ascii=False) if parsed.get("synonyms_json") else None,
            tags_json=json.dumps(parsed.get("tags_json", []), ensure_ascii=False) if parsed.get("tags_json") else None,
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
