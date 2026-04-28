"""
Mulan BI Platform — 统一错误码体系
规格：docs/specs/01-error-codes-standard.md

所有 4xx/5xx 响应必须通过本模块抛出，响应格式统一为：
  {"error_code": "AUTH_001", "message": "...", "detail": {...}}
"""
from fastapi import HTTPException
from typing import Optional, Any


class MulanError(HTTPException):
    """Mulan BI Platform 统一异常基类"""

    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = 500,
        detail: Optional[dict[str, Any]] = None,
    ):
        self.error_code = error_code
        self.message = message
        self.error_detail = detail
        super().__init__(
            status_code=status_code,
            detail={
                "error_code": error_code,
                "message": message,
                "detail": detail or {},
            },
        )


# ---------------------------------------------------------------------------
# SYS — 系统/全局  SYS_001~099
# ---------------------------------------------------------------------------

class SYSError:
    @staticmethod
    def internal_error(detail: dict = None):
        return MulanError("SYS_001", "服务器内部错误", 500, detail)

    @staticmethod
    def db_unavailable():
        return MulanError("SYS_002", "数据库连接失败", 503)

    @staticmethod
    def rate_limit_exceeded():
        return MulanError("SYS_003", "请求频率超限", 429)

    @staticmethod
    def bad_request(detail: dict = None):
        return MulanError("SYS_004", "请求体格式不正确", 400, detail)


# ---------------------------------------------------------------------------
# AUTH — 认证与权限  AUTH_001~099
# ---------------------------------------------------------------------------

class AuthError:
    @staticmethod
    def session_expired():
        return MulanError("AUTH_001", "会话过期或无效", 401)

    @staticmethod
    def invalid_credentials():
        return MulanError("AUTH_002", "用户名或密码错误", 401)

    @staticmethod
    def insufficient_permissions():
        return MulanError("AUTH_003", "权限不足", 403)

    @staticmethod
    def admin_required():
        return MulanError("AUTH_004", "需要管理员角色", 403)

    @staticmethod
    def username_exists():
        return MulanError("AUTH_005", "用户名已存在", 409)

    @staticmethod
    def email_exists():
        return MulanError("AUTH_006", "邮箱已存在", 409)

    @staticmethod
    def user_not_found():
        return MulanError("AUTH_007", "用户不存在", 404)

    @staticmethod
    def account_disabled():
        return MulanError("AUTH_008", "账号已禁用", 403)

    @staticmethod
    def register_rate_limited():
        return MulanError("AUTH_009", "注册请求过于频繁", 429)


# ---------------------------------------------------------------------------
# DS — 数据源管理  DS_001~099
# ---------------------------------------------------------------------------

class DSError:
    @staticmethod
    def not_found():
        return MulanError("DS_001", "数据源不存在", 404)

    @staticmethod
    def not_owner():
        return MulanError("DS_002", "非数据源所有者", 403)

    @staticmethod
    def connection_failed(detail: dict = None):
        return MulanError("DS_003", "连接测试失败", 400, detail)

    @staticmethod
    def unsupported_db_type():
        return MulanError("DS_004", "不支持的数据库类型", 400)

    @staticmethod
    def encryption_key_missing():
        return MulanError("DS_005", "加密密钥未配置", 400)

    @staticmethod
    def name_exists():
        return MulanError("DS_006", "数据源名称已存在", 409)


# ---------------------------------------------------------------------------
# DDL — DDL 合规检查  DDL_001~099
# ---------------------------------------------------------------------------

class DDLError:
    @staticmethod
    def invalid_syntax(detail: dict = None):
        return MulanError("DDL_001", "DDL 语法无效", 400, detail)

    @staticmethod
    def rule_not_found():
        return MulanError("DDL_002", "规则不存在", 404)

    @staticmethod
    def invalid_rule_config(detail: dict = None):
        return MulanError("DDL_003", "规则配置无效", 400, detail)


# ---------------------------------------------------------------------------
# TAB — Tableau MCP 集成 V1  TAB_001~099
# ---------------------------------------------------------------------------

class TABError:
    @staticmethod
    def connection_not_found():
        return MulanError("TAB_001", "连接不存在", 404)

    @staticmethod
    def access_denied():
        return MulanError("TAB_002", "无权访问此连接", 403)

    @staticmethod
    def pat_auth_failed(detail: dict = None):
        return MulanError("TAB_003", "PAT 认证失败", 400, detail)

    @staticmethod
    def server_unreachable(detail: dict = None):
        return MulanError("TAB_004", "Tableau Server 不可达", 502, detail)

    @staticmethod
    def sync_in_progress():
        return MulanError("TAB_005", "同步任务进行中", 409)

    @staticmethod
    def asset_not_found():
        return MulanError("TAB_006", "资产不存在", 404)

    @staticmethod
    def sync_failed(detail: dict = None):
        return MulanError("TAB_007", "同步失败", 502, detail)

    @staticmethod
    def invalid_connection_type():
        return MulanError("TAB_008", "连接类型无效", 400)

    @staticmethod
    def mcp_query_failed(detail: dict = None):
        return MulanError("TAB_009", "MCP 查询失败", 502, detail)

    @staticmethod
    def sync_log_not_found():
        return MulanError("TAB_010", "同步日志不存在", 404)


# ---------------------------------------------------------------------------
# MCP — Tableau MCP V2 直连  MCP_001~099
# ---------------------------------------------------------------------------

class MCPError:
    @staticmethod
    def invalid_vizql_query(detail: dict = None):
        return MulanError("MCP_001", "VizQL 查询 JSON 格式错误", 400, detail)

    @staticmethod
    def field_not_found(detail: dict = None):
        return MulanError("MCP_002", "查询引用了不存在的字段", 400, detail)

    @staticmethod
    def service_unavailable():
        return MulanError("MCP_003", "MCP 服务不可用", 503)

    @staticmethod
    def query_timeout():
        return MulanError("MCP_004", "MCP 查询超时（30s）", 504)

    @staticmethod
    def auth_failed():
        return MulanError("MCP_005", "MCP 认证失败（PAT 过期）", 401)

    @staticmethod
    def invalid_datasource_luid():
        return MulanError("MCP_006", "数据源 LUID 无效", 400)

    @staticmethod
    def limit_out_of_range():
        return MulanError("MCP_007", "查询 limit 超出允许范围", 400)

    @staticmethod
    def rate_limited():
        return MulanError("MCP_008", "MCP 请求频率超限", 429)

    @staticmethod
    def response_parse_failed(detail: dict = None):
        return MulanError("MCP_009", "MCP 响应解析失败", 500, detail)

    @staticmethod
    def not_datasource_type():
        return MulanError("MCP_010", "目标资产不是 datasource 类型", 400)

    @staticmethod
    def v2_not_enabled():
        """连接未开启 V2 直连模式（mcp_direct_enabled=false）"""
        return MulanError("MCP_010", "目标资产不是 datasource 类型或连接未开启直连模式，请使用 V1 API", 422)


# ---------------------------------------------------------------------------
# REQ — 需求管理  REQ_001~099
# ---------------------------------------------------------------------------

class REQError:
    @staticmethod
    def not_found():
        return MulanError("REQ_001", "需求不存在", 404)

    @staticmethod
    def unauthorized():
        return MulanError("AUTH_003", "无权操作此需求", 403)


# ---------------------------------------------------------------------------
# SM — 语义维护  SM_001~099
# ---------------------------------------------------------------------------

class SMError:
    @staticmethod
    def datasource_semantics_not_found():
        return MulanError("SM_001", "数据源语义不存在", 404)

    @staticmethod
    def field_semantics_not_found():
        return MulanError("SM_002", "字段语义不存在", 404)

    @staticmethod
    def invalid_status_transition(detail: dict = None):
        return MulanError("SM_003", "状态流转无效", 409, detail)

    @staticmethod
    def reviewer_required():
        return MulanError("SM_004", "仅审核者/管理员可审批", 403)

    @staticmethod
    def admin_required_for_rollback():
        return MulanError("SM_005", "仅管理员可回滚", 403)

    @staticmethod
    def ai_generation_failed(detail: dict = None):
        return MulanError("SM_006", "AI 生成失败", 502, detail)

    @staticmethod
    def already_published():
        return MulanError("SM_007", "已发布", 409)

    @staticmethod
    def confidential_field_blocked():
        return MulanError("SM_008", "机密字段不可发布", 422)

    @staticmethod
    def version_not_found():
        return MulanError("SM_009", "版本不存在", 404)


# ---------------------------------------------------------------------------
# LLM — LLM 能力层  LLM_001~099
# ---------------------------------------------------------------------------

class LLMError:
    @staticmethod
    def no_config():
        return MulanError("LLM_001", "无可用 LLM 配置", 404)

    @staticmethod
    def invalid_api_key():
        return MulanError("LLM_002", "API Key 无效", 400)

    @staticmethod
    def provider_timeout():
        return MulanError("LLM_003", "LLM 供应商超时", 502)

    @staticmethod
    def provider_unavailable():
        return MulanError("LLM_004", "LLM 供应商不可用", 502)

    @staticmethod
    def response_parse_failed():
        return MulanError("LLM_005", "LLM 响应解析失败", 502)


# ---------------------------------------------------------------------------
# HS — 健康扫描  HS_001~099
# ---------------------------------------------------------------------------

class HSError:
    @staticmethod
    def scan_not_found():
        return MulanError("HS_001", "扫描记录不存在", 404)

    @staticmethod
    def scan_in_progress():
        return MulanError("HS_002", "扫描任务进行中", 409)

    @staticmethod
    def datasource_connection_failed(detail: dict = None):
        return MulanError("HS_003", "数据源连接失败", 400, detail)

    @staticmethod
    def db_query_timeout():
        return MulanError("HS_004", "数据库查询超时", 502)


# ---------------------------------------------------------------------------
# SEARCH — 自然语言查询  SEARCH_001~099
# ---------------------------------------------------------------------------

class SEARCHError:
    @staticmethod
    def no_llm_config():
        return MulanError("SEARCH_001", "无 LLM 配置", 404)

    @staticmethod
    def no_semantic_data():
        return MulanError("SEARCH_002", "无可用语义数据", 404)

    @staticmethod
    def no_matching_fields():
        return MulanError("SEARCH_003", "未匹配到相关字段", 404)

    @staticmethod
    def query_failed(detail: dict = None):
        return MulanError("SEARCH_004", "查询执行失败", 502, detail)

    @staticmethod
    def ambiguous_datasource():
        return MulanError("SEARCH_005", "歧义：匹配到多个数据源", 409)


# ---------------------------------------------------------------------------
# GOV — 数据治理质量  GOV_001~099
# ---------------------------------------------------------------------------

class GOVError:
    @staticmethod
    def rule_not_found():
        return MulanError("GOV_001", "质量规则不存在", 404)

    @staticmethod
    def result_not_found():
        return MulanError("GOV_002", "质量检测结果不存在", 404)

    @staticmethod
    def scan_in_progress():
        return MulanError("GOV_003", "质量扫描任务进行中", 409)

    @staticmethod
    def datasource_connection_failed(detail: dict = None):
        return MulanError("GOV_004", "数据源连接失败", 400, detail)


# ---------------------------------------------------------------------------
# DQC — Data Quality Core 流水线  DQC_001~099
# ---------------------------------------------------------------------------

class DQCError:
    @staticmethod
    def asset_not_found():
        return MulanError("DQC_001", "监控资产不存在", 404)

    @staticmethod
    def asset_already_exists(detail: dict = None):
        return MulanError("DQC_002", "监控资产已存在", 409, detail)

    @staticmethod
    def datasource_not_found_or_inactive(detail: dict = None):
        return MulanError("DQC_003", "数据源不存在或未激活", 400, detail)

    @staticmethod
    def not_asset_owner():
        return MulanError("DQC_004", "非资产所有者", 403)

    @staticmethod
    def invalid_dimension_weights(detail: dict = None):
        return MulanError("DQC_010", "维度权重非法", 400, detail)

    @staticmethod
    def invalid_signal_thresholds(detail: dict = None):
        return MulanError("DQC_011", "信号阈值非法", 400, detail)

    @staticmethod
    def unsupported_rule_type(detail: dict = None):
        return MulanError("DQC_020", "规则类型不支持", 400, detail)

    @staticmethod
    def invalid_rule_config(detail: dict = None):
        return MulanError("DQC_021", "规则配置参数无效", 400, detail)

    @staticmethod
    def dimension_rule_incompatible(detail: dict = None):
        return MulanError("DQC_022", "维度与规则类型不兼容", 400, detail)

    @staticmethod
    def rule_already_exists(detail: dict = None):
        return MulanError("DQC_023", "规则已存在", 409, detail)

    @staticmethod
    def rule_not_found():
        return MulanError("DQC_024", "规则不存在", 404)

    @staticmethod
    def custom_sql_not_readonly(detail: dict = None):
        return MulanError("DQC_025", "custom_sql 非只读", 400, detail)

    @staticmethod
    def cycle_in_progress():
        return MulanError("DQC_030", "DQC cycle 正在运行", 409)

    @staticmethod
    def cycle_not_found():
        return MulanError("DQC_031", "cycle 不存在", 404)

    @staticmethod
    def target_connection_failed(detail: dict = None):
        return MulanError("DQC_040", "目标数据库连接失败", 502, detail)

    @staticmethod
    def target_query_timeout(detail: dict = None):
        return MulanError("DQC_041", "目标数据库查询超时", 504, detail)

    @staticmethod
    def scan_rows_exceeded(detail: dict = None):
        return MulanError("DQC_042", "扫描行数超限", 422, detail)

    @staticmethod
    def llm_call_failed(detail: dict = None):
        return MulanError("DQC_050", "LLM 调用失败", 502, detail)

    @staticmethod
    def llm_response_parse_failed(detail: dict = None):
        return MulanError("DQC_051", "LLM 响应解析失败", 502, detail)


# ---------------------------------------------------------------------------
# TR — Task Runtime  TR_001~TR_010  (Spec 24)
# ---------------------------------------------------------------------------

class TRError:
    @staticmethod
    def invalid_intent():
        """TR_001: intent 不在白名单"""
        return MulanError("TR_001", "intent 不在白名单中", 400)

    @staticmethod
    def timeout_out_of_range():
        """TR_002: timeout 超出范围 [5, 600]"""
        return MulanError("TR_002", "timeout_seconds 超出允许范围 [5, 600]", 400)

    @staticmethod
    def conversation_not_owned():
        """TR_003: conversation_id 不属于当前用户"""
        return MulanError("TR_003", "conversation_id 不属于当前用户", 403)

    @staticmethod
    def task_run_not_found():
        """TR_004: TaskRun 不存在或无权访问"""
        return MulanError("TR_004", "TaskRun 不存在或无权访问", 404)

    @staticmethod
    def invalid_state_transition():
        """TR_005: 当前状态不允许该操作"""
        return MulanError("TR_005", "当前状态不允许该操作", 409)

    @staticmethod
    def task_timeout():
        """TR_006: TaskRun 总超时"""
        return MulanError("TR_006", "TaskRun 总超时", 504)

    @staticmethod
    def illegal_state_transition(detail: dict = None):
        """TR_007: 非法状态转移（内部 bug）"""
        return MulanError("TR_007", "非法状态转移", 500, detail)

    @staticmethod
    def concurrent_limit_exceeded():
        """TR_008: 并发上限，用户 5 个 running TaskRun"""
        return MulanError("TR_008", "并发运行任务数超限（最多 5 个）", 429)

    @staticmethod
    def capability_invocation_failed(detail: dict = None):
        """TR_009: 下游 capability 调用失败"""
        return MulanError("TR_009", "下游 capability 调用失败", 502, detail)

    @staticmethod
    def state_write_conflict():
        """TR_010: 状态写入冲突，OCC 重试耗尽"""
        return MulanError("TR_010", "状态写入冲突，请重试", 500)
