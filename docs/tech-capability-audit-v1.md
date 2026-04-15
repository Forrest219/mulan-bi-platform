---
title: P4 · Capability Wrapper 审计层设计
aliases:
  - P4 Audit Spec
  - Wrapper 审计
tags:
  - project/mulan-bi
  - type/design-spec
  - phase/v1-mvp
  - owner/governance
status: ready-for-implementation
created: 2026-04-15
spec_version: v0.1
target_executor: MiniMax-M2.7 / Sonnet
related:
  - "[[Mulan - 首页问数 TODO 协作清单]]"
  - "[[Mulan - P3 Embedding 召回能力设计]]"
---

# P4 · Capability Wrapper 审计层设计

> [!abstract] 目标
> 在首页问数链路上**贴上企业级审计骨架**:统一 `trace_id` 贯穿 → 统一审计表 `bi_capability_invocations`(Append-Only)→ 在 `/api/search/query` 入口 + MCP 调用处 + 拒绝路径埋点。
> 这是 Capability Wrapper **Phase 1 安全壳的最后一块**(AuthzPolicy / SensitivityGuard 已由 `nlq_service.py` 现成逻辑提供)。

> [!note] 本 spec 只做"观测 + 审计骨架"
> 不做 RateLimiter / CircuitBreaker / Capability Registry(都是 Phase 1.5)。
> 不改业务逻辑,只加埋点和一张审计表。

---

## 1. 任务分解

### T1 · 新建迁移:`bi_capability_invocations`

新建 `backend/alembic/versions/add_bi_capability_invocations.py`:

```python
"""add bi_capability_invocations for homepage Ask audit (Append-Only)"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "add_bi_capability_invocations"
down_revision = "<填当前 head>"

def upgrade():
    op.create_table(
        "bi_capability_invocations",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("principal_id", sa.Integer, nullable=False, index=True),
        sa.Column("principal_role", sa.String(32), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),       # 本次只有 "query_metric"
        sa.Column("params_jsonb", JSONB, nullable=True),              # 输入参数摘要(脱敏)
        sa.Column("status", sa.String(24), nullable=False),           # allowed | denied | failed | ok
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("mcp_call_id", sa.BigInteger, nullable=True),       # FK 到 tableau_mcp_query_logs 或 nlq 日志
        sa.Column("llm_tokens_in", sa.Integer, nullable=True),
        sa.Column("llm_tokens_out", sa.Integer, nullable=True),
        sa.Column("redacted_fields", JSONB, nullable=True),           # 被敏感度拦截的字段名列表
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
    )
    op.create_index("ix_cap_inv_created_at", "bi_capability_invocations", ["created_at"])
    op.create_index("ix_cap_inv_trace_status", "bi_capability_invocations", ["trace_id", "status"])

def downgrade():
    op.drop_index("ix_cap_inv_trace_status", table_name="bi_capability_invocations")
    op.drop_index("ix_cap_inv_created_at", table_name="bi_capability_invocations")
    op.drop_table("bi_capability_invocations")
```

**强制**:此表 **Append-Only**,代码中**禁止** UPDATE / UPSERT / ON CONFLICT。违反视为架构回退。

---

### T2 · 审计服务 `services/capability/audit.py`

```python
"""
Capability 调用审计(Append-Only)
"""
import logging
import uuid
import time
from contextvars import ContextVar
from typing import Optional, List
from dataclasses import dataclass, field
from sqlalchemy import text
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

_trace_id_var: ContextVar[Optional[str]] = ContextVar("capability_trace_id", default=None)


def new_trace_id() -> str:
    tid = uuid.uuid4().hex[:16]
    _trace_id_var.set(tid)
    return tid


def get_trace_id() -> Optional[str]:
    return _trace_id_var.get()


@dataclass
class InvocationRecord:
    trace_id: str
    principal_id: int
    principal_role: str
    capability: str
    params_jsonb: dict = field(default_factory=dict)
    status: str = "ok"                    # allowed | denied | failed | ok
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    latency_ms: Optional[int] = None
    mcp_call_id: Optional[int] = None
    llm_tokens_in: Optional[int] = None
    llm_tokens_out: Optional[int] = None
    redacted_fields: Optional[List[str]] = None


def write_audit(rec: InvocationRecord) -> None:
    """Append-Only 写入。失败只记日志不抛,避免审计路径阻塞主链路"""
    try:
        db = SessionLocal()
        db.execute(text("""
            INSERT INTO bi_capability_invocations
            (trace_id, principal_id, principal_role, capability, params_jsonb,
             status, error_code, error_detail, latency_ms, mcp_call_id,
             llm_tokens_in, llm_tokens_out, redacted_fields)
            VALUES
            (:trace_id, :principal_id, :principal_role, :capability, CAST(:params_jsonb AS JSONB),
             :status, :error_code, :error_detail, :latency_ms, :mcp_call_id,
             :llm_tokens_in, :llm_tokens_out, CAST(:redacted_fields AS JSONB))
        """), {
            "trace_id": rec.trace_id,
            "principal_id": rec.principal_id,
            "principal_role": rec.principal_role,
            "capability": rec.capability,
            "params_jsonb": _json_dumps(rec.params_jsonb),
            "status": rec.status,
            "error_code": rec.error_code,
            "error_detail": (rec.error_detail or "")[:2000],
            "latency_ms": rec.latency_ms,
            "mcp_call_id": rec.mcp_call_id,
            "llm_tokens_in": rec.llm_tokens_in,
            "llm_tokens_out": rec.llm_tokens_out,
            "redacted_fields": _json_dumps(rec.redacted_fields) if rec.redacted_fields else None,
        })
        db.commit()
        db.close()
    except Exception as e:
        logger.error("审计写入失败 trace_id=%s: %s", rec.trace_id, e)


def _json_dumps(v):
    import json
    return json.dumps(v, ensure_ascii=False, default=str)
```

---

### T3 · 在 `app/api/search.py` 埋点

**改动原则:最小侵入**。仅在入口生成 `trace_id`、结束落审计。不改业务逻辑函数签名。

伪码示意,**执行者需读现文件后精准定位插入点**:

```python
# app/api/search.py  query(...)
from services.capability.audit import new_trace_id, write_audit, InvocationRecord

@router.post("/query")
async def query(body: QueryRequest, db: Session = Depends(get_db)):
    trace_id = new_trace_id()
    user = get_current_user(request=None, db=db)
    _require_role(user, "analyst")

    record = InvocationRecord(
        trace_id=trace_id,
        principal_id=user.get("id") or 0,
        principal_role=user.get("role") or "user",
        capability="query_metric",
        params_jsonb={
            "question_length": len(body.question or ""),
            "datasource_luid": body.datasource_luid,
            "connection_id": body.connection_id,
        },
    )
    t0 = time.perf_counter()
    try:
        # 原有逻辑不动
        result = await _run_query_pipeline(body, user, trace_id)
        record.status = "ok"
        record.latency_ms = int((time.perf_counter() - t0) * 1000)
        # 如果内部能拿到 mcp_call_id / tokens,一并填入
        return result
    except HTTPException as exc:
        record.status = "denied" if exc.status_code in (401, 403) else "failed"
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        record.error_code = detail.get("code")
        record.error_detail = detail.get("message")
        record.latency_ms = int((time.perf_counter() - t0) * 1000)
        raise
    except Exception as exc:
        record.status = "failed"
        record.error_code = "INTERNAL"
        record.error_detail = str(exc)[:1000]
        record.latency_ms = int((time.perf_counter() - t0) * 1000)
        raise
    finally:
        write_audit(record)
```

**埋点要求**:
- [ ] `trace_id` 须通过 contextvars 传播(已在 T2 实现),下游日志打印 `logger.info(..., extra={"trace_id": get_trace_id()})`
- [ ] 所有 `HTTPException` 路径必须有审计记录
- [ ] 敏感度被拦截(`is_datasource_sensitivity_blocked` 返回 True)时,`status="denied"`,`error_code="SENSITIVITY_BLOCK"`,`redacted_fields` 填入被拒字段名(≤ 10 个)
- [ ] 审计写入失败**不得**影响主响应(T2 已按这个原则实现)

---

### T4 · 下游日志串联 trace_id

在 `services/llm/nlq_service.py` 的关键步骤(One-Pass LLM 调用前、execute_query 前)加入:

```python
from services.capability.audit import get_trace_id
logger.info("nlq.one_pass trace=%s question_len=%d", get_trace_id(), len(question))
```

**不要**改函数签名。**不要**把 trace_id 透传为参数——用 contextvars 自动传。

---

### T5 · 自验证测试

`tests/services/capability/test_audit.py`:

```python
def test_audit_append_only(db_session):
    # 尝试对同一 trace_id 重复写入,必须得到两条而非 upsert
    rec1 = InvocationRecord(trace_id="t1", principal_id=1, principal_role="analyst", capability="query_metric", status="ok")
    rec2 = InvocationRecord(trace_id="t1", principal_id=1, principal_role="analyst", capability="query_metric", status="ok")
    write_audit(rec1); write_audit(rec2)
    count = db_session.execute(text("SELECT COUNT(*) FROM bi_capability_invocations WHERE trace_id='t1'")).scalar()
    assert count == 2

def test_audit_failure_does_not_break_main_flow(monkeypatch):
    # 模拟 DB 挂掉,write_audit 不抛
    monkeypatch.setattr("services.capability.audit.SessionLocal", lambda: _FailingSession())
    rec = InvocationRecord(trace_id="t2", principal_id=1, principal_role="analyst", capability="query_metric")
    write_audit(rec)  # 不应抛异常
```

`tests/api/test_search_audit.py`:

```python
async def test_search_query_writes_audit(client, seeded_db):
    resp = await client.post("/api/search/query", json={"question":"Q1 销售额"})
    # 不关心响应,关心审计
    row = db.execute(text("SELECT trace_id, status, capability FROM bi_capability_invocations ORDER BY id DESC LIMIT 1")).first()
    assert row is not None
    assert row.capability == "query_metric"

async def test_sensitivity_denial_audited(client, high_sens_datasource):
    resp = await client.post("/api/search/query", json={"question":"...", "datasource_luid": high_sens_datasource.luid})
    assert resp.status_code in (400, 403)
    row = db.execute(text("SELECT status, error_code FROM bi_capability_invocations ORDER BY id DESC LIMIT 1")).first()
    assert row.status == "denied"
    assert row.error_code in ("NLQ_011", "SENSITIVITY_BLOCK")  # 以现有代码实际抛的为准
```

---

## 2. DoD(MiniMax 自查)

- [ ] `alembic upgrade head` 后 `\d bi_capability_invocations` 展示全部列 + 3 个索引
- [ ] 执行一次成功查询后,`SELECT * FROM bi_capability_invocations WHERE trace_id=?` 有 1 条 `status=ok` 记录
- [ ] 用不存在的 `datasource_luid` 查询,记录 `status=failed`,`error_code` 非空
- [ ] 对 high sensitivity 数据源查询,记录 `status=denied`,`redacted_fields` 非空
- [ ] 模拟 DB 异常(断网或假 session),审计失败但主响应仍返回(测试覆盖)
- [ ] 代码里搜索 `bi_capability_invocations` **没有** `UPDATE` / `UPSERT` / `ON CONFLICT`
- [ ] `ruff check backend/services/capability/ backend/app/api/search.py` 零告警
- [ ] 日志里能看到 `trace_id` 串起来(grep 单个 trace_id 能拎出整个链路)

---

## 3. 碰到以下情况停下来

| 情况 | 为什么 |
|---|---|
| `app/api/search.py` 的主函数已经有自定义 try/except 结构,插入点不明显 | 可能破坏现有错误语义,需对齐 |
| `nlq_service.py` 里找不到 `is_datasource_sensitivity_blocked` 调用点 | 敏感度审计分支写不到 |
| 审计表迁移 revision id 冲突(已有同名) | 改 revision id |
| 审计写入 JSONB 字段格式报错 | 参数 `CAST(... AS JSONB)` 要仔细 |

---

## 4. 未来延伸(不在本 spec)

- P4.1 · `bi_capability_invocations` 90 天自动清理(Celery Beat)
- P4.2 · 审计查询页面(admin 用,`/admin/audit`)
- P4.3 · Rate limiter 接入(现 `check_rate_limit` 迁到本表驱动)
- P4.4 · Capability Registry(`config/capabilities.yaml` + 声明式策略引擎)

统一落到 [[SPEC 20 骨架]]。

---

> [!success] 交付标志
> 前端 AskBar 一次提问 → 数据库里一条审计 → `trace_id` 能把 FastAPI 日志、LLM 调用日志、MCP 调用日志三段串起来。敏感字段拒绝路径也有明确记录。
