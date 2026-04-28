"""
META 查询处理器（Spec 14 §14）

3 种 META 意图：
1. meta_datasource_list — 数据源列表
2. meta_asset_count — 看板数量
3. meta_semantic_quality — 语义配置质量

这些查询不进入 VizQL 流水线，直接查本地 DB 毫秒级返回。
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# META 意图关键词（Spec 14 §14.3）
META_INTENT_KEYWORDS = {
    # 数据源列表
    "meta_datasource_list": [
        "你有哪些数据源", "有哪些数据源", "数据源列表", "list datasource",
        "数据源有哪些", "几个数据源", "多少个数据源", "有几个数据源",
        "多少数据源", "接了多少个数据源", "接了几个数据源", "共有几个数据源",
        "一共接了多少", "现在有多少数据源", "数据源一共有多少",
    ],
    # 看板数量
    "meta_asset_count": [
        "你有几个看板", "有几个看板", "看板数量", "有多少看板",
        "多少个看板", "看板总数", "几个dashboard", "几个workbook",
    ],
    # 语义质量
    "meta_semantic_quality": [
        "语义配置有哪些不完善", "语义配置不完善", "语义缺失",
        "哪些语义没配置", "语义配置问题", "语义不完善", "语义配置哪些问题",
    ],
}


def classify_meta_intent(question: str) -> Optional[str]:
    """
    规则检测 META 查询意图。

    Args:
        question: 用户问题

    Returns:
        intent key 或 None
    """
    q = question.lower()
    for intent, keywords in META_INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in q:
                return intent
    return None


def handle_meta_datasource_list(
    db: Session,
    connection_id: int,
) -> Dict[str, Any]:
    """
    META handler 1：列出当前连接下的数据源（Spec 14 §14.3.1）。

    查询范围 = connection_id 指定的连接，不 fallback。
    按 Site（connection name）分组展示。
    """
    from services.tableau.models import TableauAsset, TableauConnection

    assets = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "datasource",
        TableauAsset.is_deleted == False,
    ).all()

    connection = db.query(TableauConnection).filter(
        TableauConnection.id == connection_id
    ).first()

    site_label = (
        f"{connection.name}（{connection.site}）"
        if connection
        else f"连接 {connection_id}"
    )

    if not assets:
        content = f"**{site_label}** 下暂无数据源，请先完成资产同步。"
    else:
        lines = [f"我在 **{site_label}** 中找到 **{len(assets)}** 个数据源："]
        for a in sorted(assets, key=lambda x: x.name):
            lines.append(f"- {a.name}")
        lines.append("\n> 如需了解某个数据源的字段信息，可以直接提问，例如：「管理费用数据源 有什么字段」")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_datasource_list",
        "meta": True,
    }


def handle_meta_asset_count(
    db: Session,
    connection_id: int,
) -> Dict[str, Any]:
    """
    META handler 2：统计当前连接下的看板数量（Spec 14 §14.3.2）。

    dashboard + workbook 都计入。
    """
    from services.tableau.models import TableauAsset

    dashboard_count = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "dashboard",
        TableauAsset.is_deleted == False,
    ).count()

    workbook_count = db.query(TableauAsset).filter(
        TableauAsset.connection_id == connection_id,
        TableauAsset.asset_type == "workbook",
        TableauAsset.is_deleted == False,
    ).count()

    total = dashboard_count + workbook_count

    content = (
        f"当前连接共有 **{total}** 个看板"
        f"（其中 Dashboard {dashboard_count} 个，Workbook {workbook_count} 个）。"
    )

    return {
        "response_type": "number",
        "value": total,
        "label": "看板总数",
        "unit": "个",
        "formatted": str(total),
        "content": content,
        "intent": "meta_asset_count",
        "meta": True,
    }


def handle_meta_semantic_quality(
    db: Session,
    connection_id: int,
) -> Dict[str, Any]:
    """
    META handler 3：分析当前连接的语义配置完整性（Spec 14 §14.3.3）。

    检查 tableau_field_semantics 表中该 connection 下的不完善项：
    - semantic_definition 为空
    - status 为 draft 或 ai_generated（未经人工审核）
    """
    from services.semantic_maintenance.models import TableauFieldSemantics
    from sqlalchemy import or_

    incomplete = db.query(TableauFieldSemantics).filter(
        TableauFieldSemantics.connection_id == connection_id,
        or_(
            TableauFieldSemantics.semantic_definition.is_(None),
            TableauFieldSemantics.semantic_definition == "",
            TableauFieldSemantics.status.in_(["draft", "ai_generated"]),
        ),
    ).all()

    if not incomplete:
        content = "当前数据源的语义配置较为完善，未发现明显缺失项。"
    else:
        lines = [f"发现 **{len(incomplete)}** 处语义配置不完善："]
        for f in incomplete[:10]:
            reason = []
            if not f.semantic_definition:
                reason.append("缺少语义定义")
            if f.status in ("draft", "ai_generated"):
                reason.append(f"状态为 {f.status}（未审核）")
            display_name = f.semantic_name_zh or f.semantic_name or f.tableau_field_id
            lines.append(f"- `{display_name}`：{', '.join(reason)}")
        if len(incomplete) > 10:
            lines.append(f"... 等共 {len(incomplete)} 处")
        content = "\n".join(lines)

    return {
        "response_type": "text",
        "content": content,
        "intent": "meta_semantic_quality",
        "meta": True,
    }


def handle_meta_query(
    meta_intent: str,
    db: Session,
    connection_id: int,
) -> Dict[str, Any]:
    """
    META 查询分发入口。

    Args:
        meta_intent: classify_meta_intent() 返回的意图 key
        db: SQLAlchemy session
        connection_id: 连接 ID

    Returns:
        META 查询响应字典
    """
    handlers = {
        "meta_datasource_list": handle_meta_datasource_list,
        "meta_asset_count": handle_meta_asset_count,
        "meta_semantic_quality": handle_meta_semantic_quality,
    }

    handler = handlers.get(meta_intent)
    if handler:
        return handler(db, connection_id)

    return {
        "response_type": "text",
        "content": f"未知的 META 查询类型：{meta_intent}",
        "intent": meta_intent,
        "meta": True,
    }
