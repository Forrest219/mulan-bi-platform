"""
SQL Agent HTTP Client — 服务间 HTTP 调用

Spec 28 §2.3 — Data Agent → SQL Agent 调用规范
- POST /api/agents/sql/query
- 携带 X-Forward-User-JWT（用户发起）或 X-Scan-Service-JWT（调度扫描）
- 两种 header 互斥，不得同时出现

服务间认证：mTLS 客户端证书或 HMAC 签名 Token
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SQLAgentError(Exception):
    """SQL Agent 调用异常"""

    def __init__(self, code: str, message: str, detail: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"[{code}] {message}")


class SQLAgentClient:
    """
    SQL Agent HTTP API 客户端

    Args:
        base_url: SQL Agent 服务地址（默认从配置读取）
        timeout: 请求超时时间（秒）
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        settings = get_settings()
        self.base_url = base_url or getattr(settings, "SQL_AGENT_URL", "http://localhost:8001")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            headers={"Content-Type": "application/json"},
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    def _build_headers(
        self,
        user_jwt: Optional[str] = None,
        scan_service_jwt: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        构建请求头

        Args:
            user_jwt: X-Forward-User-JWT（用户发起）
            scan_service_jwt: X-Scan-Service-JWT（调度扫描）

        Returns:
            请求头字典

        Raises:
            ValueError: 同时提供两种 JWT 或均未提供
        """
        if user_jwt and scan_service_jwt:
            raise ValueError("X-Forward-User-JWT 和 X-Scan-Service-JWT 不可同时出现")

        if not user_jwt and not scan_service_jwt:
            raise ValueError("必须提供 X-Forward-User-JWT 或 X-Scan-Service-JWT 之一")

        headers: Dict[str, str] = {}
        if user_jwt:
            headers["X-Forward-User-JWT"] = user_jwt
        else:
            headers["X-Scan-Service-JWT"] = scan_service_jwt

        return headers

    async def query(
        self,
        natural_language_intent: str,
        actor: Dict[str, Any],
        schema_context: Dict[str, Any],
        session_id: str,
        max_rows: int = 10000,
        query_timeout_seconds: int = 30,
        user_jwt: Optional[str] = None,
        scan_service_jwt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        调用 SQL Agent 执行查询

        Args:
            natural_language_intent: 自然语言查询意图
            actor: 参与者信息（user_id, roles, allowed_datasources, allowed_metrics, allowed_dimensions）
            schema_context: Schema 上下文（available_tables, metric_definitions）
            session_id: 分析会话 ID
            max_rows: 最大返回行数
            query_timeout_seconds: 查询超时时间
            user_jwt: X-Forward-User-JWT（用户发起）
            scan_service_jwt: X-Scan-Service-JWT（调度扫描）

        Returns:
            SQL Agent 响应：
            {
                "sql": "SELECT ...",
                "result_summary": "一句话结果描述",
                "result_metadata": {
                    "schema": [{"name": "region", "type": "varchar"}, ...],
                    "row_count": 12,
                    "sample_rows": [...],
                    "filters_applied": [...],
                    "raw_data_ref": "query_20260420_001"
                },
                "execution_time_ms": 1250
            }

        Raises:
            SQLAgentError: 调用失败时
        """
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={"Content-Type": "application/json"},
            )

        headers = self._build_headers(user_jwt, scan_service_jwt)

        payload = {
            "natural_language_intent": natural_language_intent,
            "actor": actor,
            "schema_context": schema_context,
            "session_id": session_id,
            "max_rows": max_rows,
            "query_timeout_seconds": query_timeout_seconds,
        }

        start_time = time.time()
        logger.info(
            "SQL Agent query: intent=%s, session_id=%s, trace=%s",
            natural_language_intent[:100],
            session_id,
            headers.get("X-Trace-ID", ""),
        )

        try:
            response = await self._client.post(
                "/api/agents/sql/query",
                json=payload,
                headers=headers,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 401:
                raise SQLAgentError(
                    code="DAT_007",
                    message="SQL Agent 认证失败：服务令牌无效或已过期",
                    detail={"status_code": 401},
                )

            if response.status_code == 403:
                raise SQLAgentError(
                    code="DAT_007",
                    message="SQL Agent 授权失败：权限不足",
                    detail={"status_code": 403},
                )

            if response.status_code >= 500:
                raise SQLAgentError(
                    code="DAT_007",
                    message="SQL Agent 服务暂时不可用",
                    detail={"status_code": response.status_code},
                )

            if response.status_code != 200:
                try:
                    error_data = response.json()
                    raise SQLAgentError(
                        code=error_data.get("error_code", "DAT_007"),
                        message=error_data.get("message", "SQL Agent 调用失败"),
                        detail=error_data.get("detail"),
                    )
                except Exception:
                    raise SQLAgentError(
                        code="DAT_007",
                        message=f"SQL Agent 调用失败：HTTP {response.status_code}",
                        detail={"status_code": response.status_code},
                    )

            result = response.json()

            # 验证响应格式
            if "result_summary" not in result:
                raise SQLAgentError(
                    code="DAT_007",
                    message="SQL Agent 响应缺少 result_summary 字段",
                    detail={"response_keys": list(result.keys())},
                )

            if "result_metadata" not in result:
                raise SQLAgentError(
                    code="DAT_007",
                    message="SQL Agent 响应缺少 result_metadata 字段",
                    detail={"response_keys": list(result.keys())},
                )

            logger.info(
                "SQL Agent success: session_id=%s, execution_time_ms=%d, row_count=%d",
                session_id,
                execution_time_ms,
                result.get("result_metadata", {}).get("row_count", 0),
            )

            return result

        except httpx.TimeoutException:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.warning(
                "SQL Agent timeout: intent=%s, session_id=%s, timeout=%ds",
                natural_language_intent[:100],
                session_id,
                self.timeout,
            )
            raise SQLAgentError(
                code="DAT_004",
                message=f"SQL Agent 查询超时（{self.timeout}秒）",
                detail={
                    "timeout_seconds": self.timeout,
                    "execution_time_ms": execution_time_ms,
                },
            )

        except httpx.RequestError as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "SQL Agent request error: intent=%s, session_id=%s, error=%s",
                natural_language_intent[:100],
                session_id,
                str(e),
            )
            raise SQLAgentError(
                code="DAT_007",
                message=f"SQL Agent 请求失败：{str(e)}",
                detail={
                    "execution_time_ms": execution_time_ms,
                    "error_type": type(e).__name__,
                },
            )


def sanitize_result_summary(result_summary: str, sensitive_fields: List[str]) -> str:
    """
    对 result_summary 进行敏感字段脱敏

    Args:
        result_summary: 原始结果摘要
        sensitive_fields: 敏感字段列表

    Returns:
        脱敏后的结果摘要
    """
    sanitized = result_summary
    for field in sensitive_fields:
        # 替换可能的敏感字段引用
        import re

        # 匹配字段名后跟冒号和值的情况
        pattern = rf"({field}\s*[:：]\s*)[^\s,，；]+"
        sanitized = re.sub(pattern, r"\1***", sanitized)

        # 匹配字段名在引号中的情况
        pattern = rf"(['\"]{field}['\"]\s*[:：]\s*)['\"][^'\"]+['\"]"
        sanitized = re.sub(pattern, r"\1***", sanitized)

    return sanitized


def sanitize_result_metadata(
    metadata: Dict[str, Any], sensitive_fields: List[str]
) -> Dict[str, Any]:
    """
    对 result_metadata 进行敏感字段脱敏

    Args:
        metadata: 原始元数据
        sensitive_fields: 敏感字段列表

    Returns:
        脱敏后的元数据
    """
    import copy

    sanitized = copy.deepcopy(metadata)

    # 脱敏 schema 中的敏感字段
    if "schema" in sanitized:
        for field_def in sanitized["schema"]:
            if field_def.get("name") in sensitive_fields:
                field_def["name"] = "***_脱敏字段"

    # 不返回 sample_rows 原始数据，仅保留聚合信息
    if "sample_rows" in sanitized:
        row_count = sanitized.get("row_count", 0)
        # 只保留行数，不保留具体数据
        sanitized["sample_rows"] = [{"_info": f"共 {row_count} 行数据（原始数据已脱敏）"}]

    return sanitized