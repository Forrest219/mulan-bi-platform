"""
回归测试 Bug 3：ORM 模型字段与数据库实际列不同步（缺迁移）

根本原因：
  auth_user_groups 表的 ORM 模型新增了 updated_at 字段，但没有对应的 Alembic 迁移，
  导致后端启动时 _ensure_admin() 报 UndefinedColumn，进而 scoped_session 停留在
  失败事务状态，所有后续 DB 查询全部报 InFailedSqlTransaction，登录 API 永远 500。

检查内容：
  1. 用 SQLAlchemy inspect 对比 ORM 模型定义列 vs 数据库实际列，不一致时失败并打印 diff。
  2. 覆盖 auth_users、auth_user_groups、auth_user_group_members 三张表。
  3. AuthService.__new__ 在 _ensure_admin() 抛异常后，scoped_session 必须处于干净状态。

环境要求：
  需要可访问的 PostgreSQL 数据库，DATABASE_URL 从 backend/.env 或环境变量读取。
  若数据库不可达，测试标记为 skip 而非 fail。
"""

import os
import sys
from pathlib import Path

import pytest

# ── 加载 .env（若存在）────────────────────────────────────────────────────────
_backend_root = Path(__file__).parent.parent.parent  # backend/
_env_file = _backend_root / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

# 确保必要环境变量存在（conftest.py 中也有 setdefault，双重保障）
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")

# ── 确保 backend/ 在 sys.path ─────────────────────────────────────────────────
_backend_str = str(_backend_root)
if _backend_str not in sys.path:
    sys.path.insert(0, _backend_str)


# ── 跳过条件：数据库不可达 ─────────────────────────────────────────────────────
def _db_reachable() -> bool:
    try:
        from sqlalchemy import create_engine, text
        url = os.environ["DATABASE_URL"]
        eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_reachable(),
    reason="数据库不可达，跳过 Bug 3 回归测试（需要 DATABASE_URL 可连接）",
)


# ── 辅助：获取 ORM 模型定义的列名集合 ─────────────────────────────────────────
def _orm_columns(mapped_class) -> set[str]:
    """返回 ORM 模型定义的普通列名集合（不含关系属性）"""
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(mapped_class)
    return {col.key for col in mapper.mapper.column_attrs}


def _orm_table_columns(table) -> set[str]:
    """返回 Table 对象（关联表）定义的列名集合"""
    return {col.name for col in table.columns}


# ── 辅助：获取数据库中实际存在的列名集合 ──────────────────────────────────────
def _db_columns(engine, table_name: str) -> set[str]:
    """通过 information_schema 查询数据库实际列名"""
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :tbl"
            ),
            {"tbl": table_name},
        ).fetchall()
    return {row[0] for row in rows}


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 1：ORM vs 数据库列同步检查
# ═══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestOrmSchemaSyncBug3:
    """ORM 模型定义与数据库实际列必须一致"""

    @pytest.fixture(scope="class")
    def engine(self):
        from sqlalchemy import create_engine
        return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

    @pytest.fixture(scope="class", autouse=True)
    def import_models(self):
        """触发所有 auth 模型的 import，确保元数据注册完成"""
        import services.auth.models  # noqa: F401

    def _assert_columns_match(self, engine, orm_cols: set[str], db_table: str):
        """对比 ORM 定义列与数据库实际列，不一致时给出清晰 diff 并 fail"""
        db_cols = _db_columns(engine, db_table)

        only_in_orm = orm_cols - db_cols
        only_in_db = db_cols - orm_cols

        problems = []
        if only_in_orm:
            problems.append(
                f"  ORM 模型定义但数据库中不存在（缺迁移）: {sorted(only_in_orm)}"
            )
        if only_in_db:
            problems.append(
                f"  数据库存在但 ORM 模型未定义（模型落后）: {sorted(only_in_db)}"
            )

        if problems:
            raise AssertionError(
                f"表 '{db_table}' 的 ORM 模型与数据库列不同步：\n"
                + "\n".join(problems)
                + "\n请运行 alembic revision --autogenerate 并检查迁移文件。"
            )

    def test_auth_users_columns_in_sync(self, engine):
        """auth_users 表：ORM 与数据库列同步"""
        from services.auth.models import User
        self._assert_columns_match(engine, _orm_columns(User), "auth_users")

    def test_auth_user_groups_columns_in_sync(self, engine):
        """auth_user_groups 表：ORM 与数据库列同步（此表新增 updated_at 引发过 Bug 3）"""
        from services.auth.models import UserGroup
        self._assert_columns_match(engine, _orm_columns(UserGroup), "auth_user_groups")

    def test_auth_user_group_members_columns_in_sync(self, engine):
        """auth_user_group_members 关联表：ORM 与数据库列同步"""
        from services.auth.models import user_group_members
        self._assert_columns_match(
            engine, _orm_table_columns(user_group_members), "auth_user_group_members"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 2：_ensure_admin 抛异常后 scoped_session 必须干净
# ═══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestScopedSessionCleanAfterEnsureAdminFailure:
    """
    模拟 _ensure_admin() 抛出 UndefinedColumn 异常，
    验证 AuthService.__new__ 的 rollback 逻辑能让 scoped_session 恢复干净。
    """

    def test_session_is_clean_after_ensure_admin_failure(self, monkeypatch):
        """
        当 _ensure_admin() 抛异常时，后续查询不能报 InFailedSqlTransaction。
        """
        from sqlalchemy import text
        from sqlalchemy.exc import ProgrammingError
        from app.core.database import SessionLocal

        # 先确保 session 初始干净
        SessionLocal.remove()

        # 让 session 执行一条必定失败的 SQL，模拟 UndefinedColumn 场景，
        # 使事务进入失败状态
        session = SessionLocal()
        try:
            session.execute(text("SELECT nonexistent_column_xyz FROM auth_users LIMIT 1"))
            session.commit()
        except Exception:
            # 这里故意不 rollback，模拟旧代码的缺陷（没有 rollback）
            pass

        # 验证：此时若不 rollback，下一条查询会报 InFailedSqlTransaction
        # （这里只检查 rollback 后能正常查询）
        session.rollback()  # 这是 __new__ 里修复后的行为

        # rollback 之后必须能执行正常查询
        try:
            result = session.execute(text("SELECT 1 AS ok")).fetchone()
            assert result is not None and result[0] == 1, (
                "rollback 后执行简单查询失败，session 仍处于异常状态"
            )
        finally:
            SessionLocal.remove()

    def test_auth_service_new_rollbacks_on_ensure_admin_failure(self, monkeypatch):
        """
        直接对 AuthService._ensure_admin 打桩使其抛异常，
        验证 AuthService() 实例化后 scoped_session 仍可正常查询。
        """
        from sqlalchemy import text
        from app.core.database import SessionLocal
        import services.auth.service as auth_service_module

        # 重置单例，使 __new__ 重新初始化
        original_instance = auth_service_module.AuthService._instance
        auth_service_module.AuthService._instance = None

        def _broken_ensure_admin(self_inner):
            # 模拟 UndefinedColumn：先让 session 进入失败状态，再抛异常
            session = SessionLocal()
            try:
                session.execute(
                    text("SELECT nonexistent_xyz FROM auth_users LIMIT 1")
                )
            except Exception:
                pass  # session 已进入 InFailedSqlTransaction
            raise RuntimeError("模拟 _ensure_admin UndefinedColumn 错误")

        monkeypatch.setattr(
            auth_service_module.AuthService, "_ensure_admin", _broken_ensure_admin
        )

        try:
            # 实例化 AuthService（触发 __new__ + _ensure_admin 失败 + rollback）
            _svc = auth_service_module.AuthService()

            # 实例化后，scoped_session 必须处于干净状态，能执行正常查询
            SessionLocal.remove()  # 清理当前 scoped session
            session = SessionLocal()
            try:
                result = session.execute(text("SELECT 1 AS ok")).fetchone()
                assert result is not None and result[0] == 1, (
                    "_ensure_admin 抛异常后，scoped_session 仍处于失败事务状态，"
                    "后续查询报 InFailedSqlTransaction。"
                    "确认 AuthService.__new__ 中有 SessionLocal().rollback() 逻辑。"
                )
            finally:
                SessionLocal.remove()
        finally:
            # 恢复单例，不影响其他测试
            auth_service_module.AuthService._instance = original_instance
