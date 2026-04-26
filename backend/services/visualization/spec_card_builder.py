"""
规格卡片构建器 — Spec Card Builder (Spec 26 附录 A §2.3 路径 3)

在平台内展示可视化规格卡片：
- chart_type + field_roles（Tableau 操作步骤）
- ECharts 预览缩略图配置（低精度示意，非精确预览）

ECharts 预览限制：
- 尺寸：最大 320×200px
- 数据：使用推断的 schema 生成模拟数据（非真实查询数据）
- 交互：只读，无 tooltip/zoom/legend 等交互
"""

import logging
from typing import Any, Dict, List, Optional

from .prompts import CHART_TYPE_TO_TABLEAU_MARK

logger = logging.getLogger(__name__)


class SpecCardBuilder:
    """
    规格卡片数据组装器。

    根据推荐结果组装规格卡片数据，含：
    - field_roles: 各字段的 Tableau 角色（Columns/Rows/Marks）
    - tableau_steps: Tableau 操作步骤（人工操作指南）
    - echarts_preview_config: ECharts 缩略图配置（mock data）
    """

    # Tableau 操作步骤模板
    TABLEAU_STEPS_TEMPLATES = {
        "line": [
            "1. 打开 Tableau，连接到目标数据源",
            "2. 将 [{x_field}] 拖拽到 Columns（X 轴）",
            "3. 如需时间聚合，右键点击字段 → 转换为 MONTH/QUARTER/YEAR",
            "4. 将 [{y_field}] 拖拽到 Rows（Y 轴）",
            "5. 如有分类字段 [{color_field}]，拖拽到 Marks → Color",
            "6. 在 Marks 卡中选择 Line 类型",
            "7. 可选：拖拽更多字段到 Detail/Size 增加细节",
        ],
        "bar": [
            "1. 打开 Tableau，连接到目标数据源",
            "2. 将 [{x_field}] 拖拽到 Columns 或 Rows（决定横向/纵向）",
            "3. 将 [{y_field}] 拖拽到对应的另一轴",
            "4. 如有分类字段 [{color_field}]，拖拽到 Marks → Color",
            "5. 在 Marks 卡中选择 Bar 类型",
            "6. 可选：右键度量字段 → 改为 SUM/AVG/MIN/MAX 聚合",
        ],
        "pie": [
            "1. 打开 Tableau，连接到目标数据源",
            "2. 将 [{x_field}]（分类字段）拖拽到 Columns",
            "3. 将 [{y_field}]（度量字段）拖拽到 Rows",
            "4. 在 Marks 卡中选择 Pie 类型",
            "5. 将 [{x_field}] 拖拽到 Marks → Label 显示标签",
            "6. 可选：拖拽 [{color_field}] 到 Marks → Color",
        ],
        "scatter": [
            "1. 打开 Tableau，连接到目标数据源",
            "2. 将 [{x_field}]（数值字段）拖拽到 Columns",
            "3. 将 [{y_field}]（数值字段）拖拽到 Rows",
            "4. 在 Marks 卡中选择 Circle 类型",
            "5. 如有分类 [{color_field}]，拖拽到 Marks → Color",
            "6. 可选：拖拽 [{size_field}] 到 Marks → Size 增加维度",
        ],
        "area": [
            "1. 打开 Tableau，连接到目标数据源",
            "2. 将 [{x_field}] 拖拽到 Columns",
            "3. 将 [{y_field}] 拖拽到 Rows",
            "4. 在 Marks 卡中选择 Area 类型",
            "5. 如有分类 [{color_field}]，拖拽到 Marks → Color（堆叠面积）",
        ],
        "heatmap": [
            "1. 打开 Tableau，连接到目标数据源",
            "2. 将 [{x_field}]（维度 A）拖拽到 Columns",
            "3. 将 [{y_field}]（维度 B）拖拽到 Rows",
            "4. 在 Marks 卡中选择 Square 类型",
            "5. 将度量字段拖拽到 Marks → Color（颜色编码数值）",
        ],
        "geo": [
            "1. 打开 Tableau，连接到目标数据源",
            "2. 将地理字段（如 [{x_field}] Country/State/City）双击或拖拽到画布",
            "3. Tableau 自动识别地理角色，创建地图视图",
            "4. 将 [{y_field}] 拖拽到 Marks → Color（颜色编码度量）",
            "5. 可选：拖拽 [{color_field}] 到 Marks → Detail 增加分类层",
        ],
        "gantt": [
            "1. 打开 Tableau，连接到目标数据源",
            "2. 将 [{x_field}]（开始时间）拖拽到 Columns",
            "3. 将任务/分类 [{y_field}] 拖拽到 Rows",
            "4. 在 Marks 卡中选择 Gantt 类型",
            "5. 将时长字段拖拽到 Marks → Size",
        ],
    }

    # 降级模板（通用柱状图步骤）
    DEFAULT_STEPS = [
        "1. 打开 Tableau，连接到目标数据源",
        "2. 将分类字段拖拽到 Columns",
        "3. 将度量字段拖拽到 Rows",
        "4. 在 Marks 卡中选择 Bar 类型",
        "5. 根据需要调整聚合方式（SUM/AVG/MIN/MAX）",
    ]

    def __init__(self):
        pass

    # ── Public API ──────────────────────────────────────────────────────────────

    def build_spec_card(
        self,
        recommendation: Dict[str, Any],
        query_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        构建规格卡片数据。

        Args:
            recommendation: 推荐结果
            query_schema: 原始查询 schema（用于生成 mock data）

        Returns:
            {
                "chart_type": str,
                "title": str,
                "field_roles": [...],
                "tableau_steps": [...],
                "echarts_preview_config": {...}
            }
        """
        chart_type = recommendation.get("chart_type", "bar")
        field_mapping = recommendation.get("field_mapping", {})
        suggested_title = recommendation.get("suggested_title", "推荐图表")

        # 构建 field_roles
        field_roles = self._build_field_roles(chart_type, field_mapping, query_schema)

        # 构建 Tableau 操作步骤
        tableau_steps = self._build_tableau_steps(chart_type, field_mapping)

        # 构建 ECharts 预览配置（mock data）
        echarts_preview_config = self._build_echarts_preview(
            chart_type=chart_type,
            field_mapping=field_mapping,
            query_schema=query_schema,
        )

        return {
            "chart_type": chart_type,
            "title": suggested_title,
            "field_roles": field_roles,
            "tableau_steps": tableau_steps,
            "echarts_preview_config": echarts_preview_config,
        }

    # ── Field Roles ─────────────────────────────────────────────────────────────

    def _build_field_roles(
        self,
        chart_type: str,
        field_mapping: Dict[str, Any],
        query_schema: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        根据 chart_type 确定各字段的 Tableau 角色。
        """
        x_field = field_mapping.get("x", "")
        y_field = field_mapping.get("y", "")
        color_field = field_mapping.get("color")
        size_field = field_mapping.get("size")
        label_field = field_mapping.get("label")

        roles = []

        # 从 schema 中获取 dtype 用于 aggregation 推断
        schema_columns = {c["name"]: c for c in (query_schema or {}).get("columns", [])}

        if x_field:
            col_info = schema_columns.get(x_field, {})
            dtype = col_info.get("dtype", "")
            aggregation = self._infer_aggregation(dtype, role="dimension")
            roles.append({
                "field": x_field,
                "role": self._x_axis_role(chart_type),
                "aggregation": aggregation,
            })

        if y_field:
            col_info = schema_columns.get(y_field, {})
            dtype = col_info.get("dtype", "")
            aggregation = self._infer_aggregation(dtype, role="measure")
            roles.append({
                "field": y_field,
                "role": self._y_axis_role(chart_type),
                "aggregation": aggregation,
            })

        if color_field:
            roles.append({
                "field": color_field,
                "role": "Marks → Color（颜色）",
                "aggregation": None,
            })

        if size_field:
            roles.append({
                "field": size_field,
                "role": "Marks → Size（大小）",
                "aggregation": None,
            })

        if label_field:
            roles.append({
                "field": label_field,
                "role": "Marks → Label（标签）",
                "aggregation": None,
            })

        return roles

    @staticmethod
    def _x_axis_role(chart_type: str) -> str:
        if chart_type in ("line", "area", "scatter", "histogram"):
            return "Columns（X 轴）"
        elif chart_type in ("bar", "pie"):
            return "Columns 或 Rows（取决于方向）"
        return "Columns（X 轴）"

    @staticmethod
    def _y_axis_role(chart_type: str) -> str:
        if chart_type in ("line", "area", "scatter", "histogram"):
            return "Rows（Y 轴）"
        elif chart_type in ("bar", "pie"):
            return "对应的另一轴"
        return "Rows（Y 轴）"

    @staticmethod
    def _infer_aggregation(dtype: str, role: str) -> Optional[str]:
        """根据 dtype 推断 Tableau 聚合方式。"""
        if role == "dimension":
            if dtype in ("DATE", "DATETIME"):
                return "YEAR/MONTH/QUARTER/DAY"
            return None
        if role == "measure":
            if dtype in ("INTEGER", "FLOAT"):
                return "SUM"
            return "COUNT"
        return None

    # ── Tableau 操作步骤 ────────────────────────────────────────────────────────

    def _build_tableau_steps(
        self,
        chart_type: str,
        field_mapping: Dict[str, Any],
    ) -> List[str]:
        """
        根据 chart_type 和 field_mapping 渲染步骤模板。
        """
        x_field = field_mapping.get("x", "")
        y_field = field_mapping.get("y", "")
        color_field = field_mapping.get("color", "")
        size_field = field_mapping.get("size", "")

        template = self.TABLEAU_STEPS_TEMPLATES.get(chart_type, self.DEFAULT_STEPS)

        steps = []
        for step in template:
            filled = step.replace("{x_field}", x_field or "字段 X")
            filled = filled.replace("{y_field}", y_field or "字段 Y")
            filled = filled.replace("{color_field}", color_field or "")
            filled = filled.replace("{size_field}", size_field or "")
            steps.append(filled)

        return steps

    # ── ECharts 预览配置 ────────────────────────────────────────────────────────

    def _build_echarts_preview(
        self,
        chart_type: str,
        field_mapping: Dict[str, Any],
        query_schema: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        构建 ECharts 缩略图配置。

        限制：
        - 尺寸：最大 320×200px（由前端控制）
        - 数据：使用 mock data（非真实数据）
        - 交互：只读
        """
        x_field = field_mapping.get("x", "X")
        y_field = field_mapping.get("y", "Y")
        color_field = field_mapping.get("color")

        # 生成 mock data（基于 schema 中的 sample_values 或自动生成）
        mock_data = self._generate_mock_data(chart_type, x_field, y_field, color_field, query_schema)

        # ECharts option 构建
        echarts_config: Dict[str, Any] = {
            "type": chart_type,
            "mock_data": mock_data,
            "x_field": x_field,
            "y_field": y_field,
            "color_field": color_field,
        }

        # 根据 chart_type 补充 ECharts 配置
        if chart_type == "line":
            echarts_config["echarts_option"] = {
                "xAxis": {"type": "category", "data": mock_data.get("x_data", [])},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "name": y_field,
                        "type": "line",
                        "data": mock_data.get("y_data", []),
                        "smooth": True,
                    }
                ],
            }
        elif chart_type == "bar":
            echarts_config["echarts_option"] = {
                "xAxis": {"type": "category", "data": mock_data.get("x_data", [])},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "name": y_field,
                        "type": "bar",
                        "data": mock_data.get("y_data", []),
                    }
                ],
            }
        elif chart_type == "pie":
            echarts_config["echarts_option"] = {
                "series": [
                    {
                        "name": y_field,
                        "type": "pie",
                        "radius": ["35%", "60%"],
                        "data": mock_data.get("pie_data", []),
                    }
                ],
            }
        elif chart_type == "scatter":
            echarts_config["echarts_option"] = {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "name": "scatter",
                        "type": "scatter",
                        "symbolSize": 12,
                        "data": mock_data.get("scatter_data", []),
                    }
                ],
            }
        elif chart_type == "area":
            echarts_config["echarts_option"] = {
                "xAxis": {"type": "category", "data": mock_data.get("x_data", [])},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "name": y_field,
                        "type": "line",
                        "areaStyle": {},
                        "data": mock_data.get("y_data", []),
                    }
                ],
            }
        else:
            # 默认折线图配置
            echarts_config["echarts_option"] = {
                "xAxis": {"type": "category", "data": mock_data.get("x_data", [])},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "data": mock_data.get("y_data", [])}],
            }

        return echarts_config

    def _generate_mock_data(
        self,
        chart_type: str,
        x_field: str,
        y_field: str,
        color_field: Optional[str],
        query_schema: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        生成 mock data（基于 schema 中的 sample_values 或自动生成合理模拟数据）。
        """
        # 尝试使用 schema 中的 sample_values
        sample_values = (query_schema or {}).get("sample_values", {})
        x_samples = sample_values.get(x_field, [])
        y_samples = sample_values.get(y_field, [])

        if chart_type == "pie":
            # 饼图：category + value
            pie_data = []
            x_values = x_samples if x_samples else [f"类别{i}" for i in range(1, 6)]
            y_values = y_samples if y_samples else [100, 80, 60, 40, 20]
            for i, xv in enumerate(x_values[:7]):  # 饼图最多 7 个扇区
                pie_data.append({"name": str(xv), "value": y_values[i] if i < len(y_values) else 50})
            return {"pie_data": pie_data}

        if chart_type == "scatter":
            # 散点图：[[x, y], ...]
            scatter_data = []
            n = min(len(x_samples), len(y_samples), 20) if (x_samples and y_samples) else 10
            import random

            random.seed(42)
            for i in range(n):
                x_val = float(x_samples[i]) if i < len(x_samples) and x_samples[i] else random.uniform(10, 100)
                y_val = float(y_samples[i]) if i < len(y_samples) and y_samples[i] else random.uniform(10, 100)
                scatter_data.append([x_val, y_val])
            return {"scatter_data": scatter_data}

        # 默认：x_data + y_data（时序/分类）
        x_data = x_samples if x_samples else [f"2024-0{i}" for i in range(1, 8)]
        y_data = y_samples if y_samples else [120, 90, 75, 130, 110, 95, 140]

        return {
            "x_data": x_data,
            "y_data": y_data,
        }
