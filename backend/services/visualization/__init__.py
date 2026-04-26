"""
Viz Agent — 图表推荐与 Tableau 输出引导服务 (Spec 26 附录 A)

模块结构：
- chart_recommender: 图表推荐 LLM 推理链路
- twb_generator: TWB 骨架生成器
- spec_card_builder: 规格卡片数据组装
- prompts: 推荐用 Prompt 模板
- api: FastAPI 路由层

输出三路径：
  路径 1 — MCP Bridge（create-viz-custom-view）
  路径 2 — TWB 骨架生成
  路径 3 — 规格卡片（默认）
"""
from .chart_recommender import ChartRecommender, VIZ_SYSTEM_PROMPT
from .twb_generator import TWBGenerator
from .spec_card_builder import SpecCardBuilder

__all__ = [
    "ChartRecommender",
    "TWBGenerator",
    "SpecCardBuilder",
    "VIZ_SYSTEM_PROMPT",
]
