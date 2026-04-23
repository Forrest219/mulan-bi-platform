"""DQC DAO

所有写操作不调用 db.commit()；事务边界由调用方（API / Celery orchestrator）管理。
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

from .constants import ALL_DIMENSIONS
from .models import (
    DqcAssetSnapshot,
    DqcCycle,
    DqcDimensionScore,
    DqcLlmAnalysis,
    DqcMonitoredAsset,
    DqcQualityRule,
    DqcRuleResult,
)


class DqcDatabase:
    """DQC 数据访问层"""

    # ==================== MonitoredAsset ====================

    def create_asset(self, db: Session, **kwargs) -> DqcMonitoredAsset:
        asset = DqcMonitoredAsset(**kwargs)
        db.add(asset)
        db.flush()
        db.refresh(asset)
        return asset

    def get_asset(self, db: Session, asset_id: int) -> Optional[DqcMonitoredAsset]:
        return db.query(DqcMonitoredAsset).filter(DqcMonitoredAsset.id == asset_id).first()

    def get_asset_by_natural_key(
        self, db: Session, datasource_id: int, schema_name: str, table_name: str
    ) -> Optional[DqcMonitoredAsset]:
        return (
            db.query(DqcMonitoredAsset)
            .filter(
                DqcMonitoredAsset.datasource_id == datasource_id,
                DqcMonitoredAsset.schema_name == schema_name,
                DqcMonitoredAsset.table_name == table_name,
            )
            .first()
        )

    def list_assets(
        self,
        db: Session,
        datasource_id: Optional[int] = None,
        status: Optional[str] = None,
        owner_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        q = db.query(DqcMonitoredAsset)
        if datasource_id is not None:
            q = q.filter(DqcMonitoredAsset.datasource_id == datasource_id)
        if status:
            q = q.filter(DqcMonitoredAsset.status == status)
        if owner_id is not None:
            q = q.filter(DqcMonitoredAsset.owner_id == owner_id)
        total = q.count()
        items = (
            q.order_by(DqcMonitoredAsset.id.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
            .all()
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if page_size else 1,
        }

    def update_asset(self, db: Session, asset_id: int, **fields) -> bool:
        asset = self.get_asset(db, asset_id)
        if not asset:
            return False
        for key, value in fields.items():
            if value is None:
                continue
            if hasattr(asset, key):
                setattr(asset, key, value)
        db.flush()
        return True

    def disable_asset(self, db: Session, asset_id: int) -> bool:
        asset = self.get_asset(db, asset_id)
        if not asset:
            return False
        asset.status = "disabled"
        db.flush()
        return True

    def list_enabled_assets(self, db: Session) -> List[DqcMonitoredAsset]:
        return (
            db.query(DqcMonitoredAsset)
            .filter(DqcMonitoredAsset.status == "enabled")
            .order_by(DqcMonitoredAsset.id.asc())
            .all()
        )

    # ==================== QualityRule ====================

    def create_rule(self, db: Session, **kwargs) -> DqcQualityRule:
        rule = DqcQualityRule(**kwargs)
        db.add(rule)
        db.flush()
        db.refresh(rule)
        return rule

    def bulk_create_rules(self, db: Session, rules: List[dict]) -> List[DqcQualityRule]:
        objs = [DqcQualityRule(**r) for r in rules]
        for obj in objs:
            db.add(obj)
        db.flush()
        return objs

    def get_rule(self, db: Session, rule_id: int) -> Optional[DqcQualityRule]:
        return db.query(DqcQualityRule).filter(DqcQualityRule.id == rule_id).first()

    def list_rules_by_asset(
        self,
        db: Session,
        asset_id: int,
        dimension: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_system_suggested: Optional[bool] = None,
    ) -> List[DqcQualityRule]:
        q = db.query(DqcQualityRule).filter(DqcQualityRule.asset_id == asset_id)
        if dimension:
            q = q.filter(DqcQualityRule.dimension == dimension)
        if is_active is not None:
            q = q.filter(DqcQualityRule.is_active == is_active)
        if is_system_suggested is not None:
            q = q.filter(DqcQualityRule.is_system_suggested == is_system_suggested)
        return q.order_by(DqcQualityRule.id.desc()).all()

    def count_rules_by_asset(self, db: Session, asset_id: int) -> Dict[str, int]:
        total = db.query(func.count(DqcQualityRule.id)).filter(DqcQualityRule.asset_id == asset_id).scalar() or 0
        active = (
            db.query(func.count(DqcQualityRule.id))
            .filter(DqcQualityRule.asset_id == asset_id, DqcQualityRule.is_active == True)
            .scalar()
            or 0
        )
        return {"total": total, "active": active}

    def rule_name_exists(self, db: Session, asset_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
        q = db.query(DqcQualityRule).filter(
            DqcQualityRule.asset_id == asset_id, DqcQualityRule.name == name
        )
        if exclude_id is not None:
            q = q.filter(DqcQualityRule.id != exclude_id)
        return q.first() is not None

    def update_rule(self, db: Session, rule_id: int, **fields) -> bool:
        rule = self.get_rule(db, rule_id)
        if not rule:
            return False
        protected = {"id", "asset_id", "dimension", "rule_type", "created_by", "created_at"}
        for key, value in fields.items():
            if key in protected or value is None:
                continue
            if hasattr(rule, key):
                setattr(rule, key, value)
        db.flush()
        return True

    def delete_rule(self, db: Session, rule_id: int) -> bool:
        rule = self.get_rule(db, rule_id)
        if not rule:
            return False
        db.delete(rule)
        db.flush()
        return True

    # ==================== Cycle ====================

    def create_cycle(self, db: Session, **kwargs) -> DqcCycle:
        cycle = DqcCycle(**kwargs)
        db.add(cycle)
        db.flush()
        db.refresh(cycle)
        return cycle

    def get_cycle(self, db: Session, cycle_id: UUID) -> Optional[DqcCycle]:
        return db.query(DqcCycle).filter(DqcCycle.id == cycle_id).first()

    def mark_cycle_running(self, db: Session, cycle_id: UUID, assets_total: int) -> None:
        cycle = self.get_cycle(db, cycle_id)
        if not cycle:
            return
        cycle.status = "running"
        cycle.assets_total = assets_total
        cycle.started_at = datetime.utcnow()
        db.flush()

    def mark_cycle_completed(
        self,
        db: Session,
        cycle_id: UUID,
        status: str,
        assets_processed: int,
        assets_failed: int,
        rules_executed: int,
        p0_count: int,
        p1_count: int,
        error_message: Optional[str] = None,
    ) -> None:
        cycle = self.get_cycle(db, cycle_id)
        if not cycle:
            return
        cycle.status = status
        cycle.assets_processed = assets_processed
        cycle.assets_failed = assets_failed
        cycle.rules_executed = rules_executed
        cycle.p0_count = p0_count
        cycle.p1_count = p1_count
        cycle.error_message = error_message
        cycle.completed_at = datetime.utcnow()
        db.flush()

    def list_cycles(
        self,
        db: Session,
        status: Optional[str] = None,
        scope: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        q = db.query(DqcCycle)
        if status:
            q = q.filter(DqcCycle.status == status)
        if scope:
            q = q.filter(DqcCycle.scope == scope)
        if start:
            q = q.filter(DqcCycle.created_at >= start)
        if end:
            q = q.filter(DqcCycle.created_at <= end)
        total = q.count()
        items = (
            q.order_by(DqcCycle.created_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
            .all()
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if page_size else 1,
        }

    def active_cycle_exists(self, db: Session, scope: Optional[str] = None) -> bool:
        q = db.query(DqcCycle).filter(DqcCycle.status.in_(["pending", "running"]))
        if scope:
            q = q.filter(DqcCycle.scope == scope)
        return q.first() is not None

    # ==================== DimensionScore (Append-Only) ====================

    def insert_dimension_score(self, db: Session, **kwargs) -> DqcDimensionScore:
        row = DqcDimensionScore(**kwargs)
        db.add(row)
        db.flush()
        return row

    def bulk_insert_dimension_scores(self, db: Session, rows: List[dict]) -> None:
        if not rows:
            return
        db.bulk_insert_mappings(DqcDimensionScore, rows)
        db.flush()

    def get_latest_dimension_scores(self, db: Session, asset_id: int) -> Dict[str, DqcDimensionScore]:
        out: Dict[str, DqcDimensionScore] = {}
        for dim in ALL_DIMENSIONS:
            row = (
                db.query(DqcDimensionScore)
                .filter(DqcDimensionScore.asset_id == asset_id, DqcDimensionScore.dimension == dim)
                .order_by(DqcDimensionScore.computed_at.desc())
                .first()
            )
            if row:
                out[dim] = row
        return out

    def get_prev_dimension_scores(
        self, db: Session, asset_id: int, before: datetime
    ) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for dim in ALL_DIMENSIONS:
            row = (
                db.query(DqcDimensionScore)
                .filter(
                    DqcDimensionScore.asset_id == asset_id,
                    DqcDimensionScore.dimension == dim,
                    DqcDimensionScore.computed_at < before,
                )
                .order_by(DqcDimensionScore.computed_at.desc())
                .first()
            )
            if row:
                out[dim] = row.score
        return out

    def get_7d_avg_dimension_scores(
        self, db: Session, asset_id: int, now: Optional[datetime] = None
    ) -> Dict[str, float]:
        ref = now or datetime.utcnow()
        start = ref - timedelta(days=7)
        out: Dict[str, float] = {}
        rows = (
            db.query(
                DqcDimensionScore.dimension,
                func.avg(DqcDimensionScore.score).label("avg_score"),
            )
            .filter(
                DqcDimensionScore.asset_id == asset_id,
                DqcDimensionScore.computed_at >= start,
                DqcDimensionScore.computed_at < ref,
            )
            .group_by(DqcDimensionScore.dimension)
            .all()
        )
        for dim, avg_score in rows:
            if avg_score is not None:
                out[dim] = float(avg_score)
        return out

    def list_dimension_scores(
        self,
        db: Session,
        asset_id: int,
        dimension: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[DqcDimensionScore]:
        q = db.query(DqcDimensionScore).filter(DqcDimensionScore.asset_id == asset_id)
        if dimension:
            q = q.filter(DqcDimensionScore.dimension == dimension)
        if start:
            q = q.filter(DqcDimensionScore.computed_at >= start)
        if end:
            q = q.filter(DqcDimensionScore.computed_at <= end)
        return q.order_by(DqcDimensionScore.computed_at.desc()).limit(limit).all()

    # ==================== Snapshot (Append-Only) ====================

    def insert_snapshot(self, db: Session, **kwargs) -> DqcAssetSnapshot:
        snap = DqcAssetSnapshot(**kwargs)
        db.add(snap)
        db.flush()
        return snap

    def get_latest_snapshot(self, db: Session, asset_id: int) -> Optional[DqcAssetSnapshot]:
        return (
            db.query(DqcAssetSnapshot)
            .filter(DqcAssetSnapshot.asset_id == asset_id)
            .order_by(DqcAssetSnapshot.computed_at.desc())
            .first()
        )

    def list_snapshots(
        self,
        db: Session,
        asset_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 30,
    ) -> List[DqcAssetSnapshot]:
        q = db.query(DqcAssetSnapshot).filter(DqcAssetSnapshot.asset_id == asset_id)
        if start:
            q = q.filter(DqcAssetSnapshot.computed_at >= start)
        if end:
            q = q.filter(DqcAssetSnapshot.computed_at <= end)
        return q.order_by(DqcAssetSnapshot.computed_at.desc()).limit(limit).all()

    def get_snapshots_for_cycle(self, db: Session, cycle_id: UUID) -> List[DqcAssetSnapshot]:
        return (
            db.query(DqcAssetSnapshot)
            .filter(DqcAssetSnapshot.cycle_id == cycle_id)
            .order_by(DqcAssetSnapshot.id.asc())
            .all()
        )

    # ==================== RuleResult (Append-Only) ====================

    def insert_rule_result(self, db: Session, **kwargs) -> DqcRuleResult:
        row = DqcRuleResult(**kwargs)
        db.add(row)
        db.flush()
        return row

    def bulk_insert_rule_results(self, db: Session, rows: List[dict]) -> None:
        if not rows:
            return
        db.bulk_insert_mappings(DqcRuleResult, rows)
        db.flush()

    def get_rule_results_for_cycle(
        self, db: Session, cycle_id: UUID, asset_id: Optional[int] = None
    ) -> List[DqcRuleResult]:
        q = db.query(DqcRuleResult).filter(DqcRuleResult.cycle_id == cycle_id)
        if asset_id is not None:
            q = q.filter(DqcRuleResult.asset_id == asset_id)
        return q.order_by(DqcRuleResult.id.asc()).all()

    def get_failed_results_for_asset(
        self, db: Session, cycle_id: UUID, asset_id: int, limit: int = 10
    ) -> List[DqcRuleResult]:
        return (
            db.query(DqcRuleResult)
            .filter(
                DqcRuleResult.cycle_id == cycle_id,
                DqcRuleResult.asset_id == asset_id,
                DqcRuleResult.passed == False,
            )
            .order_by(DqcRuleResult.id.asc())
            .limit(limit)
            .all()
        )

    # ==================== LlmAnalysis ====================

    def insert_llm_analysis(self, db: Session, **kwargs) -> DqcLlmAnalysis:
        row = DqcLlmAnalysis(**kwargs)
        db.add(row)
        db.flush()
        db.refresh(row)
        return row

    def get_llm_analysis(self, db: Session, analysis_id: int) -> Optional[DqcLlmAnalysis]:
        return db.query(DqcLlmAnalysis).filter(DqcLlmAnalysis.id == analysis_id).first()

    def list_llm_analyses_for_asset(
        self,
        db: Session,
        asset_id: int,
        trigger: Optional[str] = None,
        limit: int = 20,
    ) -> List[DqcLlmAnalysis]:
        q = db.query(DqcLlmAnalysis).filter(DqcLlmAnalysis.asset_id == asset_id)
        if trigger:
            q = q.filter(DqcLlmAnalysis.trigger == trigger)
        return q.order_by(DqcLlmAnalysis.created_at.desc()).limit(limit).all()

    # ==================== Dashboard ====================

    def get_dashboard_summary(self, db: Session) -> Dict[str, Any]:
        total_assets = (
            db.query(func.count(DqcMonitoredAsset.id))
            .filter(DqcMonitoredAsset.status == "enabled")
            .scalar()
            or 0
        )

        latest_subq = (
            db.query(
                DqcAssetSnapshot.asset_id.label("asset_id"),
                func.max(DqcAssetSnapshot.id).label("max_id"),
            )
            .group_by(DqcAssetSnapshot.asset_id)
            .subquery()
        )
        latest_rows = (
            db.query(DqcAssetSnapshot)
            .join(latest_subq, DqcAssetSnapshot.id == latest_subq.c.max_id)
            .all()
        )

        signal_counts = {"GREEN": 0, "P1": 0, "P0": 0}
        scores: List[float] = []
        for row in latest_rows:
            signal_counts[row.signal] = signal_counts.get(row.signal, 0) + 1
            scores.append(row.confidence_score)

        avg_cs = round(sum(scores) / len(scores), 2) if scores else 0.0

        last_cycle = (
            db.query(DqcCycle)
            .filter(DqcCycle.status.in_(["completed", "partial"]))
            .order_by(DqcCycle.completed_at.desc())
            .first()
        )

        return {
            "total_assets": total_assets,
            "assets_green": signal_counts.get("GREEN", 0),
            "assets_p1": signal_counts.get("P1", 0),
            "assets_p0": signal_counts.get("P0", 0),
            "avg_confidence_score": avg_cs,
            "last_cycle_at": last_cycle.completed_at.strftime("%Y-%m-%d %H:%M:%S")
            if last_cycle and last_cycle.completed_at
            else None,
            "last_cycle_id": str(last_cycle.id) if last_cycle else None,
            "signal_distribution": signal_counts,
        }

    def get_top_failing_assets(self, db: Session, limit: int = 10) -> List[Dict[str, Any]]:
        latest_subq = (
            db.query(
                DqcAssetSnapshot.asset_id.label("asset_id"),
                func.max(DqcAssetSnapshot.id).label("max_id"),
            )
            .group_by(DqcAssetSnapshot.asset_id)
            .subquery()
        )
        rows = (
            db.query(DqcAssetSnapshot)
            .join(latest_subq, DqcAssetSnapshot.id == latest_subq.c.max_id)
            .filter(DqcAssetSnapshot.signal.in_(["P0", "P1"]))
            .order_by(DqcAssetSnapshot.confidence_score.asc())
            .limit(limit)
            .all()
        )
        out = []
        for snap in rows:
            asset = self.get_asset(db, snap.asset_id)
            dim_scores = snap.dimension_scores or {}
            top_failed_dim = None
            lowest = None
            for dim_name, dim_score in dim_scores.items():
                if lowest is None or dim_score < lowest:
                    lowest = dim_score
                    top_failed_dim = dim_name
            out.append(
                {
                    "asset_id": snap.asset_id,
                    "display_name": (asset.display_name or f"{asset.schema_name}.{asset.table_name}")
                    if asset
                    else str(snap.asset_id),
                    "signal": snap.signal,
                    "confidence_score": snap.confidence_score,
                    "top_failed_dimension": top_failed_dim,
                }
            )
        return out

    def get_dimension_avg(self, db: Session) -> Dict[str, float]:
        latest_subq = (
            db.query(
                DqcDimensionScore.asset_id.label("asset_id"),
                DqcDimensionScore.dimension.label("dimension"),
                func.max(DqcDimensionScore.computed_at).label("max_at"),
            )
            .group_by(DqcDimensionScore.asset_id, DqcDimensionScore.dimension)
            .subquery()
        )
        rows = (
            db.query(
                DqcDimensionScore.dimension,
                func.avg(DqcDimensionScore.score).label("avg_score"),
            )
            .join(
                latest_subq,
                and_(
                    DqcDimensionScore.asset_id == latest_subq.c.asset_id,
                    DqcDimensionScore.dimension == latest_subq.c.dimension,
                    DqcDimensionScore.computed_at == latest_subq.c.max_at,
                ),
            )
            .group_by(DqcDimensionScore.dimension)
            .all()
        )
        out: Dict[str, float] = {dim: 0.0 for dim in ALL_DIMENSIONS}
        for dim, avg_score in rows:
            if avg_score is not None:
                out[dim] = round(float(avg_score), 2)
        return out

    def get_recent_signal_changes(
        self, db: Session, hours: int = 24, limit: int = 20
    ) -> List[Dict[str, Any]]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        rows = (
            db.query(DqcAssetSnapshot)
            .filter(
                DqcAssetSnapshot.computed_at >= cutoff,
                DqcAssetSnapshot.prev_signal.isnot(None),
                DqcAssetSnapshot.prev_signal != DqcAssetSnapshot.signal,
            )
            .order_by(DqcAssetSnapshot.computed_at.desc())
            .limit(limit)
            .all()
        )
        out = []
        for snap in rows:
            asset = self.get_asset(db, snap.asset_id)
            display_name = (
                f"{asset.schema_name}.{asset.table_name}" if asset else str(snap.asset_id)
            )
            out.append(
                {
                    "asset_id": snap.asset_id,
                    "display_name": display_name,
                    "prev_signal": snap.prev_signal,
                    "current_signal": snap.signal,
                    "changed_at": snap.computed_at.strftime("%Y-%m-%d %H:%M:%S")
                    if snap.computed_at
                    else None,
                }
            )
        return out
