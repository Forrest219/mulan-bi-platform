"""Capability Rate Limiter — Redis 滑动窗口 + PostgreSQL 兜底

对应 spec §5.4 — 基于 Redis INCR + EXPIRE 滑动窗口算法。
Redis 不可用时降级到 PostgreSQL（bi_capability_rate_limits 表）。
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

from sqlalchemy import text

from app.core.database import SessionLocal
from services.common.settings import get_redis_url
from .errors import CapabilityRateLimited

logger = logging.getLogger(__name__)

# Redis key 前缀
RL_KEY_PREFIX = "cap:rl"

_redis_client = None


def _get_redis_client():
    """获取 Redis 客户端（惰性单例）"""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(get_redis_url(), decode_responses=True)
        except Exception as e:
            logger.warning("Redis unavailable for rate limiter: %s", e)
            return None
    return _redis_client


def _pg_fallback_increment(
    capability: str,
    user_id: int,
    window_seconds: int,
) -> tuple[int, bool]:
    """PostgreSQL 滑动窗口计数（Redis 不可用时的兜底）

    Returns:
        (current_count, is_allowed)
    """
    db = SessionLocal()
    try:
        now = time.time()
        window_start = now - window_seconds
        key = f"{capability}:{user_id}"

        # 清理过期记录
        db.execute(
            text("DELETE FROM bi_capability_rate_limits WHERE key = :key AND window_start < :window_start"),
            {"key": key, "window_start": window_start},
        )

        # 计数
        result = db.execute(
            text("SELECT COUNT(*) FROM bi_capability_rate_limits WHERE key = :key AND window_start >= :window_start"),
            {"key": key, "window_start": window_start},
        )
        current = result.scalar() or 0

        # 插入新记录
        db.execute(
            text(
                "INSERT INTO bi_capability_rate_limits (key, window_start, created_at) VALUES (:key, :window_start, :now)"
            ),
            {"key": key, "window_start": now, "now": now},
        )
        db.commit()

        return current + 1, True
    except Exception as e:
        logger.error("PG rate limit fallback failed: %s", e)
        db.rollback()
        return 999, True  # fail-open
    finally:
        db.close()


class RateLimiter:
    """
    Redis 滑动窗口限流器。

    Key: cap:rl:{capability}:{user_id}
    算法: ZSET score=时间戳，统计 [now-window, now] 区间内的请求数
    """

    def __init__(self):
        self._redis = _get_redis_client()

    def _redis_sliding_window(
        self,
        capability: str,
        user_id: int,
        rate: int,
        window_seconds: int,
    ) -> tuple[int, bool]:
        """Redis ZSET 滑动窗口实现

        Returns:
            (current_count, is_allowed)
        """
        key = f"{RL_KEY_PREFIX}:{capability}:{user_id}"
        now = time.time()
        window_start = now - window_seconds

        try:
            pipe = self._redis.pipeline()
            # 移除窗口外的旧记录
            pipe.zremrangebyscore(key, 0, window_start)
            # 计数当前窗口内请求
            pipe.zcard(key)
            # 写入当前请求时间戳
            pipe.zadd(key, {str(now): now})
            # 设置过期
            pipe.expire(key, window_seconds + 1)
            results = pipe.execute()

            current = results[1]  # zcard result

            if current >= rate:
                # 超过限制，移除刚才的写入（不计数）
                self._redis.zrem(key, str(now))
                return current, False

            return current + 1, True
        except Exception as e:
            logger.warning("Redis rate limit failed, using PG fallback: %s", e)
            return _pg_fallback_increment(capability, user_id, window_seconds)

    def acquire(
        self,
        capability: str,
        user_id: int,
        rate: int,
        window_seconds: int,
    ) -> None:
        """申请一个 rate limit token。

        Args:
            capability: 能力名称
            user_id: 用户 ID
            rate: 时间窗口内最大请求数
            window_seconds: 时间窗口（秒）

        Raises:
            CapabilityRateLimited: 超过限制时抛出
        """
        if self._redis is None:
            _pg_fallback_increment(capability, user_id, window_seconds)
        else:
            current, allowed = self._redis_sliding_window(capability, user_id, rate, window_seconds)
            if not allowed:
                retry_after = window_seconds // rate if rate > 0 else window_seconds
                raise CapabilityRateLimited(
                    f"Rate limit exceeded for '{capability}': {current}/{rate} in {window_seconds}s",
                    retry_after=retry_after,
                )

    def check(
        self,
        capability: str,
        user_id: int,
        rate: int,
        window_seconds: int,
    ) -> bool:
        """仅检查是否超限，不消耗 token（用于预检）"""
        key = f"{RL_KEY_PREFIX}:{capability}:{user_id}"
        now = time.time()
        window_start = now - window_seconds

        try:
            if self._redis:
                self._redis.zremrangebyscore(key, 0, window_start)
                count = self._redis.zcard(key)
                return count < rate
        except Exception:
            pass
        return True  # fail-open
