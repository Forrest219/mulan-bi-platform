"""
Metrics Agent — Service 层测试

使用项目已有 db_session fixture（tests/conftest.py）+ 真实 PostgreSQL test DB。
每个测试后自动 rollback，实现数据隔离。

运行：
    cd /Users/forrest/Projects/mulan-bi-platform/backend
    pytest tests/services/metrics_agent/test_registry.py -v
"""
import os
import uuid

# 环境变量必须在所有 import 之前设置
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from app.core.errors import MulanError
from services.metrics_agent import registry
from services.metrics_agent.schemas import MetricCreate, MetricUpdate


# ---------------------------------------------------------------------------
# 测试专用 fixtures
# ---------------------------------------------------------------------------

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_A = 1   # 创建人
USER_B = 2   # 审核人（不同于创建人）


def _make_create_data(**kwargs) -> MetricCreate:
    """生成默认合法的 MetricCreate 数据。"""
    defaults = {
        "name": f"test_metric_{uuid.uuid4().hex[:8]}",
        "metric_type": "atomic",
        "datasource_id": 1,
        "table_name": "fact_orders",
        "column_name": "amount",
        "sensitivity_level": "public",
    }
    defaults.update(kwargs)
    return MetricCreate(**defaults)


@pytest.fixture()
def valid_datasource(db_session):
    """确保 bi_data_sources 中有 id=1 的数据源（幂等插入）。"""
    from sqlalchemy import text
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
    """确保 auth_users 中有 id=1,2 的用户（幂等插入）。"""
    from sqlalchemy import text
    for uid, uname in [(1, "creator"), (2, "reviewer")]:
        existing = db_session.execute(
            text("SELECT id FROM auth_users WHERE id = :id"), {"id": uid}
        ).first()
        if existing is None:
            db_session.execute(
                text(
                    """
                    INSERT INTO auth_users (id, username, display_name, password_hash, email, role, is_active)
                    VALUES (:id, :uname, :uname, 'hash', :email, 'data_admin', true)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": uid, "uname": uname, "email": f"{uname}@test.local"},
            )
    db_session.flush()


# ---------------------------------------------------------------------------
# Case 1: create_metric 成功
# ---------------------------------------------------------------------------

def test_create_metric_success(db_session, valid_datasource, valid_user):
    data = _make_create_data()
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)

    assert metric.id is not None
    assert metric.name == data.name
    assert metric.tenant_id == TENANT_ID
    assert metric.is_active is False
    assert metric.lineage_status == "unknown"
    assert metric.reviewed_by is None
    assert metric.published_at is None

    # 初始状态应为 draft
    assert registry._get_metric_status(metric) == "draft"


# ---------------------------------------------------------------------------
# Case 2: create_metric 重名 → 409
# ---------------------------------------------------------------------------

def test_create_metric_duplicate_name(db_session, valid_datasource, valid_user):
    shared_name = f"dup_metric_{uuid.uuid4().hex[:8]}"
    data1 = _make_create_data(name=shared_name)
    registry.create_metric(db_session, data1, user_id=USER_A, tenant_id=TENANT_ID)

    data2 = _make_create_data(name=shared_name)
    with pytest.raises(MulanError) as exc_info:
        registry.create_metric(db_session, data2, user_id=USER_A, tenant_id=TENANT_ID)

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "MC_001"


# ---------------------------------------------------------------------------
# Case 3: submit_review → approve → publish 完整流
# ---------------------------------------------------------------------------

def test_full_review_publish_flow(db_session, valid_datasource, valid_user):
    # 创建草稿
    data = _make_create_data()
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    assert registry._get_metric_status(metric) == "draft"

    # 提交审核
    metric = registry.submit_review(db_session, metric.id, user_id=USER_A, tenant_id=TENANT_ID)
    assert registry._get_metric_status(metric) == "pending_review"
    # 哨兵时间标记：reviewed_at = 1970-01-01
    assert registry._is_pending(metric.reviewed_at)

    # 批准（USER_B 审核，不能与 USER_A 相同）
    metric = registry.approve_metric(db_session, metric.id, reviewer_id=USER_B, tenant_id=TENANT_ID)
    assert registry._get_metric_status(metric) == "approved"
    assert metric.reviewed_by == USER_B
    assert metric.reviewed_at is not None

    # 发布前先将 lineage_status 设为 resolved
    metric.lineage_status = "resolved"
    db_session.commit()
    db_session.refresh(metric)

    metric = registry.publish_metric(db_session, metric.id, user_id=USER_B, tenant_id=TENANT_ID)
    assert registry._get_metric_status(metric) == "published"
    assert metric.is_active is True
    assert metric.published_at is not None

    # 验证版本记录写入
    from models.metrics import BiMetricVersion
    versions = db_session.query(BiMetricVersion).filter(BiMetricVersion.metric_id == metric.id).all()
    assert len(versions) >= 1
    assert any(v.change_type == "created" for v in versions)


# ---------------------------------------------------------------------------
# Case 4: draft 直接 publish → 400
# ---------------------------------------------------------------------------

def test_publish_from_draft_fails(db_session, valid_datasource, valid_user):
    data = _make_create_data()
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)

    with pytest.raises(MulanError) as exc_info:
        registry.publish_metric(db_session, metric.id, user_id=USER_A, tenant_id=TENANT_ID)

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "MC_400"


# ---------------------------------------------------------------------------
# Case 5: approve 后 creator 自己 approve → 400
# ---------------------------------------------------------------------------

def test_approve_by_creator_fails(db_session, valid_datasource, valid_user):
    data = _make_create_data()
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    registry.submit_review(db_session, metric.id, user_id=USER_A, tenant_id=TENANT_ID)

    # 创建人自己审批 → 应失败
    with pytest.raises(MulanError) as exc_info:
        registry.approve_metric(db_session, metric.id, reviewer_id=USER_A, tenant_id=TENANT_ID)

    assert exc_info.value.status_code == 400
    assert "相同" in exc_info.value.message


# ---------------------------------------------------------------------------
# Case 6: lookup 返回已发布指标 + not_found 列表
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Case T5: publish_metric 成功后触发 emit_metric_published 事件
# ---------------------------------------------------------------------------

def test_publish_metric_emits_event(db_session, valid_datasource, valid_user):
    """publish_metric 成功后，emit_metric_published 应被调用一次。"""
    from unittest.mock import patch

    data = _make_create_data()
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    registry.submit_review(db_session, metric.id, user_id=USER_A, tenant_id=TENANT_ID)
    registry.approve_metric(db_session, metric.id, reviewer_id=USER_B, tenant_id=TENANT_ID)
    metric.lineage_status = "resolved"
    db_session.commit()
    db_session.refresh(metric)

    # patch registry 模块级别的 emit_metric_published（顶层导入）
    with patch("services.metrics_agent.registry.emit_metric_published") as mock_emit:
        registry.publish_metric(db_session, metric.id, user_id=USER_B, tenant_id=TENANT_ID)

    mock_emit.assert_called_once()
    call_kwargs = mock_emit.call_args.kwargs
    assert call_kwargs.get("metric_id") == metric.id
    assert call_kwargs.get("name") == metric.name
    assert call_kwargs.get("tenant_id") == TENANT_ID


def test_lookup_published_and_not_found(db_session, valid_datasource, valid_user):
    # 创建并发布一个指标
    data = _make_create_data()
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    registry.submit_review(db_session, metric.id, user_id=USER_A, tenant_id=TENANT_ID)
    registry.approve_metric(db_session, metric.id, reviewer_id=USER_B, tenant_id=TENANT_ID)
    metric.lineage_status = "resolved"
    db_session.commit()
    db_session.refresh(metric)
    registry.publish_metric(db_session, metric.id, user_id=USER_B, tenant_id=TENANT_ID)

    published_name = metric.name
    missing_name = "nonexistent_metric_xyz"

    result = registry.lookup_metrics(
        db_session,
        names=[published_name, missing_name],
        tenant_id=TENANT_ID,
    )

    found_names = [m.name for m in result["metrics"]]
    assert published_name in found_names
    assert missing_name in result["not_found"]
    assert missing_name not in found_names


# ---------------------------------------------------------------------------
# Case 7: lookup 负向验证 — 非 published 状态的指标不出现在结果中
# ---------------------------------------------------------------------------

def test_lookup_excludes_non_published_metrics(db_session, valid_datasource, valid_user):
    """draft / pending_review / approved 状态的指标不应出现在 lookup 结果中。"""
    from services.metrics_agent.registry import lookup_metrics, _get_metric_status

    lookup_tenant = uuid.UUID("33333333-3333-3333-3333-333333333333")

    # --- draft 指标：刚创建，未 submit_review ---
    draft_data = _make_create_data(name=f"draft_metric_{uuid.uuid4().hex[:6]}")
    draft_metric = registry.create_metric(db_session, draft_data, user_id=USER_A, tenant_id=lookup_tenant)
    assert _get_metric_status(draft_metric) == "draft"

    # --- pending_review 指标：已 submit_review ---
    pending_data = _make_create_data(name=f"pending_metric_{uuid.uuid4().hex[:6]}")
    pending_metric = registry.create_metric(db_session, pending_data, user_id=USER_A, tenant_id=lookup_tenant)
    pending_metric = registry.submit_review(db_session, pending_metric.id, user_id=USER_A, tenant_id=lookup_tenant)
    assert _get_metric_status(pending_metric) == "pending_review"

    # --- approved 指标：已 approve，但未 publish（published_at=None）---
    approved_data = _make_create_data(name=f"approved_metric_{uuid.uuid4().hex[:6]}")
    approved_metric = registry.create_metric(db_session, approved_data, user_id=USER_A, tenant_id=lookup_tenant)
    registry.submit_review(db_session, approved_metric.id, user_id=USER_A, tenant_id=lookup_tenant)
    approved_metric = registry.approve_metric(db_session, approved_metric.id, reviewer_id=USER_B, tenant_id=lookup_tenant)
    assert _get_metric_status(approved_metric) == "approved"
    assert approved_metric.published_at is None
    assert approved_metric.is_active is False

    # 调用 lookup_metrics，传入三个非 published 指标的名称
    names_to_query = [draft_metric.name, pending_metric.name, approved_metric.name]
    result = lookup_metrics(db_session, names=names_to_query, tenant_id=lookup_tenant)

    # 三个均不应出现在结果中（lookup 只返回 is_active=True 的指标）
    assert result["metrics"] == []
    assert set(result["not_found"]) == set(names_to_query)


# ---------------------------------------------------------------------------
# Case 8: MetricCreate name 格式校验 — ^[a-z][a-z0-9_]{1,127}$
# ---------------------------------------------------------------------------

def test_name_format_rejects_digit_prefix():
    """数字开头 → ValueError"""
    with pytest.raises(ValueError):
        MetricCreate(
            name="123abc",
            metric_type="atomic",
            datasource_id=1,
            table_name="t",
            column_name="c",
        )


def test_name_format_rejects_uppercase():
    """含大写字母 → ValueError"""
    with pytest.raises(ValueError):
        MetricCreate(
            name="GMV_total",
            metric_type="atomic",
            datasource_id=1,
            table_name="t",
            column_name="c",
        )


def test_name_format_rejects_special_chars():
    """含特殊字符 → ValueError"""
    with pytest.raises(ValueError):
        MetricCreate(
            name="metric-name",
            metric_type="atomic",
            datasource_id=1,
            table_name="t",
            column_name="c",
        )


def test_name_format_accepts_valid_name(db_session, valid_datasource, valid_user):
    """合法 name（小写字母开头）应正常创建"""
    data = _make_create_data(name="valid_metric_name_123")
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    assert metric.name == "valid_metric_name_123"


def test_name_too_short():
    """name 长度 < 2 → ValueError"""
    with pytest.raises(ValueError):
        MetricCreate(
            name="a",  # 长度 1，pattern 要求 2-128
            metric_type="atomic",
            datasource_id=1,
            table_name="t",
            column_name="c",
        )


# ---------------------------------------------------------------------------
# Case 9: MetricCreate metric_type 枚举校验
# ---------------------------------------------------------------------------

def test_metric_type_rejects_invalid():
    """无效的 metric_type → ValueError"""
    with pytest.raises(ValueError):
        MetricCreate(
            name="test_metric_type",
            metric_type="invalid_type",
            datasource_id=1,
            table_name="t",
            column_name="c",
        )


def test_metric_type_accepts_atomic(db_session, valid_datasource, valid_user):
    data = _make_create_data(name=f"atomic_{uuid.uuid4().hex[:6]}", metric_type="atomic")
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    assert metric.metric_type == "atomic"


def test_metric_type_accepts_derived(db_session, valid_datasource, valid_user):
    data = _make_create_data(name=f"derived_{uuid.uuid4().hex[:6]}", metric_type="derived")
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    assert metric.metric_type == "derived"


def test_metric_type_accepts_ratio(db_session, valid_datasource, valid_user):
    data = _make_create_data(name=f"ratio_{uuid.uuid4().hex[:6]}", metric_type="ratio")
    metric = registry.create_metric(db_session, data, user_id=USER_A, tenant_id=TENANT_ID)
    assert metric.metric_type == "ratio"
