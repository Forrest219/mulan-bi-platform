"""事件类型枚举常量"""

# === Tableau 模块事件 ===
TABLEAU_SYNC_COMPLETED = "tableau.sync.completed"
TABLEAU_SYNC_FAILED = "tableau.sync.failed"
TABLEAU_CONNECTION_TESTED = "tableau.connection.tested"

# === Semantic 模块事件 ===
SEMANTIC_SUBMITTED = "semantic.submitted"
SEMANTIC_APPROVED = "semantic.approved"
SEMANTIC_REJECTED = "semantic.rejected"
SEMANTIC_PUBLISHED = "semantic.published"
SEMANTIC_PUBLISH_FAILED = "semantic.publish_failed"
SEMANTIC_ROLLBACK = "semantic.rollback"
SEMANTIC_AI_GENERATED = "semantic.ai_generated"

# === Semantic Table 语义状态流转事件（Spec 9 → Spec 16） ===
SEMANTIC_TABLE_CREATED = "semantic_table.created"
SEMANTIC_TABLE_SUBMITTED = "semantic_table.submitted"     # under_review 入口
SEMANTIC_TABLE_PUBLISHED = "semantic_table.published"     # published 入口
SEMANTIC_TABLE_DEPRECATED = "semantic_table.deprecated"   # deprecated 入口
FIELD_SYNC_COMPLETED = "field_sync.completed"

# === Health 模块事件 ===
HEALTH_SCAN_COMPLETED = "health.scan.completed"
HEALTH_SCAN_FAILED = "health.scan.failed"
HEALTH_SCORE_DROPPED = "health.score.dropped"

# === Auth 模块事件 ===
AUTH_USER_LOGIN = "auth.user.login"
AUTH_USER_CREATED = "auth.user.created"
AUTH_USER_ROLE_CHANGED = "auth.user.role_changed"

# === System 模块事件 ===
SYSTEM_MAINTENANCE = "system.maintenance"
SYSTEM_ERROR = "system.error"

# === Metrics Agent 模块事件 ===
METRIC_PUBLISHED = "metric.published"
METRIC_ANOMALY_DETECTED = "metric.anomaly.detected"
METRIC_CONSISTENCY_FAILED = "metric.consistency.failed"

# === 异常检测告警事件（Spec 30） ===
ANOMALY_DETECTED = "anomaly.detected"

# === DQC 模块事件 ===
DQC_CYCLE_STARTED = "dqc.cycle.started"
DQC_CYCLE_COMPLETED = "dqc.cycle.completed"
DQC_ASSET_SIGNAL_CHANGED = "dqc.asset.signal_changed"
DQC_ASSET_P0_TRIGGERED = "dqc.asset.p0_triggered"
DQC_ASSET_P1_TRIGGERED = "dqc.asset.p1_triggered"
DQC_ASSET_RECOVERED = "dqc.asset.recovered"

# === MCP→Tableau 反向同步事件 (Spec 32 v1.1) ===
MCP_SERVER_CHANGED = "mcp.server.changed"
MCP_SERVER_DELETED = "mcp.server.deleted"

# === 反向同步结果事件 ===
TABLEAU_CONNECTION_SYNCED_FROM_MCP = "tableau.connection.synced_from_mcp"
TABLEAU_CONNECTION_SYNC_SKIPPED = "tableau.connection.sync_skipped"
TABLEAU_CONNECTION_DEACTIVATED_BY_MCP_DELETE = "tableau.connection.deactivated_by_mcp_delete"
TABLEAU_CONNECTION_RENAMED = "tableau.connection.renamed"

# === 所有事件类型列表 ===
ALL_EVENT_TYPES = [
    TABLEAU_SYNC_COMPLETED,
    TABLEAU_SYNC_FAILED,
    TABLEAU_CONNECTION_TESTED,
    SEMANTIC_SUBMITTED,
    SEMANTIC_APPROVED,
    SEMANTIC_REJECTED,
    SEMANTIC_PUBLISHED,
    SEMANTIC_PUBLISH_FAILED,
    SEMANTIC_ROLLBACK,
    SEMANTIC_AI_GENERATED,
    SEMANTIC_TABLE_CREATED,
    SEMANTIC_TABLE_SUBMITTED,
    SEMANTIC_TABLE_PUBLISHED,
    SEMANTIC_TABLE_DEPRECATED,
    FIELD_SYNC_COMPLETED,
    HEALTH_SCAN_COMPLETED,
    HEALTH_SCAN_FAILED,
    HEALTH_SCORE_DROPPED,
    AUTH_USER_LOGIN,
    AUTH_USER_CREATED,
    AUTH_USER_ROLE_CHANGED,
    SYSTEM_MAINTENANCE,
    SYSTEM_ERROR,
    METRIC_PUBLISHED,
    METRIC_ANOMALY_DETECTED,
    METRIC_CONSISTENCY_FAILED,
    ANOMALY_DETECTED,
    DQC_CYCLE_STARTED,
    DQC_CYCLE_COMPLETED,
    DQC_ASSET_SIGNAL_CHANGED,
    DQC_ASSET_P0_TRIGGERED,
    DQC_ASSET_P1_TRIGGERED,
    DQC_ASSET_RECOVERED,
    # MCP→Tableau 反向同步事件 (Spec 32 v1.1)
    MCP_SERVER_CHANGED,
    MCP_SERVER_DELETED,
    TABLEAU_CONNECTION_SYNCED_FROM_MCP,
    TABLEAU_CONNECTION_SYNC_SKIPPED,
    TABLEAU_CONNECTION_DEACTIVATED_BY_MCP_DELETE,
    TABLEAU_CONNECTION_RENAMED,
]

# 来源模块枚举
SOURCE_MODULE_TABLEAU = "tableau"
SOURCE_MODULE_SEMANTIC = "semantic"
SOURCE_MODULE_HEALTH = "health"
SOURCE_MODULE_AUTH = "auth"
SOURCE_MODULE_SYSTEM = "system"
SOURCE_MODULE_METRICS = "metrics"
SOURCE_MODULE_DQC = "dqc"
SOURCE_MODULE_MCP = "mcp"  # Spec 32 v1.1

# 严重级别枚举
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"


# === 错误码（PRD §7）===
class EvtErrorCode:
    NOTIFICATION_NOT_FOUND = "EVT_001"   # 404 通知不存在
    NOT_OWNER = "EVT_002"               # 403 非通知所有者
    INVALID_EVENT_TYPE = "EVT_003"       # 400 无效的事件类型
    PAYLOAD_VALIDATION_FAILED = "EVT_004" # 400 事件载荷校验失败
    NOTIFICATION_CREATE_FAILED = "EVT_005" # 500 通知创建失败
    ADMIN_REQUIRED = "EVT_006"           # 403 需要管理员角色


EVT_ERROR_MESSAGES = {
    EvtErrorCode.NOTIFICATION_NOT_FOUND: "通知不存在",
    EvtErrorCode.NOT_OWNER: "无权操作此通知",
    EvtErrorCode.INVALID_EVENT_TYPE: "无效的事件类型",
    EvtErrorCode.PAYLOAD_VALIDATION_FAILED: "事件载荷校验失败",
    EvtErrorCode.NOTIFICATION_CREATE_FAILED: "通知创建失败",
    EvtErrorCode.ADMIN_REQUIRED: "需要管理员角色",
}


# === MCP→Tableau 桥接错误码（BRG 前缀，Spec 32 v1.1）===
class BrgErrorCode:
    """MCP→Tableau 桥接错误码"""
    REVERSE_SYNC_NOT_FOUND = "BRG_004"   # 反向同步找不到对应连接（不报错，事件标记）
    REVERSE_SYNC_FERNET_FAILED = "BRG_005"  # 反向同步 Fernet 加密失败
    REVERSE_SYNC_OCC_CONFLICT = "BRG_006"   # 反向同步 OCC 冲突重试耗尽
    REVERSE_SYNC_NOT_SUBSCRIBED = "BRG_007"  # ReverseSyncHandler 未订阅启动检查失败


BRG_ERROR_MESSAGES = {
    BrgErrorCode.REVERSE_SYNC_NOT_FOUND: "反向同步找不到对应连接",
    BrgErrorCode.REVERSE_SYNC_FERNET_FAILED: "反向同步 Fernet 加密失败",
    BrgErrorCode.REVERSE_SYNC_OCC_CONFLICT: "反向同步 OCC 冲突重试耗尽",
    BrgErrorCode.REVERSE_SYNC_NOT_SUBSCRIBED: "ReverseSyncHandler 未订阅启动检查失败",
}
