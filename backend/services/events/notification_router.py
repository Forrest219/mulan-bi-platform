"""通知路由注册表"""

from typing import Callable, List
from sqlalchemy.orm import Session

from .constants import (
    TABLEAU_SYNC_COMPLETED, TABLEAU_SYNC_FAILED,
    SEMANTIC_SUBMITTED, SEMANTIC_APPROVED, SEMANTIC_REJECTED,
    SEMANTIC_PUBLISHED, SEMANTIC_PUBLISH_FAILED,
    HEALTH_SCAN_COMPLETED, HEALTH_SCAN_FAILED, HEALTH_SCORE_DROPPED,
    AUTH_USER_ROLE_CHANGED, SYSTEM_MAINTENANCE, SYSTEM_ERROR,
    METRIC_PUBLISHED, METRIC_ANOMALY_DETECTED, METRIC_CONSISTENCY_FAILED,
    DQC_CYCLE_STARTED, DQC_CYCLE_COMPLETED,
    DQC_ASSET_SIGNAL_CHANGED, DQC_ASSET_P0_TRIGGERED,
    DQC_ASSET_P1_TRIGGERED, DQC_ASSET_RECOVERED,
)


# 路由注册表：event_type -> 返回目标用户 ID 列表的函数
NOTIFICATION_ROUTES: dict[str, Callable] = {}


def register_route(event_type: str):
    """装饰器：注册事件类型对应的通知路由函数"""
    def decorator(fn: Callable):
        NOTIFICATION_ROUTES[event_type] = fn
        return fn
    return decorator


def resolve_targets(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """
    根据事件类型解析通知目标用户列表。
    如果未注册路由，返回空列表。
    """
    router = NOTIFICATION_ROUTES.get(event_type)
    if router:
        return router(db, event_type, payload, actor_id)
    return []


def _get_users_by_role(db: Session, role: str) -> List[int]:
    """获取指定角色的所有用户ID"""
    from services.auth.models import User
    users = db.query(User).filter(User.role == role).all()
    return [u.id for u in users]


def _get_all_active_user_ids(db: Session) -> List[int]:
    """获取所有活跃用户ID"""
    from services.auth.models import User
    users = db.query(User).filter(User.is_active == True).all()
    return [u.id for u in users]


# === Tableau 模块路由 ===

@register_route(TABLEAU_SYNC_COMPLETED)
def route_tableau_sync_completed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """同步成功：通知连接所有者"""
    from services.tableau.models import TableauConnection
    connection_id = payload.get("connection_id")
    if not connection_id:
        return []
    conn = db.query(TableauConnection).filter(TableauConnection.id == connection_id).first()
    if not conn or not conn.owner_id:
        return []
    return [conn.owner_id]


@register_route(TABLEAU_SYNC_FAILED)
def route_tableau_sync_failed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """同步失败：通知连接所有者 + 所有 admin"""
    from services.tableau.models import TableauConnection
    connection_id = payload.get("connection_id")
    owner_ids = []
    if connection_id:
        conn = db.query(TableauConnection).filter(TableauConnection.id == connection_id).first()
        if conn and conn.owner_id:
            owner_ids.append(conn.owner_id)
    admin_ids = _get_users_by_role(db, "admin")
    return list(set(owner_ids + admin_ids))


# === Semantic 模块路由 ===

@register_route(SEMANTIC_SUBMITTED)
def route_semantic_submitted(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """提交审核：通知所有 admin + data_admin"""
    admin_ids = _get_users_by_role(db, "admin")
    data_admin_ids = _get_users_by_role(db, "data_admin")
    return list(set(admin_ids + data_admin_ids))


@register_route(SEMANTIC_APPROVED)
def route_semantic_approved(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """审核通过：通知语义创建者"""
    creator_id = payload.get("creator_id") or payload.get("actor_id")
    if creator_id:
        return [int(creator_id)]
    return []


@register_route(SEMANTIC_REJECTED)
def route_semantic_rejected(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """审核驳回：通知语义创建者"""
    creator_id = payload.get("creator_id") or payload.get("actor_id")
    if creator_id:
        return [int(creator_id)]
    return []


@register_route(SEMANTIC_PUBLISHED)
def route_semantic_published(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """发布成功：通知创建者 + 所有 admin"""
    creator_id = payload.get("creator_id")
    admin_ids = _get_users_by_role(db, "admin")
    target_ids = list(set(admin_ids))
    if creator_id:
        target_ids.append(int(creator_id))
    return list(set(target_ids))


@register_route(SEMANTIC_PUBLISH_FAILED)
def route_semantic_publish_failed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """发布失败：通知创建者 + 所有 admin"""
    creator_id = payload.get("creator_id")
    admin_ids = _get_users_by_role(db, "admin")
    target_ids = list(set(admin_ids))
    if creator_id:
        target_ids.append(int(creator_id))
    return list(set(target_ids))


# === Health 模块路由 ===

@register_route(HEALTH_SCAN_COMPLETED)
def route_health_scan_completed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """扫描完成：通知扫描触发者"""
    triggered_by = payload.get("triggered_by") or actor_id
    if triggered_by:
        return [int(triggered_by)]
    return []


@register_route(HEALTH_SCAN_FAILED)
def route_health_scan_failed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """扫描失败：通知扫描触发者 + 所有 admin"""
    triggered_by = payload.get("triggered_by") or actor_id
    admin_ids = _get_users_by_role(db, "admin")
    target_ids = list(set(admin_ids))
    if triggered_by:
        target_ids.append(int(triggered_by))
    return list(set(target_ids))


@register_route(HEALTH_SCORE_DROPPED)
def route_health_score_dropped(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """分数下降：通知扫描触发者 + 所有 admin"""
    triggered_by = payload.get("triggered_by") or actor_id
    admin_ids = _get_users_by_role(db, "admin")
    target_ids = list(set(admin_ids))
    if triggered_by:
        target_ids.append(int(triggered_by))
    return list(set(target_ids))


# === Auth 模块路由 ===

@register_route(AUTH_USER_ROLE_CHANGED)
def route_auth_user_role_changed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """角色变更：通知目标用户"""
    target_user_id = payload.get("target_user_id")
    if target_user_id:
        return [int(target_user_id)]
    return []


# === System 模块路由 ===

@register_route(SYSTEM_MAINTENANCE)
def route_system_maintenance(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """系统维护：广播所有活跃用户"""
    return _get_all_active_user_ids(db)


@register_route(SYSTEM_ERROR)
def route_system_error(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """系统错误：通知所有 admin"""
    return _get_users_by_role(db, "admin")


# === Metrics Agent 模块路由 ===

@register_route(METRIC_PUBLISHED)
def route_metric_published(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """指标发布：通知所有 data_admin + admin"""
    admin_ids = _get_users_by_role(db, "admin")
    data_admin_ids = _get_users_by_role(db, "data_admin")
    return list(set(admin_ids + data_admin_ids))


@register_route(METRIC_ANOMALY_DETECTED)
def route_metric_anomaly_detected(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """指标异常：通知所有 data_admin + admin"""
    admin_ids = _get_users_by_role(db, "admin")
    data_admin_ids = _get_users_by_role(db, "data_admin")
    return list(set(admin_ids + data_admin_ids))


@register_route(METRIC_CONSISTENCY_FAILED)
def route_metric_consistency_failed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """一致性校验失败：通知所有 data_admin + admin"""
    admin_ids = _get_users_by_role(db, "admin")
    data_admin_ids = _get_users_by_role(db, "data_admin")
    return list(set(admin_ids + data_admin_ids))


# === DQC 模块路由 ===


def _get_dqc_asset_owner_id(db: Session, asset_id) -> int:
    """获取 DQC 资产 owner_id"""
    if asset_id is None:
        return None
    from services.dqc.models import DqcMonitoredAsset
    asset = db.query(DqcMonitoredAsset).filter(DqcMonitoredAsset.id == int(asset_id)).first()
    return asset.owner_id if asset else None


@register_route(DQC_CYCLE_STARTED)
def route_dqc_cycle_started(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """cycle 开始：不建通知，仅落事件审计"""
    return []


@register_route(DQC_CYCLE_COMPLETED)
def route_dqc_cycle_completed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """cycle 完成：manual 通知触发者；scheduled 仅在出现 P0/P1 时通知 admin"""
    trigger = payload.get("trigger_type")
    if trigger == "manual" and actor_id:
        return [int(actor_id)]
    if (payload.get("p0_count") or 0) > 0 or (payload.get("p1_count") or 0) > 0:
        return _get_users_by_role(db, "admin")
    return []


@register_route(DQC_ASSET_SIGNAL_CHANGED)
def route_dqc_asset_signal_changed(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """信号变化：通知资产 owner"""
    owner = _get_dqc_asset_owner_id(db, payload.get("asset_id"))
    return [owner] if owner else []


@register_route(DQC_ASSET_P0_TRIGGERED)
def route_dqc_asset_p0_triggered(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """P0 触发：通知资产 owner + 所有 admin"""
    owner = _get_dqc_asset_owner_id(db, payload.get("asset_id"))
    admin_ids = _get_users_by_role(db, "admin")
    targets = set(admin_ids)
    if owner:
        targets.add(owner)
    return list(targets)


@register_route(DQC_ASSET_P1_TRIGGERED)
def route_dqc_asset_p1_triggered(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """P1 触发：通知资产 owner"""
    owner = _get_dqc_asset_owner_id(db, payload.get("asset_id"))
    return [owner] if owner else []


@register_route(DQC_ASSET_RECOVERED)
def route_dqc_asset_recovered(db: Session, event_type: str, payload: dict, actor_id: int = None) -> List[int]:
    """资产恢复：通知资产 owner"""
    owner = _get_dqc_asset_owner_id(db, payload.get("asset_id"))
    return [owner] if owner else []
