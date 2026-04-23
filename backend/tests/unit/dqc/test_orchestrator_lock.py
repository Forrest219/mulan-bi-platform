"""Orchestrator Redis 锁单元测试"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.dqc.orchestrator import _RedisLock


class FakeRedis:
    """内存版 SET NX EX"""

    def __init__(self):
        self._store = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    def eval(self, script, numkeys, *args):
        key = args[0]
        token = args[1]
        current = self._store.get(key)
        if current == token:
            del self._store[key]
            return 1
        return 0


class TestRedisLock:
    def test_acquire_release_round_trip(self, monkeypatch):
        fake = FakeRedis()
        lock = _RedisLock("dqc:test:lock", ttl_seconds=60)
        monkeypatch.setattr(lock, "_client", fake)
        assert lock.try_acquire() is True
        assert fake._store.get("dqc:test:lock") == lock.token
        lock.release()
        assert "dqc:test:lock" not in fake._store

    def test_second_acquire_fails(self, monkeypatch):
        fake = FakeRedis()
        first = _RedisLock("dqc:test:lock2", ttl_seconds=60)
        second = _RedisLock("dqc:test:lock2", ttl_seconds=60)
        monkeypatch.setattr(first, "_client", fake)
        monkeypatch.setattr(second, "_client", fake)
        assert first.try_acquire() is True
        assert second.try_acquire() is False

    def test_release_requires_matching_token(self, monkeypatch):
        fake = FakeRedis()
        owner = _RedisLock("dqc:test:lock3", ttl_seconds=60)
        intruder = _RedisLock("dqc:test:lock3", ttl_seconds=60)
        monkeypatch.setattr(owner, "_client", fake)
        monkeypatch.setattr(intruder, "_client", fake)
        owner.try_acquire()
        # intruder has token but never acquired; release() 不会误删
        intruder.release()
        assert "dqc:test:lock3" in fake._store
        owner.release()
        assert "dqc:test:lock3" not in fake._store

    def test_fallback_when_redis_unavailable(self, monkeypatch):
        """Redis 不可用 → 锁 fail-open（不阻塞 scheduled cycle），以保证单机 / 测试环境可运行"""
        lock = _RedisLock("dqc:test:lock4", ttl_seconds=60)
        monkeypatch.setattr(lock, "_client_or_none", lambda: None)
        assert lock.try_acquire() is True
        lock.release()  # 不抛
