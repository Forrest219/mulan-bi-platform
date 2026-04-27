"""Capability Result Cache — Redis 缓存

对应 spec §5.6 — 基于 SHA256 的缓存 key，TTL 从 YAML 配置读取。
Key: cap:cache:{capability}:{hash(params + principal_role)}
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from services.common.settings import get_redis_url

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "cap:cache"

_redis_client = None


def _get_redis_client():
    """获取 Redis 客户端（惰性单例）"""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(get_redis_url(), decode_responses=True)
        except Exception as e:
            logger.warning("Redis unavailable for result cache: %s", e)
            return None
    return _redis_client


def _canonical_json(d: dict) -> str:
    """稳定的 JSON 序列化（key 排序）"""
    return json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)


def _build_cache_key(capability: str, cache_key_fields: dict, principal_role: str) -> str:
    """构建缓存 key：cap:cache:{capability}:{sha256(canonical_json(cache_key_fields + principal_role))}"""
    # 缓存 key 必须含 principal_role，防止跨角色串读（spec §7 Security）
    payload = {**cache_key_fields, "_principal_role": principal_role}
    content_hash = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:32]
    return f"{CACHE_KEY_PREFIX}:{capability}:{content_hash}"


class ResultCache:
    """
    Capability 结果缓存。

    - Redis key: cap:cache:{capability}:{sha256_hash}
    - TTL: per-capability 配置
    - 读取时检查 Redis，命中则返回；未命中则返回 None
    """

    def __init__(self):
        self._redis = _get_redis_client()

    def get(
        self,
        capability: str,
        cache_key_fields: dict,
        principal_role: str,
    ) -> Optional[Any]:
        """
        尝试从缓存读取。

        Args:
            capability: 能力名称
            cache_key_fields: 从 params 中提取的 key_fields 字典
            principal_role: 主体角色（必须含入 key）

        Returns:
            命中返回缓存数据，否则 None
        """
        if self._redis is None:
            return None

        key = _build_cache_key(capability, cache_key_fields, principal_role)
        try:
            data = self._redis.get(key)
            if data:
                logger.debug("Cache HIT: %s", key)
                return json.loads(data)
            logger.debug("Cache MISS: %s", key)
            return None
        except Exception as e:
            logger.warning("Cache GET failed [%s]: %s", key, e)
            return None

    def set(
        self,
        capability: str,
        cache_key_fields: dict,
        principal_role: str,
        result: Any,
        ttl_seconds: int,
    ) -> bool:
        """
        写入缓存。

        Args:
            capability: 能力名称
            cache_key_fields: 从 params 中提取的 key_fields 字典
            principal_role: 主体角色
            result: 要缓存的结果数据
            ttl_seconds: TTL（秒）

        Returns:
            写入成功返回 True
        """
        if self._redis is None:
            return False

        key = _build_cache_key(capability, cache_key_fields, principal_role)
        try:
            self._redis.setex(key, ttl_seconds, json.dumps(result, ensure_ascii=False, default=str))
            logger.debug("Cache SET: %s (ttl=%ds)", key, ttl_seconds)
            return True
        except Exception as e:
            logger.warning("Cache SET failed [%s]: %s", key, e)
            return False

    def invalidate(
        self,
        capability: str,
        cache_key_fields: Optional[dict] = None,
        principal_role: Optional[str] = None,
    ) -> bool:
        """
        失效缓存。

        - 指定 cache_key_fields: 只删除那一条
        - 仅传 capability: 删除该 capability 的所有缓存
        """
        if self._redis is None:
            return False

        try:
            if cache_key_fields is not None and principal_role is not None:
                key = _build_cache_key(capability, cache_key_fields, principal_role)
                self._redis.delete(key)
            else:
                pattern = f"{CACHE_KEY_PREFIX}:{capability}:*"
                keys = self._redis.keys(pattern)
                if keys:
                    self._redis.delete(*keys)
            return True
        except Exception as e:
            logger.warning("Cache invalidation failed: %s", e)
            return False

    def clear_all(self) -> bool:
        """清空所有 capability 缓存（谨慎使用）"""
        if self._redis is None:
            return False
        try:
            pattern = f"{CACHE_KEY_PREFIX}:*"
            keys = self._redis.keys(pattern)
            if keys:
                self._redis.delete(*keys)
            return True
        except Exception as e:
            logger.warning("Cache clear_all failed: %s", e)
            return False
