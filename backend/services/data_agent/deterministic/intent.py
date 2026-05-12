"""Intent detection for deterministic data-agent routes."""

from __future__ import annotations

import re
import unicodedata

RouteName = str

INVENTORY_KEYWORDS = (
    "有哪些数据源",
    "有什么数据源",
    "有哪些表",
    "有哪些字段",
    "字段有哪些",
    "字段是什么",
    "字段列表",
    "表结构",
    "数据结构",
    "有哪些资产",
    "数据资产",
    "有哪些视图",
    "视图列表",
    "当前连接",
    "可用数据源",
    "数据源列表",
    "表列表",
    "schema",
    "data sources",
    "datasets",
    "tables",
    "fields",
    "columns",
    "views",
    "workbooks",
    "available sources",
)

EXCLUDED_KEYWORDS = (
    "销售额",
    "收入",
    "订单数",
    "趋势",
    "同比",
    "环比",
    "排名",
    "top",
    "增长",
    "下降",
    "分析",
    "对比",
    "汇总",
    "统计",
    "只",
    "仅",
    "过滤",
    "包含",
    "相关",
    "匹配",
    "名字里",
    "字样",
    "项目为",
    "属于",
    "排除",
    "不要",
    "推荐",
    "第二个",
)


def detect_deterministic_route(question: str, connection_type: str | None = None) -> RouteName | None:
    """Return the deterministic route name for connection-level inventory questions."""
    del connection_type
    normalized = _normalize(question)
    if not normalized:
        return None
    if any(keyword in normalized for keyword in EXCLUDED_KEYWORDS):
        return None
    if any(keyword in normalized for keyword in INVENTORY_KEYWORDS):
        return "schema_inventory"
    return None


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()
