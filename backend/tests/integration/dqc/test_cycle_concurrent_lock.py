"""两个进程同时 POST /cycles/run → 第 2 个返回 DQC_030"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")

import pytest


def test_concurrent_cycle_locked(require_integration_env, admin_client):
    """
    步骤：
      1. 进程 A 持有 redis 锁 dqc:cycle:lock:full
      2. 进程 B POST /api/dqc/cycles/run
      3. 预期：response.status_code == 409 && error_code == DQC_030

    单元测试已覆盖锁的互斥逻辑（tests/unit/dqc/test_orchestrator_lock.py），
    此用例用于真实 Redis 环境冒烟。
    """
    pytest.skip("requires real Redis + multi-process coordination")
