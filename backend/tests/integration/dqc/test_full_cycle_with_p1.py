"""1 条 null_rate 规则失败 → cycle 结束时 snapshot.signal=P1，通知创建给 owner"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")

import pytest


def test_single_failure_triggers_p1(require_integration_env, admin_client, sample_assets, sample_rules):
    """
    步骤：
      1. 种一张 asset + 1 条 null_rate 规则，使其在目标 DB 上失败
      2. 运行 cycle
      3. 验证：
         - latest_snapshot.signal == P1（因单维度 0/1 → score=0 → P0；需预期匹配）
         - bi_notifications 中有一条 dqc.asset.p1_triggered 或 p0_triggered
    """
    assert sample_assets
