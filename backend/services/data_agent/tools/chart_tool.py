"""
ChartTool — 图表 spec 生成工具（Spec 26 附录 A 集成）

Spec: docs/specs/26-viz-agent-addendum.md §3.1 ToolRegistry

当用户要求「可视化这个结果」「做个图」时使用：
1. 接收查询结果 schema + 用户意图
2. 通过 Viz Agent ChartRecommender 生成图表推荐
3. 支持三路径输出：card（规格卡片）/ twb（TWB 骨架）/ mcp（Tableau Custom View）

Tool name: "chart"
"""

import logging
import time
from typing import Any, Dict, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)

VALID_CHART_TYPES = ("bar", "line", "pie", "scatter", "area", "heatmap", "geo", "gantt", "histogram", "box")


class ChartTool(BaseTool):
    """
    Data Agent Tool: 图表 spec 生成（Viz Agent 集成版）。

    当用户要求「可视化数据」「画一个柱状图」「用折线图展示趋势」时使用。

    与旧 stub 版的区别：
    - 接入 Viz Agent ChartRecommender 进行智能图表推荐
    - 支持三路径输出：card（规格卡片）/ twb（TWB 骨架）/ mcp（MCP Bridge）
    - 不再返回 "not_implemented" stub

    Tool name: "chart"
    """

    name = "chart"
    description = (
        "图表 spec 生成 + 发布。当用户要求可视化数据（如「做个图展示销售趋势」）时使用，"
        "生成 Tableau 可发布的图表规格（支持 bar/line/pie/scatter/area/heatmap/geo/gantt 等类型）。"
        "输入查询结果 schema + 意图，返回推荐图表类型、字段映射及发布路径（card/twb/mcp）。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": list(VALID_CHART_TYPES),
                "description": "指定图表类型（可选，不指定则由 Viz Agent 自动推荐）",
            },
            "title": {
                "type": "string",
                "description": "图表标题（可选）",
            },
            "data": {
                "type": "object",
                "description": "数据（含 fields + rows，用于生成 schema）",
            },
            "schema": {
                "type": "object",
                "description": "查询结果 schema（columns/row_count_estimate/sample_values），优先级高于 data",
            },
            "user_intent": {
                "type": "string",
                "description": "用户自然语言意图，如「分析月度销售趋势」（可选）",
            },
            "x_field": {
                "type": "string",
                "description": "X 轴字段（可选）",
            },
            "y_field": {
                "type": "string",
                "description": "Y 轴字段（可选）",
            },
            "output_mode": {
                "type": "string",
                "enum": ["card", "twb", "mcp"],
                "description": "输出路径：card=规格卡片（默认）, twb=TWB骨架, mcp=Tableau Custom View",
            },
            "connection_id": {
                "type": "integer",
                "description": "Tableau 连接 ID（mode=mcp 时需要）",
            },
            "workbook_luid": {
                "type": "string",
                "description": "Tableau 工作簿 LUID（mode=mcp 时需要）",
            },
        },
        "required": [],  # schema 或 data 至少提供一个
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        生成图表规格并返回发布数据。

        Args:
            params: {
                chart_type?: str,        # 可选，指定类型或让 Viz Agent 推荐
                title?: str,              # 图表标题
                data?: dict,             # {fields: [...], rows: [...]} 或 {columns: [...], rows: [...]}
                schema?: dict,            # Viz Agent 推荐用的 schema（优先使用）
                user_intent?: str,        # 自然语言意图
                x_field?: str, y_field?: str,
                output_mode?: str,        # card/twb/mcp
                connection_id?: int,
                workbook_luid?: str,
            }
            context: ToolContext with session_id, user_id, connection_id

        Returns:
            ToolResult with chart spec data
        """
        start_time = time.time()

        # 优先使用显式提供的 schema，其次从 data 构造
        schema = params.get("schema")
        data = params.get("data")
        chart_type = params.get("chart_type", "")
        title = params.get("title", "")
        user_intent = params.get("user_intent", "")
        x_field = params.get("x_field", "")
        y_field = params.get("y_field", "")
        output_mode = params.get("output_mode", "card")

        # 从 data 构造 schema（兼容旧接口）
        if schema is None and data is not None:
            schema = self._build_schema_from_data(data)

        # 验证：schema 或 data 至少有一个
        if schema is None and data is None:
            return ToolResult(
                success=False,
                data=None,
                error="schema 或 data 不能同时为空",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        # 验证 chart_type 合法性
        if chart_type and chart_type not in VALID_CHART_TYPES:
            return ToolResult(
                success=False,
                data=None,
                error=f"chart_type 必须为 {', '.join(VALID_CHART_TYPES)} 之一",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        # 如果显式指定了 chart_type + 字段，跳过 LLM 推荐，直接构造 recommendation
        if chart_type and x_field and y_field:
            recommendation = {
                "rank": 1,
                "chart_type": chart_type,
                "confidence": 1.0,
                "reason": f"用户指定图表类型：{chart_type}",
                "field_mapping": {
                    "x": x_field,
                    "y": y_field,
                    "color": params.get("color_field"),
                    "size": params.get("size_field"),
                    "label": params.get("label_field"),
                    "detail": None,
                },
                "tableau_mark_type": self._chart_type_to_mark_type(chart_type),
                "suggested_title": title or "推荐图表",
            }
        else:
            # 调用 Viz Agent ChartRecommender
            recommendation = await self._call_viz_agent_recommend(
                schema=schema,
                user_intent=user_intent,
                connection_id=context.connection_id,
            )
            if "error" in recommendation:
                return ToolResult(
                    success=False,
                    data=None,
                    error=recommendation["error"],
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

        # 根据 output_mode 执行输出
        result_data = await self._generate_output(
            recommendation=recommendation,
            output_mode=output_mode,
            params=params,
            context=context,
        )

        execution_time_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "ChartTool.execute: chart_type=%s, mode=%s, x_field=%s, y_field=%s, trace=%s, time=%dms",
            recommendation.get("chart_type"),
            output_mode,
            recommendation.get("field_mapping", {}).get("x"),
            recommendation.get("field_mapping", {}).get("y"),
            context.trace_id,
            execution_time_ms,
        )

        return ToolResult(
            success=True,
            data=result_data,
            execution_time_ms=execution_time_ms,
        )

    # ── Viz Agent 集成 ─────────────────────────────────────────────────────────

    async def _call_viz_agent_recommend(
        self,
        schema: Dict[str, Any],
        user_intent: str,
        connection_id: Optional[int],
    ) -> Dict[str, Any]:
        """
        调用 Viz Agent ChartRecommender 获取推荐。
        """
        try:
            from services.visualization import ChartRecommender

            recommender = ChartRecommender()
            result = await recommender.recommend(
                schema=schema,
                user_intent=user_intent,
                connection_id=connection_id,
            )

            if "error_code" in result:
                return {"error": f"[{result['error_code']}] {result.get('message', '推荐失败')}"}

            recommendations = result.get("recommendations", [])
            if not recommendations:
                return {"error": "Viz Agent 未返回任何推荐"}

            # 返回 rank=1 的推荐
            return recommendations[0]

        except Exception as e:
            logger.error("ChartTool Viz Agent 调用失败: %s", e)
            return {"error": f"Viz Agent 调用异常: {str(e)}"}

    # ── 输出生成 ───────────────────────────────────────────────────────────────

    async def _generate_output(
        self,
        recommendation: Dict[str, Any],
        output_mode: str,
        params: dict,
        context: ToolContext,
    ) -> Dict[str, Any]:
        """
        根据 output_mode 生成对应输出。
        """
        if output_mode == "twb":
            from services.visualization import TWBGenerator

            generator = TWBGenerator()
            twb_result = generator.generate_twb(recommendation)
            return {
                "output_mode": "twb",
                "chart_type": recommendation.get("chart_type"),
                "filename": twb_result["filename"],
                "download_url": twb_result["download_url"],
                "expires_at": twb_result["expires_at"],
                "twb_content": twb_result["twb_content"],
                "field_mapping": recommendation.get("field_mapping", {}),
                "tableau_mark_type": recommendation.get("tableau_mark_type"),
            }

        elif output_mode == "mcp":
            connection_id = params.get("connection_id") or context.connection_id
            workbook_luid = params.get("workbook_luid", "")

            try:
                from services.tableau.mcp_client import set_mcp_connection_id
                from services.tableau.mcp_tools.dispatcher import get_dispatcher

                set_mcp_connection_id(connection_id)

                dispatcher = get_dispatcher()
                mcp_result = dispatcher.execute_tool(
                    tool_name="create-viz-custom-view",
                    confirmation_received=True,
                    view_luid=workbook_luid,
                    view_name=recommendation.get("suggested_title", "推荐图表"),
                    field_mapping=recommendation.get("field_mapping", {}),
                    chart_type=recommendation.get("chart_type", "bar"),
                    tableau_mark_type=recommendation.get("tableau_mark_type", "Bar"),
                    filters=[],
                    connection_id=connection_id,
                )

                return {
                    "output_mode": "mcp",
                    "chart_type": recommendation.get("chart_type"),
                    "custom_view_id": mcp_result.get("custom_view_luid"),
                    "view_url": mcp_result.get("view_url"),
                    "field_mapping": recommendation.get("field_mapping", {}),
                    "message": mcp_result.get("message", "已在 Tableau 中创建 Custom View"),
                }
            except Exception as e:
                logger.error("ChartTool MCP 发布失败: %s", e)
                return {
                    "output_mode": "mcp",
                    "chart_type": recommendation.get("chart_type"),
                    "error": f"MCP 发布失败: {str(e)}",
                    "field_mapping": recommendation.get("field_mapping", {}),
                }

        else:
            # 默认 card 模式：返回规格卡片
            from services.visualization import SpecCardBuilder

            builder = SpecCardBuilder()
            schema_from_params = params.get("schema") or params.get("data")
            spec_card = builder.build_spec_card(
                recommendation=recommendation,
                query_schema=schema_from_params,
            )
            return {
                "output_mode": "card",
                "chart_type": recommendation.get("chart_type"),
                "spec_card": spec_card,
                "field_mapping": recommendation.get("field_mapping", {}),
                "tableau_mark_type": recommendation.get("tableau_mark_type"),
            }

    # ── 工具方法 ───────────────────────────────────────────────────────────────

    def _build_schema_from_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 data 构造 Viz Agent 可用的 schema。
        支持两种格式：
        - {fields: [...], rows: [...]} — 旧格式
        - {columns: [{name, dtype, role}], rows: [...]} — 新格式
        """
        fields = data.get("fields", [])
        rows = data.get("rows", [])

        if isinstance(fields, list) and fields and isinstance(fields[0], str):
            # 旧格式：fields = ["col1", "col2"], rows = [[val1, val2], ...]
            # 推断 dtype 和 role
            columns = []
            for i, fname in enumerate(fields):
                # 简单推断：数值型列为 measure
                sample_vals = [row[i] for row in rows[:10] if i < len(row)]
                dtype = self._infer_dtype(sample_vals)
                role = "measure" if dtype in ("INTEGER", "FLOAT") else "dimension"
                columns.append({"name": fname, "dtype": dtype, "role": role})
            return {
                "columns": columns,
                "row_count_estimate": f"~{len(rows)}",
                "sample_values": {fname: [str(rows[i][j]) for i in range(min(3, len(rows)))] for j, fname in enumerate(fields)},
            }

        # 新格式
        return {
            "columns": data.get("columns", []),
            "row_count_estimate": f"~{len(rows)}",
        }

    @staticmethod
    def _infer_dtype(sample_values: list) -> str:
        """简单 dtype 推断。"""
        if not sample_values:
            return "STRING"
        first = sample_values[0]
        if isinstance(first, int):
            return "INTEGER"
        if isinstance(first, float):
            return "FLOAT"
        if isinstance(first, str):
            if len(first) == 10 and first[4] == "-" and first[7] == "-":
                return "DATE"
            return "STRING"
        return "STRING"

    @staticmethod
    def _chart_type_to_mark_type(chart_type: str) -> str:
        """图表类型 → Tableau Mark Type。"""
        mapping = {
            "line": "Line",
            "bar": "Bar",
            "pie": "Pie",
            "scatter": "Circle",
            "area": "Area",
            "heatmap": "Square",
            "geo": "Map",
            "gantt": "Gantt",
            "histogram": "Bar",
            "box": "Bar",
        }
        return mapping.get(chart_type, "Bar")
