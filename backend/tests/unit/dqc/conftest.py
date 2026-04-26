"""
conftest.py — DQC Unit Tests Infrastructure

Provides consistent mock fixtures and auto-patching for all DQC unit tests.
"""
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:***@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest


# ---------------------------------------------------------------------------
# Auto-patch get_current_user for ALL governance_runtime tests
# ---------------------------------------------------------------------------
# Some test classes (GetGovernanceRule, GetGovernanceScanResults, GetAssetDrift,
# GetAssetSignal) call API endpoints that internally invoke get_current_user().
# Without patching, the real function reads session cookies and raises 401.
# We patch it at the definition site so the reference in governance_runtime.py
# is also replaced (governance_runtime imports get_current_user directly).

_original_get_current_user = None


@pytest.fixture(autouse=True)
def mock_get_current_user(monkeypatch):
    """Auto-mock get_current_user for every test to avoid real auth."""
    from app.core import dependencies

    def fake_get_current_user(request, db):
        return {"id": 1, "username": "admin", "role": "admin"}

    monkeypatch.setattr(dependencies, "get_current_user", fake_get_current_user)


@pytest.fixture
def admin_user():
    return {"id": 1, "role": "admin"}


@pytest.fixture
def data_admin_user():
    return {"id": 2, "role": "data_admin"}


@pytest.fixture
def regular_user():
    return {"id": 3, "role": "user"}


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db
