"""DQC 事件发射器

集成 EventService（Spec 16），发射 dqc.* 事件。
事件类型已在 services/events/constants.py 注册。
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class DqcEventEmitter:
    """DQC 事件发射器"""

    def __init__(self):
        pass

    def emit_cycle_started(
        self,
        db: Session,
        cycle_id: str,
        trigger_type: str,
        scope: str,
        assets_total: int,
        actor_id: Optional[int] = None,
    ) -> None:
        self._emit(
            db,
            event_type="dqc.cycle.started",
            payload={
                "cycle_id": cycle_id,
                "trigger_type": trigger_type,
                "scope": scope,
                "assets_total": assets_total,
            },
            severity="info",
            actor_id=actor_id,
        )

    def emit_cycle_completed(
        self,
        db: Session,
        cycle_id: str,
        trigger_type: str,
        scope: str,
        status: str,
        duration_sec: int,
        assets_processed: int,
        assets_failed: int,
        rules_executed: int,
        p0_count: int,
        p1_count: int,
        actor_id: Optional[int] = None,
    ) -> None:
        severity = "warning" if (p0_count or p1_count) else "info"
        self._emit(
            db,
            event_type="dqc.cycle.completed",
            payload={
                "cycle_id": cycle_id,
                "trigger_type": trigger_type,
                "scope": scope,
                "status": status,
                "duration_sec": duration_sec,
                "assets_processed": assets_processed,
                "assets_failed": assets_failed,
                "rules_executed": rules_executed,
                "p0_count": p0_count,
                "p1_count": p1_count,
            },
            severity=severity,
            actor_id=actor_id,
        )

    def emit_asset_signal_changed(
        self,
        db: Session,
        asset_id: int,
        datasource_id: int,
        schema_name: str,
        table_name: str,
        display_name: Optional[str],
        cycle_id: str,
        prev_signal: str,
        current_signal: str,
        prev_confidence_score: Optional[float],
        current_confidence_score: float,
        worsening: bool,
        actor_id: Optional[int] = None,
    ) -> None:
        self._emit(
            db,
            event_type="dqc.asset.signal_changed",
            payload={
                "asset_id": asset_id,
                "datasource_id": datasource_id,
                "schema_name": schema_name,
                "table_name": table_name,
                "display_name": display_name,
                "cycle_id": cycle_id,
                "prev_signal": prev_signal,
                "current_signal": current_signal,
                "prev_confidence_score": prev_confidence_score,
                "current_confidence_score": current_confidence_score,
            },
            severity="warning" if worsening else "info",
            actor_id=actor_id,
        )

    def emit_asset_p0_triggered(
        self,
        db: Session,
        asset_id: int,
        datasource_id: int,
        schema_name: str,
        table_name: str,
        display_name: Optional[str],
        cycle_id: str,
        confidence_score: float,
        failing_dimensions: List[str],
        actor_id: Optional[int] = None,
    ) -> None:
        self._emit(
            db,
            event_type="dqc.asset.p0_triggered",
            payload={
                "asset_id": asset_id,
                "datasource_id": datasource_id,
                "schema_name": schema_name,
                "table_name": table_name,
                "display_name": display_name,
                "cycle_id": cycle_id,
                "signal": "P0",
                "confidence_score": confidence_score,
                "failing_dimensions": failing_dimensions,
            },
            severity="error",
            actor_id=actor_id,
        )

    def emit_asset_p1_triggered(
        self,
        db: Session,
        asset_id: int,
        datasource_id: int,
        schema_name: str,
        table_name: str,
        display_name: Optional[str],
        cycle_id: str,
        confidence_score: float,
        failing_dimensions: List[str],
        actor_id: Optional[int] = None,
    ) -> None:
        self._emit(
            db,
            event_type="dqc.asset.p1_triggered",
            payload={
                "asset_id": asset_id,
                "datasource_id": datasource_id,
                "schema_name": schema_name,
                "table_name": table_name,
                "display_name": display_name,
                "cycle_id": cycle_id,
                "signal": "P1",
                "confidence_score": confidence_score,
                "failing_dimensions": failing_dimensions,
            },
            severity="warning",
            actor_id=actor_id,
        )

    def emit_asset_recovered(
        self,
        db: Session,
        asset_id: int,
        datasource_id: int,
        schema_name: str,
        table_name: str,
        display_name: Optional[str],
        cycle_id: str,
        prev_signal: str,
        current_signal: str,
        actor_id: Optional[int] = None,
    ) -> None:
        self._emit(
            db,
            event_type="dqc.asset.recovered",
            payload={
                "asset_id": asset_id,
                "datasource_id": datasource_id,
                "schema_name": schema_name,
                "table_name": table_name,
                "display_name": display_name,
                "cycle_id": cycle_id,
                "prev_signal": prev_signal,
                "current_signal": current_signal,
            },
            severity="info",
            actor_id=actor_id,
        )

    def _emit(
        self,
        db: Session,
        event_type: str,
        payload: Dict[str, Any],
        severity: str,
        actor_id: Optional[int] = None,
    ) -> None:
        try:
            from services.events.event_service import emit_event

            emit_event(
                db,
                event_type=event_type,
                source_module="dqc",
                payload=payload,
                severity=severity,
                actor_id=actor_id,
            )
            db.commit()
        except Exception:
            logger.exception("failed to emit dqc event: %s", event_type)


def _is_worsening(prev: str, current: str) -> bool:
    from .constants import SIGNAL_PRIORITY

    return SIGNAL_PRIORITY.get(current, 0) > SIGNAL_PRIORITY.get(prev, 0)