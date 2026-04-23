"""语义维护模块 - 业务逻辑层（Spec 12 §2.2 边界）"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
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
        """
        回滚数据源语义到指定版本（DB + REST 双重回滚）。

        注意：如果被回滚的版本曾经发布到 Tableau（published_to_tableau=True），
        则会自动触发 REST API 回滚，将 Tableau 侧的变更也一并撤销。
        """
        # 获取回滚前的 published_to_tableau 状态（用于判断是否需要 REST 回滚）
        ds_before = self.db.get_datasource_semantics_by_id(ds_id)
        was_published = ds_before.published_to_tableau if ds_before else False

        # Step 1: 如果曾发布到 Tableau，先执行 REST 回滚（Spec 09 §3.2.1 原子性要求）
        # REST 必须先于 DB 变更，失败时保持本地状态不变，避免数据裂脑
        if was_published and ds_before and ds_before.connection_id:
            rest_ok, rest_err = self._rollback_tableau_publish(ds_before, user_id)
            if not rest_ok:
                return False, f"Tableau REST 回滚失败，本地状态保持不变: {rest_err}"

        # Step 2: REST 成功（或无需 REST 回滚），执行 DB 层回滚
        success, err = self.db.rollback_datasource_semantic(ds_id, version_id, user_id)
        if not success:
            return False, err
        updated = self.db.get_datasource_semantics_by_id(ds_id)
        return True, updated.to_dict()

    def _rollback_tableau_publish(self, ds, user_id: int = None) -> tuple:
        """
        查询并回滚 Tableau REST API 发布记录。

        查找该数据源关联的最新一条 SUCCESS 状态的发布日志，
        调用 PublishService.rollback_publish() 撤销 Tableau 侧变更。

        Returns:
            (True, None) — 回滚成功或无需回滚（无发布日志）
            (False, "error") — 回滚失败
        """
        from .models import PublishStatus
        from services.tableau.models import TableauDatabase
        from app.core.crypto import get_tableau_crypto

        # 查找该数据源关联的最新 SUCCESS 发布日志
        logs, _ = self.db.list_publish_logs(
            connection_id=ds.connection_id,
            object_type="datasource",
            status=PublishStatus.SUCCESS,
            page=1,
            page_size=1,
        )
        if not logs:
            return True, None

        latest_log = logs[0]
        # 确保是该数据源的日志
        if latest_log.object_type != "datasource" or latest_log.object_id != ds.id:
            return True, None

        # 获取 Tableau 连接凭证
        tableau_db = TableauDatabase()
        try:
            conn = tableau_db.get_connection(ds.connection_id)
            if not conn or not conn.is_active:
                return False, f"Tableau 连接不可用（id={ds.connection_id}）"

            crypto = get_tableau_crypto()
            token_value = crypto.decrypt(conn.token_encrypted)

            # 实例化 PublishService 并执行回滚
            publish_svc = self._build_publish_service(
                server_url=conn.server_url,
                site_content_url=conn.site,
                token_name=conn.token_name,
                token_value=token_value,
                api_version=conn.api_version or "3.21",
            )
            try:
                if not publish_svc.connect():
                    return False, "Tableau REST 认证失败"
                result, err = publish_svc.rollback_publish(log_id=latest_log.id, operator=user_id)
                if err:
                    return False, err
                return True, None
            finally:
                publish_svc.disconnect()
        except Exception as e:
            logger.error("_rollback_tableau_publish 异常: %s", e, exc_info=True)
            return False, str(e)
        finally:
            tableau_db.session.close()

    def _build_publish_service(self, server_url: str, site_content_url: str,
                                token_name: str, token_value: str,
                                api_version: str) -> "PublishService":
        """构建 PublishService 实例（延迟导入避免循环依赖）"""
        from .publish_service import PublishService
        return PublishService(
            server_url=server_url,
            site_content_url=site_content_url,
            token_name=token_name,
            token_value=token_value,
            api_version=api_version,
        )

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
        """
        回滚字段语义到指定版本（DB + REST 双重回滚）。

        注意：如果被回滚的版本曾经发布到 Tableau（published_to_tableau=True），
        则会自动触发 REST API 回滚，将 Tableau 侧的变更也一并撤销。
        """
        # 获取回滚前的 published_to_tableau 状态（用于判断是否需要 REST 回滚）
        field_before = self.db.get_field_semantics_by_id(field_id)
        was_published = field_before.published_to_tableau if field_before else False

        # Step 1: 如果曾发布到 Tableau，先执行 REST 回滚（Spec 09 §3.2.1 原子性要求）
        if was_published and field_before and field_before.connection_id:
            rest_ok, rest_err = self._rollback_tableau_field_publish(field_before, user_id)
            if not rest_ok:
                return False, f"Tableau REST 回滚失败，本地状态保持不变: {rest_err}"

        # Step 2: REST 成功（或无需 REST 回滚），执行 DB 层回滚
        success, err = self.db.rollback_field_semantic(field_id, version_id, user_id)
        if not success:
            return False, err
        updated = self.db.get_field_semantics_by_id(field_id)
        return True, updated.to_dict()

    def _rollback_tableau_field_publish(self, field, user_id: int = None) -> tuple:
        """
        查询并回滚 Tableau REST API 字段发布记录。

        查找该字段关联的最新一条 SUCCESS 状态的发布日志，
        调用 PublishService.rollback_publish() 撤销 Tableau 侧变更。

        Returns:
            (True, None) — 回滚成功或无需回滚（无发布日志）
            (False, "error") — 回滚失败
        """
        from .models import PublishStatus
        from services.tableau.models import TableauDatabase
        from app.core.crypto import get_tableau_crypto

        # 查找该字段关联的最新 SUCCESS 发布日志
        logs, _ = self.db.list_publish_logs(
            connection_id=field.connection_id,
            object_type="field",
            status=PublishStatus.SUCCESS,
            page=1,
            page_size=1,
        )
        if not logs:
            return True, None

        latest_log = logs[0]
        if latest_log.object_type != "field" or latest_log.object_id != field.id:
            return True, None

        # 获取 Tableau 连接凭证
        tableau_db = TableauDatabase()
        try:
            conn = tableau_db.get_connection(field.connection_id)
            if not conn or not conn.is_active:
                return False, f"Tableau 连接不可用（id={field.connection_id}）"

            crypto = get_tableau_crypto()
            token_value = crypto.decrypt(conn.token_encrypted)

            publish_svc = self._build_publish_service(
                server_url=conn.server_url,
                site_content_url=conn.site,
                token_name=conn.token_name,
                token_value=token_value,
                api_version=conn.api_version or "3.21",
            )
            try:
                if not publish_svc.connect():
                    return False, "Tableau REST 认证失败"
                result, err = publish_svc.rollback_publish(log_id=latest_log.id, operator=user_id)
                if err:
                    return False, err
                return True, None
            finally:
                publish_svc.disconnect()
        except Exception as e:
            logger.error("_rollback_tableau_field_publish 异常: %s", e, exc_info=True)
            return False, str(e)
        finally:
            tableau_db.session.close()

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

    # ============================================================
    # 定时清理任务
    # ============================================================

    def cleanup_stale_reviews(self, stale_days: int = 7) -> Dict[str, Any]:
        """
        清理长期处于 reviewed 状态的记录（自动降级为 draft）。

        查询条件：
        - status = 'reviewed'
        - updated_at < now() - stale_days

        降级后记录 audit 日志（类型 = 'cleanup_stale_review'）。
        """
        from datetime import datetime, timedelta

        stale_threshold = datetime.now() - timedelta(days=stale_days)
        cleaned_datasources = 0
        cleaned_fields = 0

        try:
            cleaned_ds, cleaned_f = self._cleanup_stale_reviewed_sql(stale_threshold)
            cleaned_datasources = cleaned_ds
            cleaned_fields = cleaned_f
        except Exception as e:
            logger.error("清理 stale reviewed 记录失败: %s", e, exc_info=True)

        result = {
            "cleaned_datasources": cleaned_datasources,
            "cleaned_fields": cleaned_fields,
            "stale_days": stale_days,
            "threshold": stale_threshold.isoformat(),
        }
        logger.info("cleanup_stale_reviews 完成: %s", result)
        return result

    def _cleanup_stale_reviewed_sql(self, stale_threshold: datetime) -> tuple:
        """
        通过 SQL 直接批量清理 stale reviewed 记录。

        返回 (cleaned_datasources, cleaned_fields) 元组。
        """
        from app.core.database import SessionLocal
        from services.semantic_maintenance.models import (
            TableauDatasourceSemantics,
            TableauFieldSemantics,
        )

        session = SessionLocal()
        try:
            # 批量重置数据源语义
            ds_result = session.query(TableauDatasourceSemantics).filter(
                TableauDatasourceSemantics.status == SemanticStatus.REVIEWED,
                TableauDatasourceSemantics.updated_at < stale_threshold,
            ).update(
                {"status": SemanticStatus.DRAFT},
                synchronize_session=False,
            )

            # 批量重置字段语义
            field_result = session.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.status == SemanticStatus.REVIEWED,
                TableauFieldSemantics.updated_at < stale_threshold,
            ).update(
                {"status": SemanticStatus.DRAFT},
                synchronize_session=False,
            )

            session.commit()
            logger.info(
                "批量清理 stale reviewed: 数据源 %d 条，字段 %d 条",
                ds_result, field_result,
            )
            return ds_result, field_result
        finally:
            session.close()

    def resolve_field_by_embedding(
        self,
        connection_id: int,
        fuzzy_name: str,
        datasource_luid: str = None,
        top_k: int = 5,
    ) -> tuple:
        """
        向量语义字段解析（Spec 26 §P0 — /fields/resolve）。

        1. 对 fuzzy_name 生成 embedding
        2. 在 kb_embeddings（HNSW） 中搜索 source_type='field'
        3. 对每个候选，通过 field_registry_id join tableau_datasource_fields 补全 role / data_type
        4. 返回带 similarity 置信度的候选列表
        """
        from services.llm.service import llm_service
        from services.knowledge_base.embedding_service import embedding_service
        from services.tableau.models import TableauDatasourceField

        # Step 1: 生成 query embedding（async → sync bridge）
        try:
            import asyncio
            query_embedding = asyncio.run(
                embedding_service.embed_text(fuzzy_name)
            )
        except Exception as e:
            logger.warning("resolve_field_by_embedding: embed_text 失败，fallback 到空列表: %s", e)
            return [], None

        if not query_embedding:
            return [], None

        # Step 2: 向量搜索
        rows = self.db.search_field_embeddings(
            query_embedding=query_embedding,
            connection_id=connection_id,
            top_k=top_k,
            threshold=0.5,
        )

        if not rows:
            logger.info("resolve_field_by_embedding: connection_id=%d 命中 0 条，向量可能尚未生成", connection_id)

        # Step 3: 补全 field_registry_id → role / data_type
        candidates = []
        seen_field_ids = set()
        for row in rows:
            field_semantic_id = row.get("field_semantic_id")
            if field_semantic_id in seen_field_ids:
                continue
            seen_field_ids.add(field_semantic_id)

            # 获取 role / data_type（通过 tableau_datasource_fields）
            role = None
            data_type = None
            if row.get("field_registry_id"):
                db_session = self.db.session
                try:
                    fld = db_session.query(TableauDatasourceField).filter(
                        TableauDatasourceField.id == row["field_registry_id"]
                    ).first()
                    if fld:
                        role = fld.role
                        data_type = fld.data_type
                        # 若指定了 datasource_luid，还需要过滤
                        if datasource_luid and fld.datasource_luid != datasource_luid:
                            continue
                finally:
                    db_session.close()

            confidence = float(row.get("similarity", 0.0))
            candidates.append({
                "field_semantic_id": field_semantic_id,
                "tableau_field_id": row.get("tableau_field_id"),
                "semantic_name": row.get("semantic_name"),
                "semantic_name_zh": row.get("semantic_name_zh"),
                "semantic_definition": row.get("semantic_definition"),
                "role": role,
                "data_type": data_type,
                "connection_id": row.get("connection_id"),
                "confidence": round(confidence, 4),
                "match_source": "vector_hnsw",
            })

        return candidates, None
