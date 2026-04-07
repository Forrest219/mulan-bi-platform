"""DDL 规则运行时缓存 — 基于 Redis"""
import json
import logging
from typing import Dict, Any, Optional, List

from services.common.settings import get_redis_url

logger = logging.getLogger(__name__)

# 缓存键前缀
RULES_CACHE_PREFIX = "ddl:rules:"
RULES_CACHE_TTL = 300  # 5 分钟

# P0 修复：Redis 客户端单例，避免连接池泄露
_redis_client = None


def _get_redis_client():
    """获取 Redis 客户端（单例模式）"""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(get_redis_url(), decode_responses=True)
        except Exception as e:
            logger.warning("Redis 连接失败: %s", e)
            return None
    return _redis_client


class RuleCache:
    """
    DDL 规则运行时缓存（Redis）。

    缓存键: ddl:rules:{scene_type}:{db_type}
    TTL: 300 秒（5 分钟）

    API 层变更规则时，需主动调用 invalidate_* 方法失效缓存。
    """

    @staticmethod
    def _cache_key(scene_type: str = "ALL", db_type: str = "MySQL") -> str:
        return f"{RULES_CACHE_PREFIX}{scene_type}:{db_type}"

    @staticmethod
    def get(scene_type: str = "ALL", db_type: str = "MySQL") -> Optional[List[Dict[str, Any]]]:
        """
        获取缓存的规则列表。

        Returns:
            缓存命中返回规则列表，否则返回 None
        """
        client = _get_redis_client()
        if client is None:
            return None

        key = RuleCache._cache_key(scene_type, db_type)
        try:
            data = client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning("Redis GET 失败 [%s]: %s", key, e)
            return None

    @staticmethod
    def set(rules: List[Dict[str, Any]], scene_type: str = "ALL", db_type: str = "MySQL") -> bool:
        """
        写入规则列表缓存。

        Returns:
            写入成功返回 True
        """
        client = _get_redis_client()
        if client is None:
            return False

        key = RuleCache._cache_key(scene_type, db_type)
        try:
            client.setex(key, RULES_CACHE_TTL, json.dumps(rules, ensure_ascii=False))
            return True
        except Exception as e:
            logger.warning("Redis SET 失败 [%s]: %s", key, e)
            return False

    @staticmethod
    def invalidate(scene_type: str = "ALL") -> bool:
        """
        失效指定场景的所有缓存键。

        变更规则时调用，删除 {scene_type}:* 和 ALL:* 缓存。
        """
        client = _get_redis_client()
        if client is None:
            return False

        try:
            # 失效目标场景和 ALL 场景
            patterns = [
                f"{RULES_CACHE_PREFIX}{scene_type}:*",
                f"{RULES_CACHE_PREFIX}ALL:*",
            ]
            for pattern in patterns:
                keys = client.keys(pattern)
                if keys:
                    client.delete(*keys)
            return True
        except Exception as e:
            logger.warning("Redis DELETE 失败 [%s]: %s", pattern, e)
            return False

    @staticmethod
    def invalidate_all() -> bool:
        """
        失效所有 DDL 规则缓存。
        """
        client = _get_redis_client()
        if client is None:
            return False

        try:
            pattern = f"{RULES_CACHE_PREFIX}*"
            keys = client.keys(pattern)
            if keys:
                client.delete(*keys)
            return True
        except Exception as e:
            logger.warning("Redis DELETE 失败 [%s]: %s", pattern, e)
            return False
