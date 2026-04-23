"""
Metrics Agent — 血缘解析引擎测试（T3）

测试策略：
  - mock LLM，不发真实网络请求
  - 使用项目已有 db_session fixture（tests/conftest.py）+ 真实 PostgreSQL test DB
  - 每个测试后通过 fixture rollback 或显式清理实现数据隔离

LLM 返回值 key 说明（从 services/llm/service.py 确认）：
  complete_for_semantic() 返回 { "content": str } 或 { "error": str }

运行：
    cd /Users/forrest/Projects/mulan-bi-platform/backend
    pytest tests/services/metrics_agent/test_lineage.py -v
"""
import asyncio
import json
import os
import uuid

# 环境变量必须在所有 import 之前设置
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy import text

from app.core.errors import MulanError
from models.metrics import BiMetricDefinition, BiMetricLineage
from services.metrics_agent.lineage import resolve_lineage


# =============================================================================
# 常量 & 辅助
# =============================================================================

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
USER_ID = 1  # 需要存在于 auth_users

# LLM Mock 响应（confidence=0.95 → resolved）
_LLM_RESPONSE_HIGH_CONFIDENCE = {
    "content": json.dumps({
        "source_tables": ["orders"],
        "source_metrics": [],
        "fields": [
            {
                "table_name": "orders",
                "column_name": "order_amount",
                "column_type": "DECIMAL",
                "relationship_type": "source",
                "hop_number": 0,
                "transformation_logic": None,
            }
        ],
        "confidence": 0.95,
        "notes": None,
    })
}

# LLM Mock 响应（confidence=0.5 → unknown，但血缘仍写入）
_LLM_RESPONSE_LOW_CONFIDENCE = {
    "content": json.dumps({
        "source_tables": ["orders"],
        "source_metrics": [],
        "fields": [
            {
                "table_name": "orders",
                "column_name": "order_amount",
                "column_type": "DECIMAL",
                "relationship_type": "source",
                "hop_number": 0,
                "transformation_logic": None,
            }
        ],
        "confidence": 0.5,
        "notes": "低置信度：公式较简单",
    })
}

# LLM Mock 响应（多字段，用于覆盖测试）
_LLM_RESPONSE_MULTI_FIELDS = {
    "content": json.dumps({
        "source_tables": ["orders", "products"],
        "source_metrics": [],
        "fields": [
            {
                "table_name": "orders",
                "column_name": "order_amount",
                "column_type": "DECIMAL",
                "relationship_type": "source",
                "hop_number": 0,
                "transformation_logic": None,
            },
            {
                "table_name": "products",
                "column_name": "product_name",
                "column_type": "VARCHAR",
                "relationship_type": "upstream_joined",
                "hop_number": 1,
                "transformation_logic": "JOIN products ON orders.product_id = products.id",
            },
        ],
        "confidence": 0.88,
        "notes": None,
    })
}


def _run_async(coro):
    """在同步测试中运行异步函数的辅助函数。"""
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture()
def valid_datasource(db_session):
    """确保 bi_data_sources 中有 id=1 的数据源（幂等插入）。"""
    existing = db_session.execute(
        text("SELECT id FROM bi_data_sources WHERE id = 1")
    ).first()
    if existing is None:
        db_session.execute(
            text(
                """
                INSERT INTO bi_data_sources
                    (id, name, db_type, host, port, database_name, username,
                     password_encrypted, is_active, owner_id)
                VALUES
                    (1, 'test_ds', 'postgresql', 'localhost', 5432,
                     'testdb', 'user', 'enc_pwd', true, 1)
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        db_session.flush()
    return 1


@pytest.fixture()
def valid_user(db_session):
    """确保 auth_users 中有 id=1 的用户（幂等插入）。"""
    existing = db_session.execute(
        text("SELECT id FROM auth_users WHERE id = 1")
    ).first()
    if existing is None:
        db_session.execute(
            text(
                """
                INSERT INTO auth_users (id, username, display_name, password_hash, email, role, is_active)
                VALUES (1, 'creator', 'creator', 'hash', 'creator@test.local', 'data_admin', true)
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        db_session.flush()


@pytest.fixture()
def sample_metric(db_session, valid_datasource, valid_user):
    """创建一个用于测试的指标，测试结束后清理。"""
    metric = BiMetricDefinition(
        tenant_id=TENANT_ID,
        name=f"test_lineage_metric_{uuid.uuid4().hex[:8]}",
        name_zh="测试血缘指标",
        metric_type="atomic",
        datasource_id=1,
        table_name="fact_orders",
        column_name="order_amount",
        formula="SUM(orders.order_amount)",
        is_active=False,
        lineage_status="unknown",
        sensitivity_level="public",
        created_by=USER_ID,
    )
    db_session.add(metric)
    db_session.commit()
    db_session.refresh(metric)

    yield metric

    # 清理：删除血缘记录和指标（避免污染其他测试）
    db_session.query(BiMetricLineage).filter(
        BiMetricLineage.metric_id == metric.id
    ).delete(synchronize_session=False)
    db_session.query(BiMetricDefinition).filter(
        BiMetricDefinition.id == metric.id
    ).delete(synchronize_session=False)
    db_session.commit()


# =============================================================================
# Case 1: LLM 路径 — confidence=0.95 → lineage_status="resolved"，写入 1 条血缘
# =============================================================================

@patch(
    "services.metrics_agent.lineage.llm_service.complete_for_semantic",
    new_callable=AsyncMock,
)
def test_resolve_lineage_llm_high_confidence(mock_llm, db_session, sample_metric):
    """LLM 高置信度（>=0.7）→ lineage_status="resolved"，写入 1 条血缘记录。"""
    mock_llm.return_value = _LLM_RESPONSE_HIGH_CONFIDENCE

    result = _run_async(
        resolve_lineage(
            db=db_session,
            metric_id=sample_metric.id,
            tenant_id=TENANT_ID,
        )
    )

    # 断言返回值
    assert result["lineage_status"] == "resolved"
    assert result["lineage_count"] == 1

    # 断言 DB 中血缘记录
    db_session.expire(sample_metric)
    records = db_session.query(BiMetricLineage).filter(
        BiMetricLineage.metric_id == sample_metric.id
    ).all()
    assert len(records) == 1
    assert records[0].table_name == "orders"
    assert records[0].column_name == "order_amount"
    assert records[0].relationship_type == "source"

    # 断言指标 lineage_status 更新
    db_session.refresh(sample_metric)
    assert sample_metric.lineage_status == "resolved"

    # 确认 LLM 被调用了一次
    mock_llm.assert_called_once()
    call_kwargs = mock_llm.call_args.kwargs
    assert call_kwargs["purpose"] == "lineage"


# =============================================================================
# Case 2: LLM 路径 — confidence=0.5 → lineage_status="unknown"，血缘记录仍写入
# =============================================================================

@patch(
    "services.metrics_agent.lineage.llm_service.complete_for_semantic",
    new_callable=AsyncMock,
)
def test_resolve_lineage_llm_low_confidence(mock_llm, db_session, sample_metric):
    """LLM 低置信度（<0.7）→ lineage_status="unknown"，但血缘记录仍写入。"""
    mock_llm.return_value = _LLM_RESPONSE_LOW_CONFIDENCE

    result = _run_async(
        resolve_lineage(
            db=db_session,
            metric_id=sample_metric.id,
            tenant_id=TENANT_ID,
        )
    )

    # lineage_status 保持 unknown
    assert result["lineage_status"] == "unknown"
    # 血缘记录仍然写入
    assert result["lineage_count"] == 1

    # 验证 DB
    records = db_session.query(BiMetricLineage).filter(
        BiMetricLineage.metric_id == sample_metric.id
    ).all()
    assert len(records) == 1

    db_session.refresh(sample_metric)
    assert sample_metric.lineage_status == "unknown"


# =============================================================================
# Case 3: Manual override — 直接写入手动血缘，lineage_status="manual"
# =============================================================================

def test_resolve_lineage_manual_override(db_session, sample_metric):
    """manual_override=True → 跳过 LLM，写入手动血缘，lineage_status="manual"。"""
    manual_records = [
        {
            "table_name": "dim_customer",
            "column_name": "customer_id",
            "column_type": "INT",
            "relationship_type": "source",
            "hop_number": 0,
            "transformation_logic": None,
        },
        {
            "table_name": "fact_orders",
            "column_name": "order_amount",
            "column_type": "DECIMAL",
            "relationship_type": "upstream_joined",
            "hop_number": 1,
            "transformation_logic": "JOIN fact_orders ON dim_customer.id = fact_orders.customer_id",
        },
    ]

    result = _run_async(
        resolve_lineage(
            db=db_session,
            metric_id=sample_metric.id,
            tenant_id=TENANT_ID,
            manual_override=True,
            manual_records=manual_records,
        )
    )

    assert result["lineage_status"] == "manual"
    assert result["lineage_count"] == 2

    records = db_session.query(BiMetricLineage).filter(
        BiMetricLineage.metric_id == sample_metric.id
    ).all()
    assert len(records) == 2

    table_names = {r.table_name for r in records}
    assert "dim_customer" in table_names
    assert "fact_orders" in table_names

    db_session.refresh(sample_metric)
    assert sample_metric.lineage_status == "manual"


# =============================================================================
# Case 4: 重复解析 — 旧血缘被清空，新血缘覆盖
# =============================================================================

@patch(
    "services.metrics_agent.lineage.llm_service.complete_for_semantic",
    new_callable=AsyncMock,
)
def test_resolve_lineage_overwrites_old_records(mock_llm, db_session, sample_metric):
    """重复解析时，旧血缘被完全清空，新血缘覆盖。"""
    # 第一次解析：1 个字段
    mock_llm.return_value = _LLM_RESPONSE_HIGH_CONFIDENCE
    result1 = _run_async(
        resolve_lineage(
            db=db_session,
            metric_id=sample_metric.id,
            tenant_id=TENANT_ID,
        )
    )
    assert result1["lineage_count"] == 1

    # 第二次解析：2 个字段（覆盖）
    mock_llm.return_value = _LLM_RESPONSE_MULTI_FIELDS
    result2 = _run_async(
        resolve_lineage(
            db=db_session,
            metric_id=sample_metric.id,
            tenant_id=TENANT_ID,
        )
    )
    assert result2["lineage_count"] == 2
    assert result2["lineage_status"] == "resolved"

    # DB 中只有 2 条新记录
    records = db_session.query(BiMetricLineage).filter(
        BiMetricLineage.metric_id == sample_metric.id
    ).all()
    assert len(records) == 2

    table_names = {r.table_name for r in records}
    assert "orders" in table_names
    assert "products" in table_names


# =============================================================================
# Case 5: 指标不存在 → 404
# =============================================================================

@patch(
    "services.metrics_agent.lineage.llm_service.complete_for_semantic",
    new_callable=AsyncMock,
)
def test_resolve_lineage_metric_not_found(mock_llm, db_session):
    """指标不存在时应抛出 MC_404。"""
    mock_llm.return_value = _LLM_RESPONSE_HIGH_CONFIDENCE

    with pytest.raises(MulanError) as exc_info:
        _run_async(
            resolve_lineage(
                db=db_session,
                metric_id=uuid.uuid4(),  # 不存在的 ID
                tenant_id=TENANT_ID,
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "MC_404"
    mock_llm.assert_not_called()


# =============================================================================
# Case 6: manual_override=True 但 manual_records 为空 → 400
# =============================================================================

def test_resolve_lineage_manual_override_empty_records(db_session, sample_metric):
    """manual_override=True 但不传 manual_records → 400 MC_400。"""
    with pytest.raises(MulanError) as exc_info:
        _run_async(
            resolve_lineage(
                db=db_session,
                metric_id=sample_metric.id,
                tenant_id=TENANT_ID,
                manual_override=True,
                manual_records=None,  # 为空
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "MC_400"


# =============================================================================
# Case 7: LLM 返回 error → 500
# =============================================================================

@patch(
    "services.metrics_agent.lineage.llm_service.complete_for_semantic",
    new_callable=AsyncMock,
)
def test_resolve_lineage_llm_error_returns_500(mock_llm, db_session, sample_metric):
    """LLM 返回 error 时应抛出 MC_500。"""
    mock_llm.return_value = {"error": "LLM 未配置，请联系管理员"}

    with pytest.raises(MulanError) as exc_info:
        _run_async(
            resolve_lineage(
                db=db_session,
                metric_id=sample_metric.id,
                tenant_id=TENANT_ID,
            )
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code == "MC_500"


# =============================================================================
# Case 8: LLM 返回无效 JSON → 500
# =============================================================================

@patch(
    "services.metrics_agent.lineage.llm_service.complete_for_semantic",
    new_callable=AsyncMock,
)
def test_resolve_lineage_llm_invalid_json_returns_500(mock_llm, db_session, sample_metric):
    """LLM 返回非法 JSON 时应抛出 MC_500。"""
    mock_llm.return_value = {"content": "这不是 JSON，是随机文本。"}

    with pytest.raises(MulanError) as exc_info:
        _run_async(
            resolve_lineage(
                db=db_session,
                metric_id=sample_metric.id,
                tenant_id=TENANT_ID,
            )
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code == "MC_500"
