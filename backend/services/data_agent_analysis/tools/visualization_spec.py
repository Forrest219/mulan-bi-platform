"""
VisualizationSpecTool — 可视化 spec 生成

Spec 28 §4.1 — visualization_spec

功能：
- 生成图表配置 spec
- 支持 line/bar/scatter/pie/table 等类型
- 输出 ECharts 配置格式
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata

logger = logging.getLogger(__name__)


class VisualizationSpecTool(BaseTool):
    """Visualization Spec Tool — 可视化配置生成"""

    name = "visualization_spec"
    description = "生成图表配置 spec（ECharts 格式）。用于将分析结果可视化展示。"
    metadata = ToolMetadata(
        category="output",
        version="1.0.0",
        dependencies=[],
        tags=["visualization", "chart_spec", "echarts", "chart"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "description": "图表类型",
                "enum": ["line", "bar", "scatter", "pie", "table", "area", "stacked_bar"],
            },
            "title": {
                "type": "string",
                "description": "图表标题",
            },
            "x_field": {
                "type": "string",
                "description": "X 轴字段名",
            },
            "y_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Y 轴字段名列表",
            },
            "series": {
                "type": "array",
                "items": {"type": "string"},
                "description": "系列名（多系列时）",
            },
            "dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "维度字段（分类图表）",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "指标字段",
            },
            "data": {
                "type": "array",
                "description": "图表数据（可选，不提供时生成空壳 spec）",
            },
            "filters": {
                "type": "object",
                "description": "初始过滤条件",
            },
            "options": {
                "type": "object",
                "description": "额外图表配置选项",
            },
        },
        "required": ["chart_type", "title"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        chart_type = params.get("chart_type", "line")
        title = params.get("title", "")
        x_field = params.get("x_field", "")
        y_fields = params.get("y_fields", [])
        series = params.get("series", [])
        dimensions = params.get("dimensions", [])
        metrics = params.get("metrics", [])
        data = params.get("data", [])
        filters = params.get("filters", {})
        options = params.get("options", {})

        try:
            logger.info(
                "VisualizationSpecTool: chart_type=%s, title=%s",
                chart_type,
                title,
            )

            spec = self._generate_chart_spec(
                chart_type=chart_type,
                title=title,
                x_field=x_field,
                y_fields=y_fields,
                series=series,
                dimensions=dimensions,
                metrics=metrics,
                data=data,
                filters=filters,
                options=options,
            )

            return ToolResult(
                success=True,
                data={
                    "chart_spec": spec,
                    "chart_type": chart_type,
                    "title": title,
                    "result_summary": f"已生成 {chart_type} 类型图表配置",
                },
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.exception("VisualizationSpecTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"图表配置生成失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _generate_chart_spec(
        self,
        chart_type: str,
        title: str,
        x_field: str,
        y_fields: List[str],
        series: List[str],
        dimensions: List[str],
        metrics: List[str],
        data: List[Dict],
        filters: Dict,
        options: Dict,
    ) -> Dict[str, Any]:
        """生成图表配置"""
        base_spec = {
            "type": chart_type,
            "title": title,
            "x": x_field,
            "y": y_fields,
            "series": series,
            "dimensions": dimensions,
            "metrics": metrics,
            "filters": filters,
        }

        # 根据图表类型生成 ECharts 配置
        if chart_type == "line":
            echarts_config = {
                "title": {
                    "text": title,
                },
                "tooltip": {
                    "trigger": "axis",
                },
                "legend": {
                    "data": series or y_fields,
                },
                "xAxis": {
                    "type": "category",
                    "data": self._extract_field_values(data, x_field) if data else [],
                    "name": x_field,
                },
                "yAxis": {
                    "type": "value",
                    "name": y_fields[0] if y_fields else "",
                },
                "series": [
                    {
                        "name": s or yf,
                        "type": "line",
                        "data": self._extract_field_values(data, yf) if data else [],
                    }
                    for s, yf in zip(series or [], y_fields or [])
                ],
            }

        elif chart_type == "bar":
            echarts_config = {
                "title": {"text": title},
                "tooltip": {"trigger": "axis"},
                "legend": {"data": series or y_fields},
                "xAxis": {
                    "type": "category",
                    "data": self._extract_field_values(data, x_field) if data else [],
                    "name": x_field,
                },
                "yAxis": {
                    "type": "value",
                    "name": y_fields[0] if y_fields else "",
                },
                "series": [
                    {
                        "name": s or yf,
                        "type": "bar",
                        "data": self._extract_field_values(data, yf) if data else [],
                    }
                    for s, yf in zip(series or [], y_fields or [])
                ],
            }

        elif chart_type == "pie":
            echarts_config = {
                "title": {"text": title},
                "tooltip": {"trigger": "item"},
                "legend": {"bottom": 10},
                "series": [
                    {
                        "name": dimensions[0] if dimensions else "占比",
                        "type": "pie",
                        "radius": "55%",
                        "data": [
                            {"name": d.get(x_field, ""), "value": d.get(y_fields[0], 0)}
                            for d in data
                        ] if data else [],
                    }
                ],
            }

        elif chart_type == "scatter":
            echarts_config = {
                "title": {"text": title},
                "tooltip": {"trigger": "item"},
                "xAxis": {
                    "type": "value",
                    "name": x_field,
                },
                "yAxis": {
                    "type": "value",
                    "name": y_fields[0] if y_fields else "",
                },
                "series": [
                    {
                        "type": "scatter",
                        "symbolSize": 10,
                        "data": [
                            [d.get(x_field, 0), d.get(y_fields[0], 0)]
                            for d in data
                        ] if data else [],
                    }
                ],
            }

        elif chart_type == "table":
            echarts_config = {
                "title": {"text": title},
                "tooltip": {"trigger": "item"},
                "columns": y_fields or dimensions or [],
                "data": data,
            }

        else:
            echarts_config = {"title": {"text": title}}

        # 合并额外选项
        if options:
            echarts_config.update(options)

        base_spec["echarts_config"] = echarts_config

        return base_spec

    def _extract_field_values(
        self,
        data: List[Dict],
        field: str,
    ) -> List[Any]:
        """从数据列表中提取指定字段的值"""
        return [d.get(field) for d in data if field in d]