import logging
import os
from typing import Generator

logger = logging.getLogger(__name__)

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
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
    sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
)

Base = declarative_base()


_REQUIRED_RUNTIME_RELATIONS = {
    "bi_analysis_sessions": "table",
    "bi_analysis_session_steps": "table",
    "bi_analysis_session_steps_seq": "sequence",
    "bi_analysis_insights": "table",
    "bi_analysis_reports": "table",
}

_REQUIRED_RUNTIME_COLUMNS = {
    "bi_analysis_sessions": ("session_metadata",),
}


def _redact_database_url(url: str) -> str:
    try:
        return str(make_url(url).set(password="***"))
    except Exception:
        return "<invalid DATABASE_URL>"


def _import_models_for_metadata() -> None:
    # Import all models only for explicit test/dev create_all fallback.
    from services.auth.models import User, UserGroup, GroupPermission, user_group_members  # noqa: F401
    from services.logs.models import ScanLog, RuleChangeLog, OperationLog  # noqa: F401
    from services.requirements.models import Requirement  # noqa: F401
    from services.datasources.models import DataSource  # noqa: F401
    from services.llm.models import LLMConfig  # noqa: F401
    from services.tableau.models import TableauConnection, TableauAsset, TableauAssetDatasource, TableauSyncLog, TableauDatasourceField  # noqa: F401
    from services.health_scan.models import HealthScanRecord, HealthScanIssue  # noqa: F401
    from services.semantic_maintenance.models import TableauDatasourceSemantics, TableauDatasourceSemanticVersion, TableauFieldSemantics, TableauFieldSemanticVersion, TableauPublishLog  # noqa: F401
    from services.events.models import BiEvent, BiNotification, BiEventSubscription  # noqa: F401
    from services.knowledge_base.models import KbGlossary, KbSchema, KbDocument, KbEmbedding  # noqa: F401
    from services.dw_assets.models import DwAssetTable, DwAssetColumn, DwAssetPartition, DwAssetLineageEdge, DwAssetSyncRun  # noqa: F401
    from services.mcp.models import McpServer  # noqa: F401
    from services.data_agent import models as data_agent_models  # noqa: F401
    from services.help_agent import models as help_agent_models  # noqa: F401
    from services.tasks import models as task_models  # noqa: F401
    from services.task_runtime import models_db as task_runtime_models  # noqa: F401
    from services.platform_settings import models as platform_settings_models  # noqa: F401
    from models import metrics as metric_models  # noqa: F401


def _create_schema_from_metadata_for_explicit_dev_mode() -> None:
    _import_models_for_metadata()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("CREATE SEQUENCE IF NOT EXISTS bi_analysis_session_steps_seq"))
    Base.metadata.create_all(bind=engine)


def _verify_runtime_schema() -> None:
    missing_objects: list[str] = []
    missing_columns: list[str] = []
    alembic_versions: list[str] = []

    with engine.connect() as conn:
        alembic_exists = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
        if alembic_exists is None:
            missing_objects.append("alembic_version table")
        else:
            alembic_versions = list(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())

        for relation, relation_type in _REQUIRED_RUNTIME_RELATIONS.items():
            exists = conn.execute(text("SELECT to_regclass(:relation)"), {"relation": f"public.{relation}"}).scalar()
            if exists is None:
                missing_objects.append(f"{relation_type} {relation}")

        for table_name, column_names in _REQUIRED_RUNTIME_COLUMNS.items():
            for column_name in column_names:
                exists = conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = :table_name
                          AND column_name = :column_name
                        """
                    ),
                    {"table_name": table_name, "column_name": column_name},
                ).scalar()
                if exists is None:
                    missing_columns.append(f"{table_name}.{column_name}")

    if missing_objects or missing_columns:
        details = []
        if missing_objects:
            details.append(f"missing objects: {', '.join(missing_objects)}")
        if missing_columns:
            details.append(f"missing columns: {', '.join(missing_columns)}")
        version_text = ", ".join(alembic_versions) if alembic_versions else "<none>"
        raise RuntimeError(
            "Database schema preflight failed; run `cd backend && alembic upgrade head` "
            "or apply the repair migration before starting the app. "
            f"alembic_version={version_text}; "
            f"DATABASE_URL={_redact_database_url(DATABASE_URL)}; "
            + "; ".join(details)
        )


def init_db():
    """
    验证数据库 schema。

    正式运行路径只允许 Alembic 管理 schema，禁止在启动时隐式
    create_all()。如测试或临时开发确需 ORM 建表，必须显式设置：
    MULAN_DB_CREATE_ALL_ON_STARTUP=1。
    """
    logger.info("Verifying database schema...")
    try:
        if os.environ.get("MULAN_DB_CREATE_ALL_ON_STARTUP") == "1":
            logger.warning("MULAN_DB_CREATE_ALL_ON_STARTUP=1; creating schema from ORM metadata.")
            _create_schema_from_metadata_for_explicit_dev_mode()
        else:
            _verify_runtime_schema()
        logger.info("Database schema verified successfully.")
    except (OperationalError, ProgrammingError) as e:
        logger.error("Database schema preflight query failed: %s", e)
        raise
    except Exception as e:
        logger.error("Database schema preflight failed: %s", e)
        raise

def get_db() -> Generator:
    """
    FastAPI 依赖注入函数，为每个请求提供一个数据库会话。
    """
    session = SessionLocal()
    # SessionLocal is scoped; startup/import-time failures in the same worker
    # thread can leave a transaction aborted. Clear any inherited state before
    # handing the session to request handlers.
    session.rollback()
    try:
        yield session
    finally:
        session.close()
        SessionLocal.remove()


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
