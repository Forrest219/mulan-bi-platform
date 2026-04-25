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
# TestClient 使用 HTTP，cookie 的 secure=True 会导致 cookie 不被发送，必须设为 false
os.environ.setdefault("SECURE_COOKIES", "false")
os.environ.setdefault("SERVICE_JWT_SECRET", "test-jwt-secret-for-service-auth-32ch")

import pytest
from fastapi.testclient import TestClient
from app.core.database import Base, engine


def _run_alembic_migrations():
    """运行 alembic upgrade head — 确保所有迁移历史应用到测试数据库"""
    import subprocess
    import sys
    env = {
        "DATABASE_URL": "postgresql://mulan:mulan@localhost:5432/mulan_bi_test",
        "PYTHONPATH": ".",
        "SERVICE_JWT_SECRET": "test-jwt-secret-for-service-auth-32ch",
        "SESSION_SECRET": "test-session-secret-for-ci-!!",
        "DATASOURCE_ENCRYPTION_KEY": "test-datasource-key-32-bytes-ok!!",
        "TABLEAU_ENCRYPTION_KEY": "test-tableau-key-32-bytes-ok!!",
        "LLM_ENCRYPTION_KEY": "test-llm-key-32-bytes-ok!!!!",
        "SECURE_COOKIES": "false",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "",
    }
    env.update(os.environ)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),  # backend/
        env=env,
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed:\n{result.stderr}\n{result.stdout}")


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
    import services.data_agent.models  # noqa: F401 — registers agent/bi_agent/analysis tables
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
    _run_alembic_migrations()
    _ensure_admin()


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient — 整个测试会话复用，用于无需认证的测试"""
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def admin_client():
    """独立的已登录管理员 TestClient — 避免与 analyst_client 共享 session"""
    from app.main import app
    c = TestClient(app)
    resp = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, f"Admin login failed: {resp.status_code} {resp.text}"
    yield c
    c.cookies.clear()
    c.close()


@pytest.fixture(scope="function")
def analyst_client():
    """独立的已登录 analyst TestClient — 避免与 admin_client 共享 session"""
    from app.main import app
    c = TestClient(app)
    resp = c.post("/api/auth/login", json={"username": "smoke_analyst", "password": "analyst123"})
    assert resp.status_code == 200, f"Analyst login failed: {resp.status_code} {resp.text}"
    yield c
    c.cookies.clear()
    c.close()


@pytest.fixture(scope="function")
def db_session():
    """
    function-scoped 数据库 session — 每个测试后自动 rollback，实现数据隔离。

    用法示例：
        def test_something(db_session):
            db_session.add(SomeModel(...))
            db_session.flush()  # 生成 id，但不提交
            # 测试结束后自动 rollback，不影响其他测试
    """
    from app.core.database import SessionLocal
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture(scope="function", autouse=False)
def rollback_after_test():
    """
    可选 cleanup hook：在长时间运行的测试套件后手动调用清理。
    默认禁用，避免干扰 session-scoped TestClient 的事务管理。
    如需使用，在测试函数签名中加入此 fixture 即可。
    """
    yield
    from app.core.database import SessionLocal
    session = SessionLocal()
    try:
        session.rollback()
    finally:
        session.close()
