"""IDOR: 用户 A 不应能修改用户 B 的资产"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")

import pytest


def test_non_owner_cannot_patch(require_integration_env, admin_client, analyst_client):
    """
    前置：admin 创建 asset（owner=admin.id）
    测试：analyst PATCH /assets/{id} → 403 DQC_004
    """
    pytest.skip("real IDOR test requires pre-seeded assets; covered in unit via _check_asset_ownership")
