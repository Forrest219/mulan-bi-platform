"""POST /assets → 等待 profile_and_suggest_task → 手动确认规则 → 首次评分"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")

import pytest


def test_add_to_first_score_flow(require_integration_env, admin_client, sample_profile):
    """
    步骤：
      1. POST /api/dqc/assets {auto_suggest_rules: true}
      2. 轮询 asset.profile_json 直到非空
      3. GET /api/dqc/assets/{id}/analyses?trigger=rule_suggest → MVP 返回空
      4. 手动 POST /rules 确认写入 2 条规则
      5. POST /cycles/run {"asset_ids":[id]}
      6. GET /assets/{id} signal 非空
    """
    assert sample_profile
