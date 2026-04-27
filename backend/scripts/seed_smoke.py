#!/usr/bin/env python3
"""
Seed script for smoke test users and minimal smoke business data.

Creates two idempotent users:
- admin (role=admin, all permissions)
- smoke_analyst (role=user, permissions=['database_monitor'])

Usage:
    python scripts/seed_smoke.py

Requires environment variables (or .env file via python-dotenv):
    DATABASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD, DATASOURCE_ENCRYPTION_KEY,
    TABLEAU_ENCRYPTION_KEY, LLM_ENCRYPTION_KEY, SERVICE_JWT_SECRET
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add backend/ to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import hashlib
import secrets
import uuid

from app.core.database import SessionLocal
from services.auth.models import User
from services.common.crypto import CryptoHelper
from services.datasources.models import DataSource
from services.knowledge_base.models import KbDocument, KbGlossary, KbSchema
from services.llm.models import LLMConfig
from services.tableau.models import TableauAsset, TableauConnection, TableauDatasourceField


def hash_password(password: str) -> str:
    """Hash password using the same PBKDF2 format as AuthService."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    )
    return f"{salt}${digest.hex()}"


def seed_users(db):
    """Create or update smoke test users (idempotent)."""
    changes = []

    # ── admin ──────────────────────────────────────────────────────────────
    admin_username = os.getenv("SMOKE_ADMIN_USERNAME", "admin")
    admin_password = os.getenv("SMOKE_ADMIN_PASSWORD", "admin123")
    admin = db.query(User).filter(User.username == admin_username).first()
    if not admin:
        admin = User(
            username=admin_username,
            display_name="Smoke Admin",
            password_hash=hash_password(admin_password),
            email=f"{admin_username}@smoke.local",
            role="admin",
            is_active=True,
            permissions=[
                "ddl_check",
                "ddl_generator",
                "database_monitor",
                "rule_config",
                "scan_logs",
                "user_management",
                "tableau",
                "llm",
            ],
        )
        db.add(admin)
        changes.append(f"Created admin user ({admin_username}/{'*' * len(admin_password)})")
    else:
        admin.display_name = "Smoke Admin"
        admin.password_hash = hash_password(admin_password)
        admin.email = admin.email or f"{admin_username}@smoke.local"
        admin.role = "admin"
        admin.is_active = True
        admin.permissions = [
            "ddl_check",
            "ddl_generator",
            "database_monitor",
            "rule_config",
            "scan_logs",
            "user_management",
            "tableau",
            "llm",
        ]
        changes.append(f"Admin user already exists ({admin_username})")

    # ── smoke_analyst ───────────────────────────────────────────────────────
    analyst_username = os.getenv("SMOKE_ANALYST_USERNAME", "smoke_analyst")
    analyst_password = os.getenv("SMOKE_ANALYST_PASSWORD", "analyst123")
    analyst = db.query(User).filter(User.username == analyst_username).first()
    if not analyst:
        analyst = User(
            username=analyst_username,
            display_name="Smoke Analyst",
            password_hash=hash_password(analyst_password),
            email=f"{analyst_username}@smoke.local",
            role="user",
            is_active=True,
            permissions=["database_monitor"],
        )
        db.add(analyst)
        changes.append(
            f"Created smoke_analyst ({analyst_username}/{'*' * len(analyst_password)}, "
            "role=user, permissions=['database_monitor'])"
        )
    else:
        analyst.display_name = "Smoke Analyst"
        analyst.password_hash = hash_password(analyst_password)
        analyst.email = analyst.email or f"{analyst_username}@smoke.local"
        analyst.role = "user"
        analyst.is_active = True
        analyst.permissions = ["database_monitor"]
        changes.append(f"smoke_analyst already exists ({analyst_username})")

    db.commit()
    return changes


def _encrypt_with_env(env_name: str, plaintext: str) -> tuple[str | None, str | None]:
    """Encrypt only when the matching env key is configured."""
    key = os.getenv(env_name)
    if not key:
        return None, f"{env_name} is not set"
    return CryptoHelper(key).encrypt(plaintext), None


def _upsert_by_filter(db, model, filters: dict, values: dict):
    query = db.query(model)
    for field, value in filters.items():
        query = query.filter(getattr(model, field) == value)
    obj = query.first()
    created = obj is None
    if created:
        obj = model(**filters)
        db.add(obj)
    for field, value in values.items():
        setattr(obj, field, value)
    db.flush()
    return obj, created


def seed_llm_config(db):
    encrypted_key, skip_reason = _encrypt_with_env("LLM_ENCRYPTION_KEY", "smoke_disabled_api_key")
    if skip_reason:
        return [f"Skipped LLMConfig smoke seed: {skip_reason}; encrypted field is required"]

    cfg, created = _upsert_by_filter(
        db,
        LLMConfig,
        {"purpose": "smoke_default", "display_name": "smoke_llm_default"},
        {
            "provider": "openai",
            "base_url": "https://example.invalid/smoke-openai/v1",
            "api_key_encrypted": encrypted_key,
            "model": "smoke_model",
            "temperature": 0.0,
            "max_tokens": 256,
            "is_active": False,
            "priority": -100,
        },
    )
    db.commit()
    return [f"{'Created' if created else 'Updated'} LLM config ({cfg.display_name}, inactive)"]


def seed_mcp_server(db):
    return [
        "Skipped MCP server smoke seed: mcp_servers ORM/schema are not aligned "
        "in the current branch; external MCP coverage remains workflow-driven"
    ]


def seed_tableau_data(db, owner_id: int):
    encrypted_token, skip_reason = _encrypt_with_env("TABLEAU_ENCRYPTION_KEY", "smoke_disabled_pat")
    if skip_reason:
        return [f"Skipped Tableau smoke seed: {skip_reason}; token_encrypted is required"]

    conn, conn_created = _upsert_by_filter(
        db,
        TableauConnection,
        {"name": "smoke_tableau_connection"},
        {
            "server_url": "https://tableau.example.invalid",
            "site": "smoke_site",
            "api_version": "3.21",
            "connection_type": "mcp",
            "token_name": "smoke_pat",
            "token_encrypted": encrypted_token,
            "owner_id": owner_id,
            "is_active": False,
            "auto_sync_enabled": False,
            "sync_interval_hours": 24,
            "last_test_success": None,
            "last_test_message": None,
            "sync_status": "idle",
            "mcp_direct_enabled": False,
            "mcp_server_url": "http://127.0.0.1:39999/smoke-mcp",
        },
    )
    db.flush()

    workbook, workbook_created = _upsert_by_filter(
        db,
        TableauAsset,
        {"connection_id": conn.id, "tableau_id": "smoke_workbook_001"},
        {
            "asset_type": "workbook",
            "name": "smoke_workbook_sales",
            "project_name": "smoke_project",
            "description": "Smoke workbook seed data",
            "owner_name": "smoke_owner",
            "content_url": "/views/smoke_workbook_sales",
            "raw_metadata": {"smoke": True},
            "is_deleted": False,
            "tags": ["smoke"],
            "view_count": 0,
            "health_score": 1.0,
            "health_details": {"status": "smoke"},
        },
    )
    datasource, datasource_created = _upsert_by_filter(
        db,
        TableauAsset,
        {"connection_id": conn.id, "tableau_id": "smoke_datasource_001"},
        {
            "asset_type": "datasource",
            "name": "smoke_datasource_sales",
            "project_name": "smoke_project",
            "description": "Smoke datasource asset seed data",
            "owner_name": "smoke_owner",
            "raw_metadata": {"smoke": True},
            "is_deleted": False,
            "tags": ["smoke"],
            "field_count": 2,
            "is_certified": False,
        },
    )
    _upsert_by_filter(
        db,
        TableauDatasourceField,
        {
            "asset_id": datasource.id,
            "datasource_luid": "smoke_datasource_001",
            "field_name": "smoke_revenue",
        },
        {
            "field_caption": "Smoke Revenue",
            "data_type": "number",
            "role": "measure",
            "description": "Smoke revenue measure",
            "aggregation": "SUM",
            "is_calculated": False,
            "metadata_json": {"smoke": True},
        },
    )
    _upsert_by_filter(
        db,
        TableauDatasourceField,
        {
            "asset_id": datasource.id,
            "datasource_luid": "smoke_datasource_001",
            "field_name": "smoke_order_date",
        },
        {
            "field_caption": "Smoke Order Date",
            "data_type": "date",
            "role": "dimension",
            "description": "Smoke order date dimension",
            "aggregation": None,
            "is_calculated": False,
            "metadata_json": {"smoke": True},
        },
    )
    db.commit()
    return [
        f"{'Created' if conn_created else 'Updated'} Tableau connection ({conn.name}, inactive)",
        f"{'Created' if workbook_created else 'Updated'} Tableau asset ({workbook.name})",
        f"{'Created' if datasource_created else 'Updated'} Tableau asset ({datasource.name}) and fields",
    ]


def seed_datasource_metric_and_schema(db, owner_id: int):
    changes = []
    encrypted_password, skip_reason = _encrypt_with_env("DATASOURCE_ENCRYPTION_KEY", "smoke_disabled_password")
    if skip_reason:
        return [
            "Skipped DataSource/Metric/KbSchema smoke seed: "
            f"{skip_reason}; encrypted datasource password is required"
        ]

    ds = (
        db.query(DataSource)
        .filter(DataSource.name == "smoke_datasource_postgres", DataSource.owner_id == owner_id)
        .first()
    )
    ds_created = ds is None
    if ds is None:
        ds = DataSource(name="smoke_datasource_postgres", owner_id=owner_id)
        db.add(ds)
    ds.db_type = "postgresql"
    ds.host = "127.0.0.1"
    ds.port = 5432
    ds.database_name = "smoke_db"
    ds.username = "smoke_user"
    ds.password_encrypted = encrypted_password
    ds.extra_config = {"schema": "smoke_schema", "sslmode": "disable"}
    ds.is_active = False
    db.flush()
    changes.append(f"{'Created' if ds_created else 'Updated'} datasource ({ds.name}, inactive)")

    try:
        from models.metrics import BiMetricDefinition, BiMetricLineage, BiMetricVersion
    except Exception as exc:
        changes.append(f"Skipped metric smoke seed: metrics models could not be imported ({exc})")
    else:
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        metric = (
            db.query(BiMetricDefinition)
            .filter(BiMetricDefinition.tenant_id == tenant_id, BiMetricDefinition.name == "smoke_revenue")
            .first()
        )
        metric_created = metric is None
        if metric is None:
            metric = BiMetricDefinition(
                tenant_id=tenant_id,
                name="smoke_revenue",
                created_by=owner_id,
            )
            db.add(metric)
        metric.name_zh = "Smoke Revenue"
        metric.metric_type = "base"
        metric.business_domain = "smoke"
        metric.description = "Smoke metric seed data"
        metric.formula = "SUM(smoke_orders.smoke_revenue)"
        metric.formula_template = "sum"
        metric.aggregation_type = "sum"
        metric.result_type = "decimal"
        metric.unit = "USD"
        metric.precision = 2
        metric.datasource_id = ds.id
        metric.table_name = "smoke_orders"
        metric.column_name = "smoke_revenue"
        metric.filters = [{"field": "smoke_is_test", "op": "=", "value": False}]
        metric.is_active = False
        metric.lineage_status = "manual"
        metric.sensitivity_level = "public"
        db.flush()

        lineage = (
            db.query(BiMetricLineage)
            .filter(
                BiMetricLineage.metric_id == metric.id,
                BiMetricLineage.datasource_id == ds.id,
                BiMetricLineage.table_name == "smoke_orders",
                BiMetricLineage.column_name == "smoke_revenue",
            )
            .first()
        )
        if lineage is None:
            db.add(
                BiMetricLineage(
                    tenant_id=tenant_id,
                    metric_id=metric.id,
                    datasource_id=ds.id,
                    table_name="smoke_orders",
                    column_name="smoke_revenue",
                    column_type="decimal",
                    relationship_type="direct",
                    hop_number=0,
                    transformation_logic="SUM",
                )
            )

        version = (
            db.query(BiMetricVersion)
            .filter(BiMetricVersion.metric_id == metric.id, BiMetricVersion.version == 1)
            .first()
        )
        if version is None:
            db.add(
                BiMetricVersion(
                    tenant_id=tenant_id,
                    metric_id=metric.id,
                    version=1,
                    change_type="create",
                    changes={"seed": "smoke_metric"},
                    changed_by=owner_id,
                    change_reason="smoke_seed",
                )
            )
        changes.append(f"{'Created' if metric_created else 'Updated'} metric (smoke_revenue, inactive)")

    schema_yaml = """version: 1
datasource_name: smoke_datasource_postgres
tables:
  - name: smoke_orders
    description: Smoke orders fact table
    columns:
      - name: smoke_revenue
        type: decimal
        description: Smoke revenue amount
      - name: smoke_order_date
        type: date
        description: Smoke order date
relationships: []
"""
    schema = (
        db.query(KbSchema)
        .filter(KbSchema.datasource_id == ds.id, KbSchema.version == 1)
        .first()
    )
    schema_created = schema is None
    if schema is None:
        schema = KbSchema(datasource_id=ds.id, version=1)
        db.add(schema)
    schema.schema_yaml = schema_yaml
    schema.description = "smoke_ datasource schema seed data"
    schema.auto_generated = False
    schema.created_by = owner_id
    changes.append(f"{'Created' if schema_created else 'Updated'} knowledge schema for {ds.name}")

    db.commit()
    return changes


def seed_knowledge_base(db, owner_id: int):
    glossary, glossary_created = _upsert_by_filter(
        db,
        KbGlossary,
        {"canonical_term": "smoke_revenue"},
        {
            "term": "smoke_revenue",
            "synonyms_json": ["smoke_sales", "smoke_gmv"],
            "definition": "Smoke revenue term used by local seed data.",
            "formula": "SUM(smoke_orders.smoke_revenue)",
            "category": "metric",
            "related_fields_json": ["smoke_orders.smoke_revenue"],
            "source": "manual",
            "status": "active",
            "created_by": owner_id,
            "updated_by": owner_id,
        },
    )
    document, document_created = _upsert_by_filter(
        db,
        KbDocument,
        {"title": "smoke_knowledge_overview"},
        {
            "content": "smoke_ knowledge document for local smoke testing.",
            "format": "markdown",
            "category": "smoke",
            "tags_json": ["smoke"],
            "status": "active",
            "chunk_count": 0,
            "created_by": owner_id,
            "updated_by": owner_id,
        },
    )
    db.commit()
    return [
        f"{'Created' if glossary_created else 'Updated'} knowledge glossary ({glossary.canonical_term})",
        f"{'Created' if document_created else 'Updated'} knowledge document ({document.title})",
        "Skipped knowledge embedding smoke seed: vector dimensions/model contract are runtime-specific",
    ]


def seed_business_data(db):
    """Create or update minimal smoke business data without activating external integrations."""
    changes = []
    admin_username = os.getenv("SMOKE_ADMIN_USERNAME", "admin")
    admin = db.query(User).filter(User.username == admin_username).first()
    if not admin:
        return [f"Skipped business smoke seed: admin user {admin_username!r} was not found"]

    seeders = (
        seed_llm_config,
        seed_mcp_server,
        lambda session: seed_tableau_data(session, admin.id),
        lambda session: seed_knowledge_base(session, admin.id),
        lambda session: seed_datasource_metric_and_schema(session, admin.id),
    )
    for seeder in seeders:
        try:
            changes.extend(seeder(db))
        except Exception as exc:
            db.rollback()
            changes.append(f"Skipped {getattr(seeder, '__name__', 'business seed')}: {exc}")
    return changes


def main():
    db = SessionLocal()
    try:
        print("=== Smoke Seed ===")
        for line in seed_users(db):
            print(line)
        print("=== Smoke Business Seed ===")
        for line in seed_business_data(db):
            print(line)
        print("=== Seed complete ===")
    finally:
        db.close()


if __name__ == "__main__":
    main()
