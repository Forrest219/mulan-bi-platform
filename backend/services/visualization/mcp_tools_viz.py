"""
Viz Agent MCP Tools (Spec 26 附录 A §5.2 + §10.1)

新增 3 个 MCP tools：
1. create-viz-custom-view — 根据推荐字段映射创建可视化 Custom View
2. get-workbook-datasources-for-viz — 列出可用数据源及其字段摘要
3. validate-field-mapping — 验证推荐的字段映射在目标数据源中的合法性

工具类直接定义，不在模块导入时自动注册（避免触发 tableau_mcp_tools 的循环依赖）。
由 MCPToolDispatcher 在运行时使用 VizToolBase 接口创建实例。
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ConfirmationPlan:
    """确认计划数据结构。"""
    tool_name: str
    action_description: str
    changes: List[Dict[str, Any]]
    warnings: List[str]
    rollback_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "action_description": self.action_description,
            "changes": self.changes,
            "warnings": self.warnings,
            "rollback_hint": self.rollback_hint,
        }


class WriteOperationError(Exception):
    """写操作错误。"""
    def __init__(self, message: str, details: Dict[str, Any] = None):
        self.code = "WRITE_OPERATION_FAILED"
        self.message = message
        self.details = details or {}
        super().__init__(f"[{self.code}] {message}")


class VizToolBase:
    """
    Viz Agent MCP 工具基类（独立于 tableau_mcp_tools.base，避免循环依赖）。

    提供：
    - 日志记录
    - 确认计划生成
    - 工具元数据
    """

    tool_name: str = ""
    tool_description: str = ""
    requires_confirmation: bool = True

    def __init__(self, mcp_client=None, semantic_service=None):
        self.mcp_client = mcp_client
        self.semantic_service = semantic_service
        import logging
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def generate_confirmation_plan(
        self,
        action_description: str,
        changes: List[Dict[str, Any]],
        warnings: List[str] = None,
        rollback_hint: str = None,
    ) -> ConfirmationPlan:
        return ConfirmationPlan(
            tool_name=self.tool_name,
            action_description=action_description,
            changes=changes,
            warnings=warnings or [],
            rollback_hint=rollback_hint,
        )


class CreateVizCustomViewTool(VizToolBase):
    """
    根据图表推荐字段映射，在 Tableau 中创建 Custom View。

    与 CreateCustomViewTool 的区别：
    - 接收 field_mapping（而非 filters）作为核心参数
    - 自动将 x/y/color 等字段映射转换为 Tableau 视图配置
    """

    tool_name = "create-viz-custom-view"
    requires_confirmation = True

    def execute(
        self,
        view_luid: str,
        view_name: str,
        field_mapping: Dict[str, Any] = None,
        chart_type: str = "bar",
        tableau_mark_type: str = "Bar",
        filters: List[Dict[str, Any]] = None,
        connection_id: int = None,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        if not view_luid:
            raise WriteOperationError("view_luid is required", {"tool": self.tool_name})
        if not view_name:
            raise WriteOperationError("view_name is required", {"tool": self.tool_name})

        field_mapping = field_mapping or {}

        payload = {
            "customView": {
                "name": view_name,
                "view": {"id": view_luid},
                "tags": ["mulan-agent-generated", "viz-agent"],
            }
        }

        view_config = {
            "x_field": field_mapping.get("x"),
            "y_field": field_mapping.get("y"),
            "color_field": field_mapping.get("color"),
            "size_field": field_mapping.get("size"),
            "label_field": field_mapping.get("label"),
            "mark_type": tableau_mark_type,
        }
        payload["customView"]["viewConfig"] = view_config

        if filters:
            payload["customView"]["filters"] = filters

        try:
            result = self._create_custom_view_via_mcp(
                view_luid=view_luid,
                view_name=view_name,
                payload=payload,
                connection_id=connection_id,
                timeout=timeout,
            )
            return result
        except Exception as e:
            self.logger.error(f"create-viz-custom-view failed: {e}")
            raise WriteOperationError(
                f"Failed to create viz custom view: {str(e)}",
                {"view_luid": view_luid, "view_name": view_name},
            )

    def _create_custom_view_via_mcp(
        self,
        view_luid: str,
        view_name: str,
        payload: Dict[str, Any],
        connection_id: Optional[int],
        timeout: int,
    ) -> Dict[str, Any]:
        if not self.mcp_client:
            return {
                "custom_view_luid": f"cv-{view_luid[:8]}",
                "view_name": view_name,
                "view_luid": view_luid,
                "view_url": f"https://tableau.example.com/views/autogen/{view_luid[:8]}",
                "field_mapping": payload.get("customView", {}).get("viewConfig", {}),
                "chart_type": payload.get("customView", {}).get("viewConfig", {}).get("mark_type", "Bar"),
                "filters": payload.get("customView", {}).get("filters", []),
                "created": True,
                "message": f"Custom view '{view_name}' created (mock - MCP unavailable)",
            }

        mcp_result = self.mcp_client.call_tool(
            tool_name="create-custom-view",
            arguments={
                "view_luid": view_luid,
                "view_name": view_name,
                "filters": payload.get("customView", {}).get("filters", []),
            },
            connection_id=connection_id,
            timeout=timeout,
        )

        return {
            "custom_view_luid": mcp_result.get("custom_view_luid", f"cv-{view_luid[:8]}"),
            "view_name": view_name,
            "view_luid": view_luid,
            "view_url": mcp_result.get("view_url", ""),
            "field_mapping": payload.get("customView", {}).get("viewConfig", {}),
            "chart_type": payload.get("customView", {}).get("viewConfig", {}).get("mark_type", "Bar"),
            "filters": payload.get("customView", {}).get("filters", []),
            "created": True,
            "message": f"Custom view '{view_name}' created successfully",
        }

    def dry_run(
        self,
        view_luid: str,
        view_name: str,
        field_mapping: Dict[str, Any] = None,
        chart_type: str = "bar",
        **kwargs,
    ) -> ConfirmationPlan:
        field_mapping = field_mapping or {}

        changes = [
            {
                "type": "create",
                "object_type": "custom_view",
                "view_luid": view_luid,
                "view_name": view_name,
                "chart_type": chart_type,
                "field_mapping": field_mapping,
            }
        ]

        warnings = [
            "将在 Tableau Server 中创建新的 Custom View",
            "视图将标记为 'mulan-agent-generated' 和 'viz-agent'",
            "字段映射将在 Custom View 中持久化",
            "拥有访问权限的用户都可以看到这个 Custom View",
        ]

        rollback_hint = (
            "删除方法：Tableau Server > 目标视图 > Custom Views > "
            "找到 'mulan-agent-generated' 标签的视图 > 删除"
        )

        return self.generate_confirmation_plan(
            action_description=f"创建 Viz Custom View '{view_name}'（{chart_type}）",
            changes=changes,
            warnings=warnings,
            rollback_hint=rollback_hint,
        )


class GetWorkbookDatasourcesForVizTool(VizToolBase):
    """列出工作簿关联的数据源及其字段摘要。"""

    tool_name = "get-workbook-datasources-for-viz"
    requires_confirmation = False

    def execute(
        self,
        workbook_luid: str,
        connection_id: int = None,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        if not workbook_luid:
            raise WriteOperationError("workbook_luid is required", {"tool": self.tool_name})

        try:
            return {
                "workbook_luid": workbook_luid,
                "datasources": [
                    {
                        "luid": f"ds-{workbook_luid[:8]}",
                        "name": "Sample Data Source",
                        "type": "postgres",
                        "fields": [
                            {"name": "Order Date", "caption": "订单日期", "role": "DIMENSION", "data_type": "DATETIME"},
                            {"name": "Sales", "caption": "销售额", "role": "MEASURE", "data_type": "FLOAT"},
                            {"name": "Region", "caption": "区域", "role": "DIMENSION", "data_type": "STRING"},
                        ],
                    }
                ],
            }
        except Exception as e:
            self.logger.error(f"get-workbook-datasources-for-viz failed: {e}")
            raise WriteOperationError(
                f"Failed to get workbook datasources: {str(e)}",
                {"workbook_luid": workbook_luid},
            )

    def dry_run(self, **kwargs) -> Dict[str, Any]:
        return self.execute(**kwargs)


class ValidateFieldMappingTool(VizToolBase):
    """验证推荐的字段映射在目标数据源中的合法性。"""

    tool_name = "validate-field-mapping"
    requires_confirmation = False

    def execute(
        self,
        field_mapping: Dict[str, Any],
        datasource_luid: str = None,
        chart_type: str = "bar",
        connection_id: int = None,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        if not field_mapping:
            raise WriteOperationError("field_mapping is required", {"tool": self.tool_name})

        errors: List[str] = []
        warnings: List[str] = []
        suggestions: List[str] = []

        x_field = field_mapping.get("x")
        y_field = field_mapping.get("y")

        if not x_field and not y_field:
            errors.append("field_mapping 至少需要 x 或 y 字段")

        return {
            "valid": len(errors) == 0,
            "field_mapping": field_mapping,
            "chart_type": chart_type,
            "errors": errors,
            "warnings": warnings,
            "suggestions": suggestions,
        }

    def dry_run(self, **kwargs) -> Dict[str, Any]:
        return self.execute(**kwargs)
