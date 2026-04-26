"""
Viz Agent 推荐 Prompt 模板 (Spec 26 附录 A §3.3)

System Prompt: 图表推荐专家
User Prompt 模板: VIZ_RECOMMEND_TEMPLATE
"""

# 系统 Prompt
VIZ_SYSTEM_PROMPT = """你是 Mulan BI Platform 的图表推荐专家。
根据数据 schema 和用户意图，推荐最合适的 Tableau 图表类型。

规则：
1. 只分析列的名称、数据类型、语义角色，不需要真实数据值
2. 输出严格遵循 JSON schema，不添加任何额外说明
3. 最多推荐 3 个图表类型，按置信度降序
4. chart_type 必须是: line/bar/scatter/heatmap/area/pie/geo/gantt 之一
5. tableau_mark_type 必须是 Tableau 合法 Mark Type
6. reason 字段用中文，≤50 字
7. 严格返回纯 JSON 对象，不包含 markdown 代码块标记
"""

# User Prompt 模板
VIZ_RECOMMEND_TEMPLATE = """数据 Schema：
{schema_json}

用户意图：{user_intent}

请输出图表推荐（JSON 格式）：
{{
  "recommendations": [
    {{
      "chart_type": "...",
      "confidence": 0.XX,
      "reason": "...",
      "field_mapping": {{"x": "...", "y": "...", "color": null, "size": null, "label": null, "detail": null}},
      "tableau_mark_type": "...",
      "suggested_title": "..."
    }}
  ]
}}"""

# Schema 构建提示（不超过 50 列）
SCHEMA_BUILDING_HINTS = """
数据 Schema 构建规则：
- columns: 最多 50 列，超出截断
- role: dimension | measure
- dtype: STRING | INTEGER | FLOAT | DATE | DATETIME | BOOLEAN | GEO
- row_count_estimate: 量级描述字符串（如 "~10K"），不传原始行数
- sample_values: 可选，每列最多 5 个样本值（仅用于语义推断）

高敏感字段（sensitivity_level = high | confidential）必须从 schema 中移除。
"""

# 图表类型到 Tableau Mark Type 的映射
CHART_TYPE_TO_TABLEAU_MARK = {
    "line": "Line",
    "bar": "Bar",
    "scatter": "Circle",
    "heatmap": "Square",
    "area": "Area",
    "pie": "Pie",
    "geo": "Map",
    "gantt": "Gantt",
    "histogram": "Bar",
    "box": "Bar",
}

# 降级规则：当 LLM 无法确定时，退回 bar 并注明原因
FALLBACK_CHART_TYPE = "bar"
