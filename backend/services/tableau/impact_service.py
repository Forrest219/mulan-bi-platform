"""Tableau 资产影响分析服务（SPEC 40）

职责：
- get_asset_impact：查询单个 datasource 资产的两级影响树
- get_impact_alerts：查询连接级健康预警（health_score < 60 的 datasource）

架构约束：
- 不得 import app.api 层任何内容
- 所有 SQL 使用 SQLAlchemy ORM 或 text() + 绑定参数
- 所有查询强制限定 connection_id，防止跨连接污染
"""
from typing import Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy import text


class ImpactService:
    def __init__(self, db: Session):
        self.db = db

    def get_asset_impact(self, asset_id: int) -> Dict[str, Any]:
        """查询 datasource 资产的两级影响树。

        Args:
            asset_id: 资产 ID（整数主键）

        Returns:
            {
                datasource: {...},
                affected_workbooks: [
                    {id, name, asset_type, affected_views: [{id, name, asset_type}]}
                ],
                summary: {workbook_count, view_dashboard_count}
            }

        Raises:
            ValueError: 资产不存在或 asset_type != 'datasource'
        """
        from services.tableau.models import TableauAsset, TableauAssetDatasource

        # 1. 获取 datasource 资产，校验类型
        asset = self.db.query(TableauAsset).filter(
            TableauAsset.id == asset_id,
            TableauAsset.is_deleted == False,  # noqa: E712
        ).first()

        if asset is None or asset.asset_type != "datasource":
            raise ValueError(f"资产 {asset_id} 不存在或类型不是 datasource")

        connection_id = asset.connection_id
        datasource_name = asset.name

        # 2. 找出引用该 datasource 的 workbook（精确匹配 → ILIKE fallback）
        workbook_ids = self._find_affected_workbook_ids(
            datasource_name=datasource_name,
            connection_id=connection_id,
        )

        # 3. 对每个 workbook 查询其下 view/dashboard
        affected_workbooks = []
        total_view_dashboard_count = 0

        for wb_id in workbook_ids:
            wb = self.db.query(TableauAsset).filter(
                TableauAsset.id == wb_id,
                TableauAsset.connection_id == connection_id,
                TableauAsset.is_deleted == False,  # noqa: E712
            ).first()
            if wb is None:
                continue

            views = self.db.query(TableauAsset).filter(
                TableauAsset.connection_id == connection_id,
                TableauAsset.parent_workbook_name == wb.name,
                TableauAsset.asset_type.in_(["view", "dashboard"]),
                TableauAsset.is_deleted == False,  # noqa: E712
            ).all()

            affected_views = [
                {"id": v.id, "name": v.name, "asset_type": v.asset_type}
                for v in views
            ]
            total_view_dashboard_count += len(affected_views)

            affected_workbooks.append({
                "id": wb.id,
                "name": wb.name,
                "asset_type": wb.asset_type,
                "affected_views": affected_views,
            })

        return {
            "datasource": {
                "id": asset.id,
                "name": asset.name,
                "health_score": asset.health_score,
                "asset_type": asset.asset_type,
            },
            "affected_workbooks": affected_workbooks,
            "summary": {
                "workbook_count": len(affected_workbooks),
                "view_dashboard_count": total_view_dashboard_count,
            },
        }

    def get_impact_alerts(self, connection_id: int) -> Dict[str, Any]:
        """查询连接级健康预警（health_score < 60 的 datasource）。

        Args:
            connection_id: 连接 ID

        Returns:
            {
                alerts: [{datasource_id, datasource_name, health_score,
                          affected_workbook_count, affected_view_dashboard_count}],
                total_unhealthy_datasources: int,
                total_affected_workbooks: int,
            }
        """
        from services.tableau.models import TableauAsset

        # 1. 查询不健康 datasource（health_score < 60）
        unhealthy_ds = self.db.query(TableauAsset).filter(
            TableauAsset.connection_id == connection_id,
            TableauAsset.asset_type == "datasource",
            TableauAsset.health_score < 60,
            TableauAsset.is_deleted == False,  # noqa: E712
        ).order_by(TableauAsset.health_score.asc()).all()

        alerts: List[Dict[str, Any]] = []
        total_affected_workbooks = 0

        for ds in unhealthy_ds:
            counts = self._count_downstream(
                datasource_name=ds.name,
                connection_id=connection_id,
            )
            total_affected_workbooks += counts["workbook_count"]
            alerts.append({
                "datasource_id": ds.id,
                "datasource_name": ds.name,
                "health_score": ds.health_score,
                "affected_workbook_count": counts["workbook_count"],
                "affected_view_dashboard_count": counts["view_dashboard_count"],
            })

        return {
            "alerts": alerts,
            "total_unhealthy_datasources": len(unhealthy_ds),
            "total_affected_workbooks": total_affected_workbooks,
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _find_affected_workbook_ids(
        self, datasource_name: str, connection_id: int
    ) -> List[int]:
        """返回引用了指定 datasource_name 的 workbook 资产 ID 列表。

        先精确匹配，无结果再 ILIKE 模糊匹配。
        所有查询限定 connection_id。
        """
        # 精确匹配
        exact_rows = self.db.execute(
            text(
                """
                SELECT DISTINCT ta.id
                FROM tableau_asset_datasources tad
                JOIN tableau_assets ta
                    ON ta.id = tad.asset_id
                    AND ta.connection_id = :conn_id
                    AND ta.asset_type = 'workbook'
                    AND ta.is_deleted = false
                WHERE tad.datasource_name = :ds_name
                """
            ),
            {"conn_id": connection_id, "ds_name": datasource_name},
        ).fetchall()

        if exact_rows:
            return [row[0] for row in exact_rows]

        # ILIKE fallback
        ilike_rows = self.db.execute(
            text(
                """
                SELECT DISTINCT ta.id
                FROM tableau_asset_datasources tad
                JOIN tableau_assets ta
                    ON ta.id = tad.asset_id
                    AND ta.connection_id = :conn_id
                    AND ta.asset_type = 'workbook'
                    AND ta.is_deleted = false
                WHERE tad.datasource_name ILIKE :ds_name_pattern
                """
            ),
            {"conn_id": connection_id, "ds_name_pattern": f"%{datasource_name}%"},
        ).fetchall()

        return [row[0] for row in ilike_rows]

    def _count_downstream(
        self, datasource_name: str, connection_id: int
    ) -> Dict[str, int]:
        """统计 datasource 下游 workbook 数量和 view/dashboard 数量（不展开树）。

        Returns:
            {"workbook_count": int, "view_dashboard_count": int}
        """
        workbook_ids = self._find_affected_workbook_ids(
            datasource_name=datasource_name,
            connection_id=connection_id,
        )
        workbook_count = len(workbook_ids)

        if workbook_count == 0:
            return {"workbook_count": 0, "view_dashboard_count": 0}

        # 查 workbook 名称，再统计 view/dashboard
        rows = self.db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM tableau_assets
                WHERE connection_id = :conn_id
                  AND asset_type IN ('view', 'dashboard')
                  AND is_deleted = false
                  AND parent_workbook_name IN (
                      SELECT name FROM tableau_assets
                      WHERE id = ANY(:wb_ids)
                        AND connection_id = :conn_id
                        AND is_deleted = false
                  )
                """
            ),
            {"conn_id": connection_id, "wb_ids": workbook_ids},
        ).fetchone()

        view_dashboard_count = rows[0] if rows else 0

        return {
            "workbook_count": workbook_count,
            "view_dashboard_count": int(view_dashboard_count),
        }
