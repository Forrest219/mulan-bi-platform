"""
单元测试：services/capability/result_cache.py
覆盖：
- _build_cache_key 正确包含 principal_role
- get() 命中/未命中
- set() 写入 TTL
- invalidate() 删除
- clear_all()
- Redis 不可用时 fail-open
"""
import hashlib
import json
from unittest import mock

import pytest

from services.capability.result_cache import (
    ResultCache,
    _build_cache_key,
    _canonical_json,
)


class TestCacheKeyConstruction:
    """缓存 key 必须包含 principal_role（spec §7 Security）"""

    def test_different_roles_different_keys(self):
        key1 = _build_cache_key("query_metric", {"datasource_id": 1, "metric": "sales"}, "analyst")
        key2 = _build_cache_key("query_metric", {"datasource_id": 1, "metric": "sales"}, "admin")
        assert key1 != key2

    def test_same_params_same_role_same_key(self):
        key1 = _build_cache_key("query_metric", {"datasource_id": 1, "metric": "sales"}, "analyst")
        key2 = _build_cache_key("query_metric", {"datasource_id": 1, "metric": "sales"}, "analyst")
        assert key1 == key2

    def test_key_prefix(self):
        key = _build_cache_key("query_metric", {"metric": "sales"}, "analyst")
        assert key.startswith("cap:cache:query_metric:")


class TestResultCacheGetSet:
    """get / set 往返"""

    def test_get_returns_deserialized_data(self):
        rc = ResultCache()
        mock_redis = mock.Mock()
        mock_redis.get.return_value = json.dumps({"rows": [1, 2, 3]})
        rc._redis = mock_redis

        result = rc.get("query_metric", {"metric": "sales"}, "analyst")
        assert result == {"rows": [1, 2, 3]}

    def test_get_returns_none_on_miss(self):
        rc = ResultCache()
        mock_redis = mock.Mock()
        mock_redis.get.return_value = None
        rc._redis = mock_redis

        result = rc.get("query_metric", {"metric": "sales"}, "analyst")
        assert result is None

    def test_set_writes_with_ttl(self):
        rc = ResultCache()
        mock_redis = mock.Mock()
        rc._redis = mock_redis

        rc.set("query_metric", {"metric": "sales"}, "analyst", {"rows": []}, ttl_seconds=300)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 300  # TTL

    def test_get_returns_none_when_redis_unavailable(self):
        rc = ResultCache()
        rc._redis = None
        assert rc.get("query_metric", {}, "analyst") is None

    def test_set_returns_false_when_redis_unavailable(self):
        rc = ResultCache()
        rc._redis = None
        assert rc.set("query_metric", {}, "analyst", {}, 300) is False


class TestResultCacheInvalidate:
    """缓存失效"""

    def test_invalidate_specific_key(self):
        rc = ResultCache()
        mock_redis = mock.Mock()
        rc._redis = mock_redis

        rc.invalidate("query_metric", {"metric": "sales"}, "analyst")
        mock_redis.delete.assert_called_once()

    def test_invalidate_all_for_capability(self):
        rc = ResultCache()
        mock_redis = mock.Mock()
        mock_redis.keys.return_value = ["cap:cache:query_metric:abc", "cap:cache:query_metric:def"]
        rc._redis = mock_redis

        rc.invalidate("query_metric")
        mock_redis.delete.assert_called_once()

    def test_clear_all(self):
        rc = ResultCache()
        mock_redis = mock.Mock()
        mock_redis.keys.return_value = ["cap:cache:query_metric:abc", "cap:cache:search_asset:xyz"]
        rc._redis = mock_redis

        rc.clear_all()
        mock_redis.delete.assert_called_once()
