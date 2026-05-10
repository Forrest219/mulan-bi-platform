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

# ─── 生产库防护 ───────────────────────────────────────────────────────────────
# setdefault 只在环境变量未设置时生效；若开发者 shell 已 export DATABASE_URL 指向
# 生产库，测试数据会直接写入生产，此处提前硬拦截。
_db_url = os.environ.get("DATABASE_URL", "")
_db_name = _db_url.rsplit("/", 1)[-1] if "/" in _db_url else _db_url
if _db_url and "test" not in _db_name:
    raise RuntimeError(
        f"\n⛔  测试正在连接非测试数据库，已阻断！\n"
        f"    DATABASE_URL = {_db_url}\n"
        f"    数据库名必须包含 'test'（正确示例：mulan_bi_test）\n"
        f"    修复方法：\n"
        f"      unset DATABASE_URL\n"
        f"      # 或者：\n"
        f"      export DATABASE_URL=postgresql://mulan:mulan@localhost:5432/mulan_bi_test\n"
    )

import pytest
from fastapi.testclient import TestClient
from app.core.database import Base, engine


def _assert_test_database_url(database_url: str):
    """防止测试初始化误删非测试库。"""
    db_name = database_url.rsplit("/", 1)[-1] if "/" in database_url else database_url
    if "test" not in db_name:
        raise RuntimeError(f"Refusing to reset non-test database: {database_url}")


def _reset_test_database_schema(database_url: str):
    """重建测试库 public schema，用于恢复已有表但 Alembic 版本缺失的脏库。"""
    from sqlalchemy import text

    _assert_test_database_url(database_url)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    engine.dispose()


def _run_alembic_migrations():
    """运行 alembic upgrade head；失败时用当前 ORM schema 重建测试库

    若测试库已有表但缺少 alembic_version，直接跳过会留下缺字段 schema。
    这种脏状态只允许在测试库中重建 public schema 后重新迁移；若完整
    Alembic 图仍被非当前测试目标的历史迁移阻断，则使用 ORM schema 兜底，
    保证登录等测试不会在半迁移数据库上运行。
    """
    import logging
    import subprocess
    import sys
    database_url = os.environ.get("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
    _assert_test_database_url(database_url)
    env = {
        "DATABASE_URL": database_url,
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

    def _upgrade():
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=os.path.dirname(os.path.dirname(__file__)),  # backend/
            env=env,
            capture_output=True, text=True, timeout=120,
        )

    result = _upgrade()
    if result.returncode != 0:
        if "DuplicateTable" in result.stderr or "already exists" in result.stderr:
            _reset_test_database_schema(database_url)
            result = _upgrade()
            if result.returncode == 0:
                return
        logging.getLogger(__name__).warning(
            "alembic upgrade head failed on test DB; rebuilding schema from ORM metadata:\n%s\n%s",
            result.stderr,
            result.stdout,
        )
        _reset_test_database_schema(database_url)
        _create_auth_tables()


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
    import services.task_runtime.models_db  # noqa: F401 — registers bi_taskrun_* tables
    import services.tasks.models  # noqa: F401 — registers bi_sync_schedules
    import services.events.models  # noqa: F401 — registers event/outbox tables
    Base.metadata.create_all(bind=engine)


def _create_auth_tables():
    """Fallback schema for auth tests when the full Alembic graph is broken."""
    import services.auth.models  # noqa: F401

    auth_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name.startswith("auth_")
    ]
    Base.metadata.create_all(bind=engine, tables=auth_tables)


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


# 注册自定义 markers
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "skip_db: skip database setup for this test module"
    )


@pytest.fixture(scope="session", autouse=True)
def setup_database(request):
    """session-scope: 只运行一次，为所有测试准备数据库

    跳过标记了 skip_db 的测试模块（纯单元测试不需要数据库）。
    检查逻辑：若收集到的所有测试模块均带有 skip_db marker，跳过初始化。
    """
    def _is_skip_db_marker(marker) -> bool:
        if hasattr(marker, "name") and marker.name == "skip_db":
            return True
        # MarkDecorator 形式（模块级 pytestmark = pytest.mark.skip_db）
        if hasattr(marker, "args") and marker.args and hasattr(marker.args[0], "name"):
            return marker.args[0].name == "skip_db"
        return False

    def _has_skip_db_marker(item) -> bool:
        if hasattr(item, "get_closest_marker"):
            m = item.get_closest_marker("skip_db")
            if m is not None:
                return True
        if hasattr(item, "module") and item.module is not None:
            raw = getattr(item.module, "pytestmark", [])
            for m in (raw if isinstance(raw, list) else [raw]):
                if _is_skip_db_marker(m):
                    return True
        return False

    items = request.session.items
    if items and all(_has_skip_db_marker(item) for item in items):
        yield
        return

    _run_alembic_migrations()
    _ensure_admin()
    yield


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
    function-scoped 数据库 session — savepoint 模式，真正隔离测试数据。

    原理：
      1. 开启外层事务（outer transaction），整个测试期间永不 commit
      2. Session 以 join_transaction_mode="create_savepoint" 绑定到该连接：
         session.commit() 只推进 SAVEPOINT，不真正写库
      3. 测试结束后 outer_trans.rollback()，所有变更回滚

    解决了旧 rollback-after-yield 方案的根本缺陷：
    旧方案在 session.commit() 之后才执行 rollback，此时 rollback 是 no-op。
    """
    from app.core.database import engine
    from sqlalchemy.orm import Session

    conn = engine.connect()
    outer_trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer_trans.rollback()
        conn.close()
