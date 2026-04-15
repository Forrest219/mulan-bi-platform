"""
Test conftest for tests/services/tableau/

Overrides parent tests/conftest.py fixtures so DB is not required.
These are pure unit tests that mock all DB and HTTP dependencies.
"""
import os

# Set env vars before parent conftest runs
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("TABLEAU_MCP_SERVER_URL", "http://localhost:3927/tableau-mcp")
os.environ.setdefault("TABLEAU_MCP_PROTOCOL_VERSION", "2025-06-18")

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Override parent: no DB needed for these pure unit tests."""
    pass


@pytest.fixture(scope="session")
def client():
    """Override parent: no FastAPI client needed here."""
    pass
