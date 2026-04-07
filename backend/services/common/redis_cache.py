"""Redis 缓存工具（供 NL-to-Query 路由防抖用）"""
import json
import logging
from typing import Optional, List

from services.common.settings import get_redis_url

logger = logging.getLogger(__name__)

# 缓存 TTL（1小时）
_CACHE_TTL_SECONDS = 3600


def _get_redis_client():
    """获取 Redis 客户端（延迟导入）"""
    try:
        import redis
        return redis.from_url(get_redis_url(), decode_responses=True)
    except Exception as e:
        logger.warning("Redis 连接失败，缓存将降级为内存: %s", e)
        return None


_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = _get_redis_client()
    return _redis_client


class RedisCache:
    """简单的 Redis 缓存封装，仅用于 NL-to-Query 路由防抖"""

    @staticmethod
    def get(key: str) -> Optional[str]:
        """读取缓存值"""
        client = get_redis_client()
        if client is None:
            return None
        try:
            return client.get(key)
        except Exception as e:
            logger.warning("Redis GET 失败 [%s]: %s", key, e)
            return None

    @staticmethod
    def set(key: str, value: str, ttl: int = _CACHE_TTL_SECONDS) -> bool:
        """写入缓存值"""
        client = get_redis_client()
        if client is None:
            return False
        try:
            client.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.warning("Redis SET 失败 [%s]: %s", key, e)
            return False

    @staticmethod
    def delete(key: str) -> bool:
        """删除缓存"""
        client = get_redis_client()
        if client is None:
            return False
        try:
            client.delete(key)
            return True
        except Exception as e:
            logger.warning("Redis DELETE 失败 [%s]: %s", key, e)
            return False


# === NL-to-Query 专用缓存键 ===

DS_FIELDS_CACHE_PREFIX = "nlq:ds_fields:"
DS_FIELDS_CACHE_TTL = 3600  # 1小时

# ─────────────────────────────────────────────────────────────────────────────
# 限速键（PRD §10.2 — 单用户 20 次/分钟）
# ─────────────────────────────────────────────────────────────────────────────

RATE_LIMIT_KEY_PREFIX = "nlq:rate:"
RATE_LIMIT_WINDOW = 60        # 滑动窗口秒数
RATE_LIMIT_MAX = 20           # 每分钟最大请求数


def check_rate_limit(user_id: int) -> bool:
    """
    检查用户是否超过限速（PRD §10.2 — 单用户 20 次/分钟）。

    使用 Redis 滑动窗口计数器实现。
    返回 True 表示通过，False 表示超限（应返回 NLQ_010）。
    """
    import time
    client = get_redis_client()
    if client is None:
        # Redis 不可用时，放过请求（fail-open）
        return True

    key = f"{RATE_LIMIT_KEY_PREFIX}{user_id}"
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    try:
        # 使用有序集合（sorted set）：score=时间戳，member=请求ID
        pipe = client.pipeline()
        # 移除窗口外的旧记录
        pipe.zremrangebyscore(key, 0, window_start)
        # 当前窗口计数
        count = client.zcard(key)
        if count >= RATE_LIMIT_MAX:
            return False
        # 记录本次请求
        pipe.zadd(key, {f"{now}": now})
        pipe.expire(key, RATE_LIMIT_WINDOW)
        pipe.execute()
        return True
    except Exception as e:
        logger.warning("Redis 限速检查失败 [%s]: %s", key, e)
        return True  # fail-open


def cache_datasource_fields(asset_id: int, field_captions: List[str]) -> bool:
    """
    缓存数据源的 field_caption 列表（仅缓存字段名列表，防抖用）。
    """
    key = f"{DS_FIELDS_CACHE_PREFIX}{asset_id}"
    value = json.dumps(field_captions, ensure_ascii=False)
    return RedisCache.set(key, value, DS_FIELDS_CACHE_TTL)


def get_cached_datasource_fields(asset_id: int) -> Optional[List[str]]:
    """
    获取缓存的数据源 field_caption 列表。
    返回 None 表示缓存未命中。
    """
    key = f"{DS_FIELDS_CACHE_PREFIX}{asset_id}"
    value = RedisCache.get(key)
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None
