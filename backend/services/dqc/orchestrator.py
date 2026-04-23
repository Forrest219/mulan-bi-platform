"""DQC cycle 编排器

职责：
  1. Redis 锁 dqc:cycle:lock:<scope> 防并发（TTL 见 constants）
  2. 创建 DqcCycle(status=pending) → running
  3. 查询 enabled 资产列表
  4. 按资产串行执行 Layer 1（规则执行）+ Layer 2（评分 / 信号判定）
  5. 按 spec §12.5 发射事件
  6. 更新 DqcCycle（completed/partial/failed）

Layer 3（LLM 根因）在 v1 不集成（专注 MVP 范围），为未来扩展预留接入点 `_run_layer3`。
"""
import logging
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.crypto import get_datasource_crypto
from app.core.database import SessionLocal

from .constants import (
    ALL_DIMENSIONS,
    CycleScope,
    CycleStatus,
    HOURLY_LIGHT_RULE_TYPES,
    LOCK_KEY_FULL,
    LOCK_KEY_HOURLY,
    LOCK_TTL_SECONDS_FULL,
    LOCK_TTL_SECONDS_HOURLY,
    SignalLevel,
    TriggerType,
)
from .database import DqcDatabase
from .drift_detector import DriftDetector
from .models import DqcMonitoredAsset, DqcQualityRule
from .rule_engine import DqcRuleEngine, RuleExecutionResult
from .scorer import DqcScorer

logger = logging.getLogger(__name__)


class CycleLockedError(Exception):
    """已有同 scope cycle 在运行"""


class _RedisLock:
    """Redis 分布式锁：SET NX EX，Lua 脚本释放"""

    RELEASE_SCRIPT = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end"
    )

    def __init__(self, key: str, ttl_seconds: int):
        self.key = key
        self.ttl = ttl_seconds
        self.token = secrets.token_hex(16)
        self._client = None
        self._acquired = False

    def _client_or_none(self):
        if self._client is not None:
            return self._client
        try:
            from services.common.redis_cache import get_redis_client
            self._client = get_redis_client()
        except Exception as exc:
            logger.warning("redis client unavailable: %s", exc)
            self._client = None
        return self._client

    def try_acquire(self) -> bool:
        client = self._client_or_none()
        if client is None:
            self._acquired = True
            return True
        try:
            ok = client.set(self.key, self.token, nx=True, ex=self.ttl)
            self._acquired = bool(ok)
            return self._acquired
        except Exception as exc:
            logger.warning("redis lock acquire failed: %s", exc)
            self._acquired = True
            return True

    def release(self) -> None:
        if not self._acquired:
            return
        client = self._client_or_none()
        if client is None:
            return
        try:
            client.eval(self.RELEASE_SCRIPT, 1, self.key, self.token)
        except Exception as exc:
            logger.warning("redis lock release failed: %s", exc)


class DqcOrchestrator:
    """DQC cycle 编排"""

    def __init__(self, dao: Optional[DqcDatabase] = None, scorer: Optional[DqcScorer] = None):
        self.dao = dao or DqcDatabase()
        self.scorer = scorer or DqcScorer()
        self.drift = DriftDetector(self.dao)

    # ==================================================================
    # 外部入口
    # ==================================================================

    def run_full_cycle(
        self, trigger_type: str = TriggerType.SCHEDULED.value, triggered_by: Optional[int] = None
    ) -> UUID:
        return self._run_cycle(
            scope=CycleScope.FULL.value,
            trigger_type=trigger_type,
            triggered_by=triggered_by,
            lock_key=LOCK_KEY_FULL,
            lock_ttl=LOCK_TTL_SECONDS_FULL,
            rule_type_filter=None,
            asset_ids=None,
        )

    def run_hourly_light_cycle(self, triggered_by: Optional[int] = None) -> UUID:
        return self._run_cycle(
            scope=CycleScope.HOURLY_LIGHT.value,
            trigger_type=TriggerType.SCHEDULED.value,
            triggered_by=triggered_by,
            lock_key=LOCK_KEY_HOURLY,
            lock_ttl=LOCK_TTL_SECONDS_HOURLY,
            rule_type_filter=HOURLY_LIGHT_RULE_TYPES,
            asset_ids=None,
        )

    def run_for_asset(
        self,
        asset_id: int,
        trigger_type: str = TriggerType.MANUAL.value,
        triggered_by: Optional[int] = None,
    ) -> UUID:
        lock_key = f"dqc:cycle:lock:asset:{asset_id}"
        lock_ttl = 600
        return self._run_cycle(
            scope=CycleScope.FULL.value,
            trigger_type=trigger_type,
            triggered_by=triggered_by,
            lock_key=lock_key,
            lock_ttl=lock_ttl,
            rule_type_filter=None,
            asset_ids=[asset_id],
        )

    # ==================================================================
    # 核心流程
    # ==================================================================

    def _run_cycle(
        self,
        scope: str,
        trigger_type: str,
        triggered_by: Optional[int],
        lock_key: Optional[str],
        lock_ttl: int,
        rule_type_filter: Optional[set],
        asset_ids: Optional[List[int]],
    ) -> UUID:
        lock: Optional[_RedisLock] = None
        if lock_key:
            lock = _RedisLock(lock_key, lock_ttl)
            if not lock.try_acquire():
                raise CycleLockedError(f"dqc cycle locked: {lock_key}")

        cycle_uuid = uuid4()
        db: Session = SessionLocal()
        try:
            cycle = self.dao.create_cycle(
                db,
                id=cycle_uuid,
                trigger_type=trigger_type,
                status=CycleStatus.PENDING.value,
                scope=scope,
                triggered_by=triggered_by,
            )
            db.commit()

            assets = self._pick_assets(db, asset_ids)
            self.dao.mark_cycle_running(db, cycle.id, assets_total=len(assets))
            db.commit()

            self._emit_event(
                db,
                event_type="dqc.cycle.started",
                payload={
                    "cycle_id": str(cycle.id),
                    "trigger_type": trigger_type,
                    "scope": scope,
                    "assets_total": len(assets),
                },
                severity="info",
                actor_id=triggered_by,
            )
            db.commit()

            stats = {
                "assets_processed": 0,
                "assets_failed": 0,
                "rules_executed": 0,
                "p0_count": 0,
                "p1_count": 0,
            }

            for asset in assets:
                try:
                    asset_result = self._process_asset(
                        db, cycle_uuid, asset, rule_type_filter, triggered_by
                    )
                    stats["assets_processed"] += 1
                    stats["rules_executed"] += asset_result["rules_executed"]
                    if asset_result["signal"] == SignalLevel.P0.value:
                        stats["p0_count"] += 1
                    elif asset_result["signal"] == SignalLevel.P1.value:
                        stats["p1_count"] += 1
                    db.commit()
                except Exception:
                    logger.exception("dqc process asset failed: asset_id=%s", asset.id)
                    db.rollback()
                    stats["assets_failed"] += 1

            if stats["assets_failed"] == 0:
                final_status = CycleStatus.COMPLETED.value
            elif stats["assets_processed"] == 0:
                final_status = CycleStatus.FAILED.value
            else:
                final_status = CycleStatus.PARTIAL.value

            self.dao.mark_cycle_completed(
                db,
                cycle_id=cycle_uuid,
                status=final_status,
                assets_processed=stats["assets_processed"],
                assets_failed=stats["assets_failed"],
                rules_executed=stats["rules_executed"],
                p0_count=stats["p0_count"],
                p1_count=stats["p1_count"],
            )

            severity = "warning" if (stats["p0_count"] or stats["p1_count"]) else "info"
            duration_sec = 0
            cycle_row = self.dao.get_cycle(db, cycle_uuid)
            if cycle_row and cycle_row.started_at and cycle_row.completed_at:
                duration_sec = int((cycle_row.completed_at - cycle_row.started_at).total_seconds())

            self._emit_event(
                db,
                event_type="dqc.cycle.completed",
                payload={
                    "cycle_id": str(cycle_uuid),
                    "trigger_type": trigger_type,
                    "scope": scope,
                    "status": final_status,
                    "duration_sec": duration_sec,
                    "assets_processed": stats["assets_processed"],
                    "assets_failed": stats["assets_failed"],
                    "rules_executed": stats["rules_executed"],
                    "p0_count": stats["p0_count"],
                    "p1_count": stats["p1_count"],
                },
                severity=severity,
                actor_id=triggered_by,
            )
            db.commit()
            return cycle_uuid
        except Exception as exc:
            db.rollback()
            try:
                self.dao.mark_cycle_completed(
                    db,
                    cycle_id=cycle_uuid,
                    status=CycleStatus.FAILED.value,
                    assets_processed=0,
                    assets_failed=0,
                    rules_executed=0,
                    p0_count=0,
                    p1_count=0,
                    error_message="orchestrator_exception",
                )
                db.commit()
            except Exception:
                db.rollback()
            self._emit_event(
                db,
                event_type="dqc.cycle.completed",
                payload={
                    "cycle_id": str(cycle_uuid),
                    "status": "failed",
                    "error_message": str(exc),
                    "scope": scope,
                    "triggered_by": triggered_by,
                },
                severity="error",
                actor_id=None,
            )
            try:
                db.commit()
            except Exception:
                db.rollback()
            raise
        finally:
            db.close()
            if lock is not None:
                lock.release()

    # ==================================================================
    # 资产处理
    # ==================================================================

    def _pick_assets(
        self, db: Session, asset_ids: Optional[List[int]]
    ) -> List[DqcMonitoredAsset]:
        if asset_ids:
            out: List[DqcMonitoredAsset] = []
            for aid in asset_ids:
                asset = self.dao.get_asset(db, aid)
                if asset and asset.status == "enabled":
                    out.append(asset)
            return out
        return self.dao.list_enabled_assets(db)

    def _process_asset(
        self,
        db: Session,
        cycle_id: UUID,
        asset: DqcMonitoredAsset,
        rule_type_filter: Optional[set],
        actor_id: Optional[int],
    ) -> Dict[str, Any]:
        rules = self.dao.list_rules_by_asset(db, asset.id, is_active=True)
        if rule_type_filter:
            rules = [r for r in rules if r.rule_type in rule_type_filter]

        results: List[RuleExecutionResult] = []
        if rules:
            db_config = self._build_target_db_config(db, asset)
            engine = DqcRuleEngine(db_config=db_config)
            for rule in rules:
                rule_result = engine.execute_rule(asset, rule)
                results.append(rule_result)

        # 落库规则结果
        if results:
            self.dao.bulk_insert_rule_results(
                db,
                [
                    {
                        "cycle_id": cycle_id,
                        "asset_id": asset.id,
                        "rule_id": r.rule_id,
                        "dimension": r.dimension,
                        "rule_type": r.rule_type,
                        "passed": r.passed,
                        "actual_value": r.actual_value,
                        "expected_config": r.expected_config,
                        "error_message": r.error_message,
                        "execution_time_ms": r.execution_time_ms,
                        "executed_at": datetime.utcnow(),
                    }
                    for r in results
                ],
            )

        now = datetime.utcnow()
        prev_scores = self.drift.compute_prev_scores(db, asset.id, before=now)
        d7_avg = self.drift.compute_7d_avg(db, asset.id, now=now)

        score_result = self.scorer.score_asset(
            asset_id=asset.id,
            results=results,
            weights=asset.dimension_weights or {},
            thresholds=asset.signal_thresholds or {},
            prev_dimension_scores=prev_scores,
            d7_avg_dimension_scores=d7_avg,
        )

        dim_rows = []
        for dim in ALL_DIMENSIONS:
            dr = score_result.dimension_scores[dim]
            dim_rows.append(
                {
                    "cycle_id": cycle_id,
                    "asset_id": asset.id,
                    "dimension": dim,
                    "score": dr.score,
                    "signal": dr.signal,
                    "prev_score": dr.prev_score,
                    "drift_24h": dr.drift_24h,
                    "drift_vs_7d_avg": dr.drift_vs_7d_avg,
                    "rules_total": dr.rules_total,
                    "rules_passed": dr.rules_passed,
                    "rules_failed": dr.rules_failed,
                    "computed_at": now,
                }
            )
        self.dao.bulk_insert_dimension_scores(db, dim_rows)

        prev_snapshot = self.dao.get_latest_snapshot(db, asset.id)
        prev_signal = prev_snapshot.signal if prev_snapshot else None

        profile_json = asset.profile_json or {}
        row_count_snapshot = profile_json.get("row_count")

        snap = self.dao.insert_snapshot(
            db,
            cycle_id=cycle_id,
            asset_id=asset.id,
            confidence_score=score_result.confidence_score,
            signal=score_result.signal,
            prev_signal=prev_signal,
            dimension_scores={
                dim: score_result.dimension_scores[dim].score for dim in ALL_DIMENSIONS
            },
            dimension_signals={
                dim: score_result.dimension_scores[dim].signal for dim in ALL_DIMENSIONS
            },
            row_count_snapshot=row_count_snapshot,
            computed_at=now,
        )

        self._emit_asset_events(
            db,
            asset=asset,
            cycle_id=cycle_id,
            score_result=score_result,
            prev_signal=prev_signal,
            prev_snapshot=prev_snapshot,
            actor_id=actor_id,
        )

        return {
            "rules_executed": len(results),
            "signal": score_result.signal,
            "confidence_score": score_result.confidence_score,
        }

    def _build_target_db_config(self, db: Session, asset: DqcMonitoredAsset) -> Dict[str, Any]:
        from services.datasources.models import DataSourceDatabase

        ds_db = DataSourceDatabase()
        ds = ds_db.get(db, asset.datasource_id)
        if not ds:
            raise RuntimeError(f"datasource {asset.datasource_id} not found for asset {asset.id}")
        crypto = get_datasource_crypto()
        password = crypto.decrypt(ds.password_encrypted)
        return {
            "db_type": ds.db_type,
            "host": ds.host,
            "port": ds.port,
            "user": ds.username,
            "password": password,
            "database": ds.database_name,
            "readonly": True,
        }

    # ==================================================================
    # 事件发射（spec §12.5）
    # ==================================================================

    def _emit_asset_events(
        self,
        db: Session,
        asset: DqcMonitoredAsset,
        cycle_id: UUID,
        score_result,
        prev_signal: Optional[str],
        prev_snapshot,
        actor_id: Optional[int],
    ) -> None:
        current_signal = score_result.signal
        failing_dims = [
            dim
            for dim in ALL_DIMENSIONS
            if score_result.dimension_scores[dim].signal in (SignalLevel.P0.value, SignalLevel.P1.value)
        ]

        base_payload = {
            "asset_id": asset.id,
            "datasource_id": asset.datasource_id,
            "schema_name": asset.schema_name,
            "table_name": asset.table_name,
            "display_name": asset.display_name,
            "cycle_id": str(cycle_id),
        }

        if prev_signal is not None and prev_signal != current_signal:
            self._emit_event(
                db,
                event_type="dqc.asset.signal_changed",
                payload={
                    **base_payload,
                    "prev_signal": prev_signal,
                    "current_signal": current_signal,
                    "prev_confidence_score": prev_snapshot.confidence_score if prev_snapshot else None,
                    "current_confidence_score": score_result.confidence_score,
                },
                severity="warning" if _is_worsening(prev_signal, current_signal) else "info",
                actor_id=actor_id,
            )

        if current_signal == SignalLevel.P0.value and prev_signal != SignalLevel.P0.value:
            self._emit_event(
                db,
                event_type="dqc.asset.p0_triggered",
                payload={
                    **base_payload,
                    "signal": SignalLevel.P0.value,
                    "confidence_score": score_result.confidence_score,
                    "failing_dimensions": failing_dims,
                },
                severity="error",
                actor_id=actor_id,
            )

        if current_signal == SignalLevel.P1.value and prev_signal != SignalLevel.P1.value:
            self._emit_event(
                db,
                event_type="dqc.asset.p1_triggered",
                payload={
                    **base_payload,
                    "signal": SignalLevel.P1.value,
                    "confidence_score": score_result.confidence_score,
                    "failing_dimensions": failing_dims,
                },
                severity="warning",
                actor_id=actor_id,
            )

        if (
            prev_signal in (SignalLevel.P0.value, SignalLevel.P1.value)
            and current_signal == SignalLevel.GREEN.value
        ):
            self._emit_event(
                db,
                event_type="dqc.asset.recovered",
                payload={
                    **base_payload,
                    "prev_signal": prev_signal,
                    "current_signal": current_signal,
                },
                severity="info",
                actor_id=actor_id,
            )

    def _emit_event(
        self,
        db: Session,
        event_type: str,
        payload: Dict[str, Any],
        severity: str,
        actor_id: Optional[int],
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
        except Exception:
            logger.exception("failed to emit dqc event: %s", event_type)


def _is_worsening(prev: str, current: str) -> bool:
    from .constants import SIGNAL_PRIORITY

    return SIGNAL_PRIORITY.get(current, 0) > SIGNAL_PRIORITY.get(prev, 0)


def is_cycle_locked(scope: str = "full") -> bool:
    from services.common.redis_cache import get_redis_client
    from .constants import LOCK_KEY_FULL, LOCK_KEY_HOURLY

    client = get_redis_client()
    if client is None:
        return False
    key = LOCK_KEY_FULL if scope == "full" else LOCK_KEY_HOURLY
    try:
        return client.exists(key) > 0
    except Exception:
        return False
