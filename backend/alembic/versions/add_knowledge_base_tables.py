"""Add knowledge base tables

Revision ID: add_knowledge_base
Revises: add_events_notifications_tables
Create Date: 2026-04-05

Revision notes:
- kb_glossary: 业务术语表（SSOT 原则）
- kb_schemas: 数据模型语义描述
- kb_documents: 知识文档
- kb_embeddings: 向量索引（HNSW 索引，pgvector 0.5+）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "add_knowledge_base"
down_revision = "add_events_notifications_tables"  # 假设上一个迁移是事件通知表
branch_labels = None
depends_on = None


def upgrade():
    # === kb_glossary ===
    op.create_table(
        "kb_glossary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("term", sa.String(128), nullable=False),
        sa.Column("canonical_term", sa.String(128), nullable=False),
        sa.Column("synonyms_json", JSONB, server_default="[]", nullable=True),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("formula", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), server_default="concept", nullable=False),
        sa.Column("related_fields_json", JSONB, server_default="[]", nullable=True),
        sa.Column("source", sa.String(16), server_default="manual", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_glossary_term", "kb_glossary", ["term"])
    op.create_index("ix_glossary_category", "kb_glossary", ["category"])
    op.create_index("ix_glossary_status", "kb_glossary", ["status"])
    op.create_table_constraint(
        sa.UniqueConstraint("canonical_term", name="uq_glossary_canonical"),
        table_name="kb_glossary"
    )

    # === kb_schemas ===
    op.create_table(
        "kb_schemas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("datasource_id", sa.Integer(), nullable=False),
        sa.Column("schema_yaml", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("auto_generated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schema_datasource", "kb_schemas", ["datasource_id"])
    op.create_table_constraint(
        sa.UniqueConstraint("datasource_id", "version", name="uq_schema_ds_version"),
        table_name="kb_schemas"
    )

    # === kb_documents ===
    op.create_table(
        "kb_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("format", sa.String(16), server_default="markdown", nullable=False),
        sa.Column("category", sa.String(64), server_default="general", nullable=False),
        sa.Column("tags_json", JSONB, server_default="[]", nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_embedded_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_doc_category", "kb_documents", ["category"])
    op.create_index("ix_doc_status", "kb_documents", ["status"])

    # === kb_embeddings（HNSW 索引）===
    op.create_table(
        "kb_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", JSONB, nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_emb_source", "kb_embeddings", ["source_type", "source_id"])

    # 创建 HNSW 向量索引（PostgreSQL 16 + pgvector 0.5+）
    # 注意：VECTOR 类型不带维度约束（解除 1536 硬编码）
    op.execute("""
        CREATE INDEX ix_emb_hnsw
        ON kb_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m=16, ef_construction=200)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_emb_hnsw")
    op.drop_table("kb_embeddings")
    op.drop_table("kb_documents")
    op.drop_table("kb_schemas")
    op.drop_table("kb_glossary")
