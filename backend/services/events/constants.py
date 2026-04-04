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
    HEALTH_SCAN_COMPLETED,
    HEALTH_SCAN_FAILED,
    HEALTH_SCORE_DROPPED,
    AUTH_USER_LOGIN,
    AUTH_USER_CREATED,
    AUTH_USER_ROLE_CHANGED,
    SYSTEM_MAINTENANCE,
    SYSTEM_ERROR,
]

# 来源模块枚举
SOURCE_MODULE_TABLEAU = "tableau"
SOURCE_MODULE_SEMANTIC = "semantic"
SOURCE_MODULE_HEALTH = "health"
SOURCE_MODULE_AUTH = "auth"
SOURCE_MODULE_SYSTEM = "system"

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
