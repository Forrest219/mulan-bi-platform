"""
测试配置 — conftest.py
提供 FastAPI TestClient fixture 和数据库隔离

在导入 app 之前必须设置所有必需的环境变量。
"""
import os

# 必须在 import app 之前设置，否则各模块会抛出 RuntimeError
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")  # 禁用自动创建管理员

import pytest
from fastapi.testclient import TestClient
from app.core.database import Base, engine


def _create_tables():
    """确保所有 ORM 模型对应的表已创建"""
    from app.core.database import SessionLocal
    # 触发所有模型的 import 以注册到 Base.metadata
    import services.auth.models  # noqa: F401
    import services.logs.models  # noqa: F401
    import services.requirements.models  # noqa: F401
    import services.datasources.models  # noqa: F401
    import services.llm.models  # noqa: F401
    import services.tableau.models  # noqa: F401
    import services.health_scan.models  # noqa: F401
    import services.semantic_maintenance.models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def _ensure_admin():
    """确保测试数据库中有管理员账户和 analyst 测试账户"""
    from services.auth.models import User
    from app.core.database import SessionLocal
    import hashlib
    import secrets

    session = SessionLocal()
    try:
        def _create_user(username: str, display_name: str, role: str, permissions: list, password: str):
            existing = session.query(User).filter(User.username == username).first()
            if existing:
                return
            salt = secrets.token_hex(16)
            pw_hash = f"{salt}${hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()}"
            user = User(
                username=username,
                display_name=display_name,
                password_hash=pw_hash,
                email=f"{username}@mulan.local",
                role=role,
                permissions=permissions,
                is_active=True,
            )
            session.add(user)

        # 管理员（所有权限）
        _create_user(
            username="admin",
            display_name="管理员",
            role="admin",
            permissions=[
                "ddl_check", "ddl_generator", "database_monitor",
                "rule_config", "scan_logs", "user_management",
                "tableau", "llm",
            ],
            password="admin123",
        )
        # analyst（部分权限，用于 RBAC 冒烟测试）
        _create_user(
            username="smoke_analyst",
            display_name="Analyst Smoke User",
            role="analyst",
            permissions=[
                "database_monitor",   # 可访问连接中心、数据健康
                # 没有: ddl_check, tableau, user_management, llm, adminOnly
            ],
            password="analyst123",
        )
        session.commit()
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """session-scope: 只运行一次，为所有测试准备数据库"""
    _create_tables()
    _ensure_admin()


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient — 整个测试会话复用"""
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def admin_client(client: TestClient):
    """已登录管理员的 TestClient — session-scoped client 上先清空 cookies 再登录"""
    client.cookies.clear()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, f"Admin login failed: {resp.status_code} {resp.text}"
    yield client
    # 测试结束后清空 cookies，防止污染后续使用 session-scoped client 的测试
    client.cookies.clear()
