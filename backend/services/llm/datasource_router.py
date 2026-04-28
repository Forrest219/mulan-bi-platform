"""
数据源路由器（Spec 14 §7）

多数据源路由算法：根据用户问题和字段覆盖率选择最优数据源。

评分公式：
routing_score = 0.50 * field_coverage_ratio
             + 0.25 * freshness_score(last_sync_at)
             + 0.10 * field_count_score(field_count)
             + 0.15 * usage_frequency_score(query_count)

C4：当 connection_id=None 时，自动选第一个 is_active=True 的 TableauConnection。
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from services.common.redis_cache import get_cached_datasource_fields, cache_datasource_fields

logger = logging.getLogger(__name__)

# 评分权重（Spec 14 §7.3）
WEIGHT_FIELD_COVERAGE = 0.50
WEIGHT_FRESHNESS = 0.25
WEIGHT_FIELD_COUNT = 0.10
WEIGHT_USAGE_FREQUENCY = 0.15

# 评分阈值（Spec 14 §7.4）
MIN_ROUTING_SCORE = 0.3

# 字段数量合理范围
OPTIMAL_FIELD_COUNT_MIN = 10
OPTIMAL_FIELD_COUNT_MAX = 100

# Redis 缓存 TTL（秒）
CACHE_TTL_SECONDS = 3600  # 1小时


@dataclass
class DatasourceCandidate:
    """数据源候选"""
    datasource_luid: str
    datasource_name: str
    connection_id: int
    score: float
    field_coverage: float = 0.0
    freshness: float = 0.0
    field_count_score: float = 0.0
    usage_frequency: float = 0.0


def calculate_routing_score(
    user_terms: List[str],
    field_captions: List[str],
    last_sync_at: Optional[Any] = None,
    field_count: int = 0,
    query_count: int = 0,
) -> float:
    """
    计算数据源路由评分（Spec 14 §7.3）。

    Args:
        user_terms: 用户问题中提取的候选词
        field_captions: 数据源字段 caption 列表
        last_sync_at: 数据源最后同步时间
        field_count: 字段总数
        query_count: 历史查询次数

    Returns:
        评分（0.0 ~ 1.0）
    """
    # 字段完备度
    if user_terms and field_captions:
        matched = sum(
            1 for term in user_terms
            if any(term.lower() in fc.lower() for fc in field_captions)
        )
        field_coverage = matched / len(user_terms)
    else:
        field_coverage = 0.0

    # 新鲜度
    freshness = calculate_freshness(last_sync_at)

    # 字段数量得分
    field_count_score_val = calculate_field_count_score(field_count)

    # 使用频次
    usage_frequency = calculate_usage_frequency(query_count)

    score = (
        WEIGHT_FIELD_COVERAGE * field_coverage
        + WEIGHT_FRESHNESS * freshness
        + WEIGHT_FIELD_COUNT * field_count_score_val
        + WEIGHT_USAGE_FREQUENCY * usage_frequency
    )

    return round(score, 4)


def calculate_freshness(last_sync_at: Optional[Any]) -> float:
    """
    计算新鲜度得分。

    公式：freshness_score = max(0, 1 - hours_since_sync / 24)
    24 小时内线性衰减，24 小时后为 0。
    """
    if last_sync_at is None:
        return 0.5  # 默认值

    from datetime import datetime, timezone

    # 统一转为 UTC naive datetime 比较
    sync_time = last_sync_at
    if hasattr(sync_time, 'tzinfo') and sync_time.tzinfo is not None:
        sync_time = sync_time.replace(tzinfo=None)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    hours_since = (now - sync_time).total_seconds() / 3600

    return max(0.0, 1.0 - hours_since / 24)


def calculate_field_count_score(field_count: int) -> float:
    """
    计算字段数量得分。

    公式：1.0 if 10 <= count <= 100 else 0.8
    惩罚过大/过小数据源。
    """
    if OPTIMAL_FIELD_COUNT_MIN <= field_count <= OPTIMAL_FIELD_COUNT_MAX:
        return 1.0
    return 0.8


def calculate_usage_frequency(query_count: int) -> float:
    """
    计算使用频次得分。

    公式：min(1.0, query_count / 100)
    按百次查询归一化。
    """
    return min(1.0, query_count / 100)


def extract_terms(question: str) -> List[str]:
    """
    从用户问题中提取候选词。

    Args:
        question: 用户问题

    Returns:
        候选词列表
    """
    import re

    # 移除标点符号
    cleaned = re.sub(
        r"[，。！？、；：""''（）《》【】\.,!?;:\"\'\(\)\[\]]",
        " ",
        question,
    )
    # 按空格分割
    tokens = cleaned.split()
    # 提取长度 >= 2 的词
    terms = [t.strip() for t in tokens if len(t.strip()) >= 2]
    return terms


class DatasourceRouter:
    """
    数据源路由器。

    使用方式：
        router = DatasourceRouter(tableau_db=db)
        result = router.route(question="上个月各区域销售额", connection_id=None)
    """

    def __init__(self, tableau_db=None):
        """
        Args:
            tableau_db: Tableau 数据库实例
        """
        self.tableau_db = tableau_db

    def get_active_connection(self, connection_id: int = None):
        """
        获取连接（C4：如果 connection_id=None，自动选第一个活跃连接）。

        Returns:
            (connection, connection_id) 元组
        """
        from services.tableau.models import TableauConnection

        if self.tableau_db is None:
            from services.tableau.models import TableauDatabase
            self.tableau_db = TableauDatabase()

        session = self.tableau_db.session
        try:
            if connection_id is not None:
                conn = session.query(TableauConnection).filter(
                    TableauConnection.id == connection_id,
                    TableauConnection.is_active == True,
                ).first()
                return conn, connection_id

            # C4: 自动选第一个活跃连接
            conn = session.query(TableauConnection).filter(
                TableauConnection.is_active == True,
            ).order_by(TableauConnection.id.asc()).first()

            if conn:
                logger.debug(
                    "route_datasource: connection_id=None，自动路由到 connection_id=%d",
                    conn.id,
                )
                return conn, conn.id

            return None, None
        finally:
            pass  # 不关闭 session，由调用方管理

    def get_cached_fields(self, asset_id: int) -> List[str]:
        """
        获取数据源字段列表（带 Redis 缓存，Spec 14 §7.1）。

        Args:
            asset_id: TableauAsset.id

        Returns:
            field_caption 列表
        """
        # 先查缓存
        cached = get_cached_datasource_fields(asset_id)
        if cached is not None:
            logger.debug("缓存命中 asset_id=%d, field_count=%d", asset_id, len(cached))
            return cached

        # 缓存未命中，查数据库
        from services.tableau.models import TableauDatasourceField

        session = self.tableau_db.session
        field_records = session.query(TableauDatasourceField).filter(
            TableauDatasourceField.asset_id == asset_id
        ).all()

        field_captions = [
            f.field_caption or f.field_name
            for f in field_records
            if f.field_caption or f.field_name
        ]

        # 写入缓存
        cache_datasource_fields(asset_id, field_captions)
        logger.debug("缓存写入 asset_id=%d, field_count=%d", asset_id, len(field_captions))

        return field_captions

    def route(
        self,
        question: str,
        connection_id: int = None,
    ) -> Optional[DatasourceCandidate]:
        """
        执行数据源路由。

        Args:
            question: 用户问题
            connection_id: 连接 ID（可选）

        Returns:
            DatasourceCandidate 如果找到匹配，否则 None
        """
        from services.tableau.models import TableauAsset, TableauConnection

        if self.tableau_db is None:
            from services.tableau.models import TableauDatabase
            self.tableau_db = TableauDatabase()

        session = self.tableau_db.session

        # C4: connection_id=None 时自动选第一个活跃连接
        if connection_id is None:
            active_conn = session.query(TableauConnection).filter(
                TableauConnection.is_active == True,
            ).order_by(TableauConnection.id.asc()).first()
            if active_conn:
                connection_id = active_conn.id
                logger.debug("route: connection_id=None，自动路由到 connection_id=%d", connection_id)
            else:
                logger.warning("route: connection_id=None 且无活跃连接")

        # 1. 获取候选数据源
        query = session.query(TableauAsset).filter(
            TableauAsset.is_deleted == False,
            TableauAsset.asset_type == "datasource",
        )
        if connection_id is not None:
            query = query.filter(TableauAsset.connection_id == connection_id)
        candidates = query.all()

        if not candidates:
            return None

        # 2. 提取用户问题中的字段候选词
        user_terms = extract_terms(question)

        # 3. 对每个数据源评分
        scored = []
        for ds in candidates:
            # 获取字段列表（强制走 Redis 缓存）
            field_captions = self.get_cached_fields(ds.id)
            score = calculate_routing_score(
                user_terms=user_terms,
                field_captions=field_captions,
                last_sync_at=ds.last_sync_at,
                field_count=len(field_captions),
                query_count=0,  # TODO: 从查询日志获取
            )
            scored.append((ds, score))

        # 4. 按得分排序
        scored.sort(key=lambda x: x[1], reverse=True)

        if scored[0][1] < MIN_ROUTING_SCORE:
            return None

        best_ds, best_score = scored[0]
        return DatasourceCandidate(
            datasource_luid=best_ds.tableau_id,
            datasource_name=best_ds.name,
            connection_id=best_ds.connection_id,
            score=best_score,
        )


# 全局单例
_router: Optional[DatasourceRouter] = None


def get_datasource_router() -> DatasourceRouter:
    """获取数据源路由器单例"""
    global _router
    if _router is None:
        _router = DatasourceRouter()
    return _router
