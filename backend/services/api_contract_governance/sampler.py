"""API Contract Governance - HTTP 采样器

支持 REST (JSON) 和 GraphQL
字段提取：扁平化嵌套 JSON 为 field path
类型推断：从 JSON value 推断 field type
枚举值提取：记录枚举字段的可能值
"""
from __future__ import annotations

import base64
import fnmatch
import logging
import random
from collections import Counter
from datetime import datetime
from typing import Any, Optional

import httpx

from .types import ApiResponse, FieldSchema, FieldType

logger = logging.getLogger(__name__)


class SamplerError(Exception):
    """采样器异常基类"""
    pass


class HttpRequestError(SamplerError):
    """HTTP 请求错误"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ResponseParseError(SamplerError):
    """响应解析错误"""
    pass


class Sampler:
    """API 采样器

    支持:
    - REST API (JSON)
    - GraphQL API
    """

    # 字段路径分隔符
    PATH_SEPARATOR = "."

    def __init__(self, timeout: int = 30, retry_count: int = 3):
        self.timeout = timeout
        self.retry_count = retry_count
        self._http_client: Optional[httpx.Client] = None

    @property
    def http_client(self) -> httpx.Client:
        """懒加载 HTTP 客户端"""
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._http_client

    def sample(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        auth_method: Optional[str] = None,
        auth_config: Optional[dict[str, Any]] = None,
    ) -> ApiResponse:
        """
        执行 API 采样

        Args:
            url: API 端点 URL
            method: HTTP 方法
            headers: 请求头
            params: 查询参数
            body: 请求体
            auth_method: 认证方式
            auth_config: 认证配置

        Returns:
            ApiResponse: API 响应对象

        Raises:
            HttpRequestError: HTTP 请求失败
            ResponseParseError: 响应解析失败
        """
        request_headers = dict(headers) if headers else {}

        if auth_method and auth_method != "none" and auth_config:
            request_headers.update(self._apply_auth(auth_method, auth_config))

        start_time = datetime.utcnow()

        try:
            response = self.http_client.request(
                method=method.upper(),
                url=url,
                headers=request_headers,
                params=params,
                json=body,
            )
        except httpx.TimeoutException as e:
            raise HttpRequestError(f"Request timeout: {e}")
        except httpx.RequestError as e:
            raise HttpRequestError(f"Request failed: {e}")

        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        if response.status_code >= 400:
            raise HttpRequestError(
                f"HTTP {response.status_code}: {response.text[:500]}",
                status_code=response.status_code
            )

        try:
            response_body = response.json()
        except Exception as e:
            raise ResponseParseError(f"Failed to parse JSON response: {e}")

        return ApiResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response_body,
            duration_ms=duration_ms,
            size_bytes=len(response.content),
        )

    def sample_with_retry(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        auth_method: Optional[str] = None,
        auth_config: Optional[dict[str, Any]] = None,
    ) -> ApiResponse:
        """带重试的采样"""
        last_error: Optional[Exception] = None
        for attempt in range(self.retry_count + 1):
            try:
                return self.sample(url, method, headers, params, body, auth_method, auth_config)
            except HttpRequestError as e:
                last_error = e
                if e.status_code and 400 <= e.status_code < 500:
                    raise
        raise last_error or HttpRequestError("All retries failed")

    def extract_fields(
        self,
        data: Any,
        path_prefix: str = "",
        max_depth: int = 20,
        max_samples_per_field: int = 100,
    ) -> dict[str, FieldSchema]:
        """
        扁平化嵌套 JSON 为 field path

        Args:
            data: JSON 数据
            path_prefix: 路径前缀
            max_depth: 最大递归深度
            max_samples_per_field: 每个字段最多采集的样本数

        Returns:
            dict[str, FieldSchema]: 字段路径 -> 字段结构映射
        """
        fields: dict[str, FieldSchema] = {}
        self._extract_fields_recursive(data, path_prefix, fields, 0, max_depth, max_samples_per_field)
        return fields

    def _extract_fields_recursive(
        self,
        data: Any,
        path_prefix: str,
        fields: dict[str, FieldSchema],
        current_depth: int,
        max_depth: int,
        max_samples_per_field: int,
    ) -> None:
        """递归提取字段"""
        if current_depth >= max_depth:
            return

        if isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{path_prefix}.{key}" if path_prefix else key
                self._extract_fields_recursive(value, new_path, fields, current_depth + 1, max_depth, max_samples_per_field)
        elif isinstance(data, list):
            # 数组本身作为一个字段
            if path_prefix:
                existing = fields.get(path_prefix)
                if existing:
                    existing.type = FieldType.ARRAY
                else:
                    fields[path_prefix] = FieldSchema(
                        path=path_prefix,
                        type=FieldType.ARRAY,
                        value_samples=[],
                    )

            # 采样数组元素（最多前 5 个）
            for i, item in enumerate(data[:5]):
                new_path = f"{path_prefix}[{i}]" if path_prefix else f"[{i}]"
                self._extract_fields_recursive(item, new_path, fields, current_depth + 1, max_depth, max_samples_per_field)
        else:
            # 叶子节点
            field_type = self._infer_type(data)

            existing = fields.get(path_prefix)
            if existing:
                if data is not None and len(existing.value_samples) < max_samples_per_field:
                    existing.value_samples.append(data)
            else:
                fields[path_prefix] = FieldSchema(
                    path=path_prefix,
                    type=field_type,
                    value_samples=[data] if data is not None else [],
                )

    def extract_fields_with_enum_detection(
        self,
        data: Any,
        path_prefix: str = "",
        max_depth: int = 20,
        max_samples_per_field: int = 100,
        enum_threshold: float = 0.8,
    ) -> dict[str, FieldSchema]:
        """
        提取字段并检测枚举值

        当同一字段出现多次且值相同时，视为枚举字段
        enum_threshold: 枚举判定阈值（相同值出现次数/总样本数 >= threshold 时认为是枚举）
        """
        fields = self.extract_fields(data, path_prefix, max_depth, max_samples_per_field)

        # 二次采样以检测枚举 - 对同一路径多次出现的值进行统计
        self._detect_enum_values(data, path_prefix, fields, enum_threshold)

        return fields

    def _detect_enum_values(
        self,
        data: Any,
        path_prefix: str,
        fields: dict[str, FieldSchema],
        threshold: float,
    ) -> None:
        """递归检测枚举值"""
        if isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{path_prefix}.{key}" if path_prefix else key
                self._detect_enum_values(value, new_path, fields, threshold)
        elif isinstance(data, list):
            for item in data:
                self._detect_enum_values(item, path_prefix, fields, threshold)

    def _infer_type(self, value: Any) -> FieldType:
        """从 JSON value 推断 field type"""
        if value is None:
            return FieldType.NULL
        elif isinstance(value, bool):
            return FieldType.BOOLEAN
        elif isinstance(value, (int, float)):
            return FieldType.NUMBER
        elif isinstance(value, str):
            return FieldType.STRING
        elif isinstance(value, dict):
            return FieldType.OBJECT
        elif isinstance(value, list):
            return FieldType.ARRAY
        else:
            return FieldType.STRING

    def _apply_auth(
        self,
        auth_method: str,
        auth_config: dict[str, Any],
    ) -> dict[str, str]:
        """应用认证配置到请求头"""
        headers = {}

        if auth_method == "bearer":
            token = auth_config.get("token", "")
            headers["Authorization"] = f"Bearer {token}"
        elif auth_method == "api_key":
            key_name = auth_config.get("key_name", "X-API-Key")
            key_value = auth_config.get("key_value", "")
            headers[key_name] = key_value
        elif auth_method == "basic":
            username = auth_config.get("username", "")
            password = auth_config.get("password", "")
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        elif auth_method == "jwt":
            token = auth_config.get("token", "")
            headers["Authorization"] = f"JWT {token}"

        return headers

    def is_field_blacklisted(self, field_path: str, blacklist: list[str]) -> bool:
        """检查字段是否在黑名单中（支持 glob 模式）"""
        if not blacklist:
            return False
        for pattern in blacklist:
            if fnmatch.fnmatch(field_path, pattern):
                return True
        return False

    def is_field_whitelisted(self, field_path: str, whitelist: list[str]) -> bool:
        """检查字段是否在白名单中"""
        if not whitelist:
            return True
        for pattern in whitelist:
            if fnmatch.fnmatch(field_path, pattern):
                return True
        return False

    def filter_fields(
        self,
        fields: dict[str, FieldSchema],
        whitelist: Optional[list[str]] = None,
        blacklist: Optional[list[str]] = None,
    ) -> dict[str, FieldSchema]:
        """过滤字段"""
        if not whitelist and not blacklist:
            return fields

        filtered = {}
        for path, schema in fields.items():
            if blacklist and self.is_field_blacklisted(path, blacklist):
                continue
            if whitelist and not self.is_field_whitelisted(path, whitelist):
                continue
            filtered[path] = schema
        return filtered


class GraphQLSampler(Sampler):
    """GraphQL 专用采样器"""

    def sample_graphql(
        self,
        url: str,
        query: str,
        variables: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        auth_method: Optional[str] = None,
        auth_config: Optional[dict[str, Any]] = None,
    ) -> ApiResponse:
        """执行 GraphQL 查询"""
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables

        return self.sample(
            url=url,
            method="POST",
            headers=headers,
            body=body,
            auth_method=auth_method,
            auth_config=auth_config,
        )
