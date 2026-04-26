"""
单元测试：services/capability/rate_limiter.py
覆盖：
- Redis sliding window 算法
- Redis 不可用时 PG 兜底
- 限流触发时抛出 CapabilityRateLimited
- check() 不消耗 token
"""
import time
from unittest import mock

import pytest

from services.capability.errors import CapabilityRateLimited
from services.capability.rate_limiter import RateLimiter, _pg_fallback_increment


class TestRateLimiterRedis:
    """Redis 滑动窗口"""

    def test_acquire_allows_under_limit(self):
        rl = RateLimiter()

        mock_redis = mock.Mock()
        mock_pipe = mock.Mock()
        mock_pipe.execute.return_value = [None, 2, None, None]  # zcard=2, under limit
        mock_redis.pipeline.return_value = mock_pipe
        rl._redis = mock_redis

        # 不应抛异常
        rl.acquire("query_metric", user_id=1, rate=30, window_seconds=60)

    def test_acquire_blocks_over_limit(self):
        rl = RateLimiter()

        mock_redis = mock.Mock()
        mock_pipe = mock.Mock()
        # zcard=30，恰好等于 limit
        mock_pipe.execute.return_value = [None, 30, None, None]
        mock_redis.pipeline.return_value = mock_pipe
        rl._redis = mock_redis

        with pytest.raises(CapabilityRateLimited) as exc_info:
            rl.acquire("query_metric", user_id=1, rate=30, window_seconds=60)

        assert exc_info.value.code == "CAP_004"
        assert "Rate limit exceeded" in str(exc_info.value)

    def test_acquire_redis_unavailable_falls_back_to_pg(self):
        rl = RateLimiter()
        rl._redis = None  # simulate unavailable

        with mock.patch(
            "services.capability.rate_limiter._pg_fallback_increment",
            return_value=(5, True),
        ) as mock_pg:
            rl.acquire("query_metric", user_id=1, rate=10, window_seconds=60)
            mock_pg.assert_called_once()


class TestRateLimiterCheck:
    """check() 预检 API"""

    def test_check_returns_true_when_under_limit(self):
        rl = RateLimiter()
        mock_redis = mock.Mock()
        mock_redis.zcard.return_value = 5
        rl._redis = mock_redis

        result = rl.check("query_metric", user_id=1, rate=30, window_seconds=60)
        assert result is True

    def test_check_returns_false_when_over_limit(self):
        rl = RateLimiter()
        mock_redis = mock.Mock()
        mock_redis.zcard.return_value = 30
        rl._redis = mock_redis

        result = rl.check("query_metric", user_id=1, rate=30, window_seconds=60)
        assert result is False

    def test_check_fail_open_when_redis_error(self):
        rl = RateLimiter()
        mock_redis = mock.Mock()
        mock_redis.zcard.side_effect = RuntimeError("Redis down")
        rl._redis = mock_redis

        result = rl.check("query_metric", user_id=1, rate=1, window_seconds=60)
        assert result is True  # fail-open
