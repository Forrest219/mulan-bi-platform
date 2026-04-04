"""
Alembic env.py — Mulan BI Platform
从环境变量 DATABASE_URL 读取连接信息，导入所有模型的 metadata。
"""
import os
import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 确保 backend/ 在 sys.path 中
backend_dir = str(Path(__file__).resolve().parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.database import Base

# 导入所有模型，确保它们注册到 Base.metadata
from services.auth.models import User, UserGroup, GroupPermission  # noqa: F401
from services.logs.models import ScanLog, RuleChangeLog, OperationLog  # noqa: F401
from services.requirements.models import Requirement  # noqa: F401
from services.datasources.models import DataSource  # noqa: F401
from services.llm.models import LLMConfig  # noqa: F401
from services.tableau.models import (  # noqa: F401
    TableauConnection, TableauAsset, TableauAssetDatasource,
    TableauSyncLog, TableauDatasourceField,
)
from services.health_scan.models import HealthScanRecord, HealthScanIssue  # noqa: F401
from services.rules.models import RuleConfig  # noqa: F401
from services.semantic_maintenance.models import (  # noqa: F401
    TableauDatasourceSemantics, TableauDatasourceSemanticVersion,
    TableauFieldSemantics, TableauFieldSemanticVersion, TableauPublishLog,
)
from services.events.models import BiEvent, BiNotification  # noqa: F401

config = context.config

# 从环境变量覆盖 sqlalchemy.url
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
