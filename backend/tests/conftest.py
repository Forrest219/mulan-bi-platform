"""
测试配置 — conftest.py
提供 FastAPI TestClient fixture 和数据库隔离
"""
import os
import pytest
from fastapi.testclient import TestClient

# 使用测试数据库（可通过环境变量覆盖）
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")

from app.main import app


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient — 整个测试会话复用"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_client(client: TestClient):
    """已登录管理员的 TestClient"""
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    if resp.status_code == 200:
        # session cookie is set automatically
        pass
    return client
