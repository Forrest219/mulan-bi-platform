"""数仓资产血缘服务

实现 Spec §5.12-§5.14 血缘拓扑查询、手工血缘创建与删除。
"""
import logging
from typing import Optional, Dict, Any, List, Set

from sqlalchemy.orm import Session

from services.dw_assets.models import DwAssetTable, DwAssetLineageEdge

logger = logging.getLogger(__name__)


class LineageService:
    """数仓资产血缘服务"""

    # 最大 BFS 深度
    MAX_DEPTH = 3

    def get_lineage(
        self,
        db: Session,
        table_id: int,
        depth: int = 1,
        direction: str = "both",
        level: str = "table",
    ) -> Dict[str, Any]:
        """
        获取以 table_id 为中心的血缘拓扑图。

        BFS 遍历最多 depth 层 (上限 3)。

        Args:
            db: SQLAlchemy Session
            table_id: 中心表 ID
            depth: 展开深度 1-3
            direction: upstream / downstream / both
            level: table / column

        Returns:
            { nodes: [...], edges: [...], center: "table:{id}", depth: int }
        """
        depth = min(max(1, depth), self.MAX_DEPTH)

        # 验证中心表存在
        center_table = (
            db.query(DwAssetTable)
            .filter(
                DwAssetTable.id == table_id,
                DwAssetTable.is_deleted == False,  # noqa: E712
            )
            .first()
        )
        if not center_table:
            return {"error": True, "code": "DWASSET_001", "message": "数仓资产不存在"}

        # BFS 收集节点和边
        visited_table_ids: Set[int] = {table_id}
        collected_edges: List[DwAssetLineageEdge] = []

        # BFS 按层遍历
        current_layer = {table_id}

        for _ in range(depth):
            next_layer: Set[int] = set()
            edges_batch = self._fetch_edges(db, current_layer, direction, level)

            for edge in edges_batch:
                collected_edges.append(edge)
                # 确定邻居节点
                if edge.source_table_id and edge.source_table_id not in visited_table_ids:
                    next_layer.add(edge.source_table_id)
                    visited_table_ids.add(edge.source_table_id)
                if edge.target_table_id and edge.target_table_id not in visited_table_ids:
                    next_layer.add(edge.target_table_id)
                    visited_table_ids.add(edge.target_table_id)

            if not next_layer:
                break
            current_layer = next_layer

        # 构建 nodes
        nodes = self._build_nodes(db, visited_table_ids)

        # 构建 edges (去重)
        seen_edge_ids: Set[int] = set()
        edges_output = []
        for edge in collected_edges:
            if edge.id in seen_edge_ids:
                continue
            seen_edge_ids.add(edge.id)
            edges_output.append({
                "id": f"edge:{edge.id}",
                "source": f"table:{edge.source_table_id}" if edge.source_table_id else None,
                "target": f"table:{edge.target_table_id}",
                "relation_type": edge.relation_type,
                "confidence": edge.confidence,
            })

        return {
            "nodes": nodes,
            "edges": edges_output,
            "center": f"table:{table_id}",
            "depth": depth,
        }

    def create_manual_lineage(
        self,
        db: Session,
        table_id: int,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        创建手工血缘边。

        验证：无自环、source 存在。

        Args:
            db: SQLAlchemy Session
            table_id: 当前操作所属表 (target_table_id 或 source_table_id)
            data: 血缘边数据

        Returns:
            新建的边 dict 或错误 dict
        """
        lineage_type = data.get("lineage_type", "table")
        source_table_id = data.get("source_table_id")
        target_table_id = data.get("target_table_id")
        relation_type = data.get("relation_type", "manual")
        transformation_logic = data.get("transformation_logic")
        source_column_id = data.get("source_column_id")
        target_column_id = data.get("target_column_id")

        # 验证 source 和 target 不能相同 (自环检测)
        if source_table_id and target_table_id and source_table_id == target_table_id:
            return {"error": True, "code": "DWASSET_008", "message": "血缘关系不允许自环"}

        # 验证 source_table 存在
        if source_table_id:
            source_exists = (
                db.query(DwAssetTable)
                .filter(
                    DwAssetTable.id == source_table_id,
                    DwAssetTable.is_deleted == False,  # noqa: E712
                )
                .first()
            )
            if not source_exists:
                return {"error": True, "code": "DWASSET_008", "message": "上游表不存在"}

        # 验证 target_table 存在
        if target_table_id:
            target_exists = (
                db.query(DwAssetTable)
                .filter(
                    DwAssetTable.id == target_table_id,
                    DwAssetTable.is_deleted == False,  # noqa: E712
                )
                .first()
            )
            if not target_exists:
                return {"error": True, "code": "DWASSET_008", "message": "下游表不存在"}
        else:
            return {"error": True, "code": "DWASSET_008", "message": "下游表 ID 不能为空"}

        # 验证字段级血缘完整性
        if lineage_type == "column":
            if not source_column_id or not target_column_id or not source_table_id:
                return {
                    "error": True,
                    "code": "DWASSET_008",
                    "message": "字段级血缘需要提供完整的上游表、上游字段和下游字段",
                }

        # 创建边
        edge = DwAssetLineageEdge(
            lineage_type=lineage_type,
            source_table_id=source_table_id,
            source_column_id=source_column_id if lineage_type == "column" else None,
            target_table_id=target_table_id,
            target_column_id=target_column_id if lineage_type == "column" else None,
            relation_type=relation_type,
            confidence=data.get("confidence", 1.0),
            source_system="manual",
            transformation_logic=transformation_logic,
        )
        db.add(edge)
        db.commit()

        # 触发受影响表的 downstream_count 刷新
        self._refresh_downstream_counts(db, source_table_id, target_table_id)

        return {"message": "血缘关系已创建", "edge": edge.to_dict()}

    def delete_manual_lineage(
        self,
        db: Session,
        table_id: int,
        edge_id: int,
    ) -> Dict[str, Any]:
        """
        删除手工血缘边。

        仅允许删除 source_system='manual' 的边。

        Args:
            db: SQLAlchemy Session
            table_id: 当前表 ID (用于验证关联)
            edge_id: 血缘边 ID

        Returns:
            操作结果
        """
        edge = db.query(DwAssetLineageEdge).filter(
            DwAssetLineageEdge.id == edge_id,
        ).first()

        if not edge:
            return {"error": True, "code": "DWASSET_008", "message": "血缘关系不存在"}

        # 验证边关联到当前表
        if edge.source_table_id != table_id and edge.target_table_id != table_id:
            return {"error": True, "code": "DWASSET_008", "message": "该血缘关系不属于当前表"}

        # 仅允许删除手工血缘
        if edge.source_system != "manual":
            return {
                "error": True,
                "code": "DWASSET_008",
                "message": "仅允许删除手工维护的血缘关系，自动解析的血缘需通过重新同步覆盖",
            }

        source_table_id = edge.source_table_id
        target_table_id = edge.target_table_id

        db.delete(edge)
        db.commit()

        # 触发受影响表的 downstream_count 刷新
        self._refresh_downstream_counts(db, source_table_id, target_table_id)

        return {"message": "血缘关系已删除", "success": True}

    # ─────────────────────────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_edges(
        self,
        db: Session,
        table_ids: Set[int],
        direction: str,
        level: str,
    ) -> List[DwAssetLineageEdge]:
        """获取一批表的相关血缘边"""
        if not table_ids:
            return []

        table_ids_list = list(table_ids)
        query = db.query(DwAssetLineageEdge)

        # level 过滤
        if level == "table":
            query = query.filter(DwAssetLineageEdge.lineage_type == "table")
        elif level == "column":
            query = query.filter(DwAssetLineageEdge.lineage_type == "column")

        # direction 过滤
        if direction == "upstream":
            # 当前表作为 target，找到上游 source
            query = query.filter(DwAssetLineageEdge.target_table_id.in_(table_ids_list))
        elif direction == "downstream":
            # 当前表作为 source，找到下游 target
            query = query.filter(DwAssetLineageEdge.source_table_id.in_(table_ids_list))
        else:
            # both
            query = query.filter(
                (DwAssetLineageEdge.source_table_id.in_(table_ids_list))
                | (DwAssetLineageEdge.target_table_id.in_(table_ids_list))
            )

        return query.all()

    def _build_nodes(
        self, db: Session, table_ids: Set[int]
    ) -> List[Dict[str, Any]]:
        """根据收集到的表 ID 构建节点列表"""
        if not table_ids:
            return []

        tables = (
            db.query(DwAssetTable)
            .filter(DwAssetTable.id.in_(list(table_ids)))
            .all()
        )

        nodes = []
        for table in tables:
            nodes.append({
                "id": f"table:{table.id}",
                "type": "table",
                "label": table.business_name or table.table_name,
                "table_id": table.id,
                "layer": table.layer,
                "heat_score": table.heat_score,
            })

        return nodes

    def _refresh_downstream_counts(
        self,
        db: Session,
        source_table_id: Optional[int],
        target_table_id: Optional[int],
    ) -> None:
        """
        刷新受影响表的热度分数 (downstream_count 变化影响 heat_score)。

        在血缘创建/删除后调用，避免详情页显示过期热度。
        """
        affected_ids = set()
        if source_table_id:
            affected_ids.add(source_table_id)
        if target_table_id:
            affected_ids.add(target_table_id)

        if not affected_ids:
            return

        try:
            from datetime import datetime

            for tid in affected_ids:
                table = db.query(DwAssetTable).filter(DwAssetTable.id == tid).first()
                if not table:
                    continue

                # 重新计算该表的 downstream_count 并更新热度
                downstream_count = (
                    db.query(DwAssetLineageEdge)
                    .filter(DwAssetLineageEdge.source_table_id == tid)
                    .count()
                )

                partition_bonus = 0
                if table.last_partition_at:
                    days_since = (datetime.utcnow() - table.last_partition_at).days
                    if days_since <= 7:
                        partition_bonus = 10

                heat = min(
                    100.0,
                    table.query_count_7d * 0.5
                    + table.query_count_30d * 0.1
                    + downstream_count * 3
                    + partition_bonus,
                )
                table.heat_score = round(heat, 1)

            db.commit()
        except Exception as e:
            logger.warning("刷新血缘受影响表热度失败: %s", str(e))
