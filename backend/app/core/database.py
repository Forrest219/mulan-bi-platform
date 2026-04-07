import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session
from sqlalchemy.sql import func, text
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.exc import OperationalError, ProgrammingError

# 从环境变量读取 PostgreSQL 连接字符串
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable must be set for PostgreSQL connection.")

# 连接池配置
DEFAULT_POOL_SIZE = 10
DEFAULT_MAX_OVERFLOW = 20
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", DEFAULT_POOL_SIZE))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", DEFAULT_MAX_OVERFLOW))

engine = create_engine(
    DATABASE_URL,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_pre_ping=True,  # 启用连接预检查，确保连接池中的连接是活跃的
    pool_recycle=3600,   # 每小时回收一次连接，防止数据库或网络中断导致连接失效
    echo=False,          # 生产环境通常设置为 False
)

# 使用 scoped_session 确保每个线程/协程都有自己的 Session
# 并在请求结束后自动关闭
SessionLocal = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
)

Base = declarative_base()

def init_db():
    """
    在应用启动时创建所有数据库表。
    """
    print("Initializing database schema...")
    try:
        # 导入所有模型，确保 Base.metadata 包含了所有表的定义
        # 实际项目中，Alembic 会管理 schema，这里主要用于首次启动或测试
        from services.auth.models import User, UserGroup, GroupPermission, user_group_members
        from services.logs.models import ScanLog, RuleChangeLog, OperationLog
        from services.requirements.models import Requirement
        from services.datasources.models import DataSource
        from services.llm.models import LLMConfig
        from services.tableau.models import TableauConnection, TableauAsset, TableauAssetDatasource, TableauSyncLog, TableauDatasourceField
        from services.health_scan.models import HealthScanRecord, HealthScanIssue
        from services.semantic_maintenance.models import TableauDatasourceSemantics, TableauDatasourceSemanticVersion, TableauFieldSemantics, TableauFieldSemanticVersion, TableauPublishLog
        from services.events.models import BiEvent, BiNotification
        from services.knowledge_base.models import KbGlossary, KbSchema, KbDocument, KbEmbedding
        from services.governance.models import QualityRule, QualityResult, QualityScore

        Base.metadata.create_all(bind=engine)
        print("Database schema initialized successfully.")
    except (OperationalError, ProgrammingError) as e:
        print(f"Error initializing database schema: {e}")
        print("This might happen if the database is not yet available or if Alembic is managing migrations.")
        print("If this is a fresh start, ensure your DATABASE_URL is correct and the PostgreSQL server is running.")
        # Re-raise for critical errors during startup if needed, or just log and continue
        # For production, Alembic handles migrations, so create_all might not be strictly necessary here
        # but it's good for dev/testing setup.
    except Exception as e:
        print(f"An unexpected error occurred during database initialization: {e}")
        raise

def get_db() -> Generator:
    """
    FastAPI 依赖注入函数，为每个请求提供一个数据库会话。
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class DatabaseContext:
    """
    Celery 任务级数据库上下文管理器（Spec 07 §7.3 P1 修复）。
    使用方式：
        with get_db_context() as db:
            ...
    禁止在异步任务中自行 new Session 或调用 expire_all()。
    """
    def __enter__(self):
        self.session = SessionLocal()
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session is not None:
            self.session.close()
        return False


def get_db_context():
    """
    Celery 任务专用上下文管理器工厂函数（Spec 07 §7.3 P1 修复）。
    返回 DatabaseContext 实例，供 `with` 语句使用。
    """
    return DatabaseContext()

# 导出 PostgreSQL 特定的 JSONB 类型和 SQL 函数/文本表达式
JSONB = PG_JSONB
sa_func = func
sa_text = text
