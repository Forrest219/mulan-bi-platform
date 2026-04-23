# Metrics Agent 架构设计与开发交接书

> 版本：v1.0 | 状态：待 Coder 执行 | 日期：2026-04-21
> 上游 Spec：`docs/specs/30-metrics-agent-spec.md`（v0.2）
> 作者：技术架构 Agent

---

## Part 1：数据库模型设计

### 1.1 前缀选择与理由

所有 Metrics Agent 表使用 `bi_` 前缀，与现有 `bi_data_sources`、`bi_data_classifications` 保持一致——这些表属于核心业务语义层，不属于 AI 推理层（`ai_`）。

Spec 中已给出 5 张表的完整字段定义，以下 SQLAlchemy Model 骨架严格对应，并补充关键关联关系与约束注解。

### 1.2 SQLAlchemy Model 骨架

文件路径：`backend/models/metrics.py`（新建）

```python
"""Metrics Agent — SQLAlchemy 2.x ORM Models"""

import uuid
from datetime import datetime
from typing import Optional, Any

from sqlalchemy import (
    Boolean, Float, ForeignKey, Index, Integer, String, Text,
    Timestamp, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.database import Base  # 复用项目已有 Base


# ---------------------------------------------------------------------------
# bi_metric_definitions（指标定义主表 — Source of Truth）
# ---------------------------------------------------------------------------

class BiMetricDefinition(Base):
    __tablename__ = "bi_metric_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_zh: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # 指标类型：atomic / derived / ratio
    metric_type: Mapped[str] = mapped_column(String(16), nullable=False)
    business_domain: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 计算口径
    formula: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ⚠️ 安全要求：formula_template 渲染必须在 Jinja2 沙箱内执行，禁止动态导入
    formula_template: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # 聚合与结果类型
    # aggregation_type: SUM / AVG / COUNT / COUNT_DISTINCT / MAX / MIN / none
    aggregation_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # result_type: float / integer / percentage / currency
    result_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    precision: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    # 物理表映射
    datasource_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bi_data_sources.id"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    filters: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # 状态字段
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # lineage_status: resolved / unknown / manual
    lineage_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown"
    )
    # sensitivity_level: public / internal / confidential / restricted
    sensitivity_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="public"
    )

    # 审核流
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("auth_users.id"), nullable=False
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("auth_users.id"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # 关联关系
    lineage_records: Mapped[list["BiMetricLineage"]] = relationship(
        back_populates="metric", cascade="all, delete-orphan"
    )
    versions: Mapped[list["BiMetricVersion"]] = relationship(
        back_populates="metric", cascade="all, delete-orphan"
    )
    anomalies: Mapped[list["BiMetricAnomaly"]] = relationship(
        back_populates="metric", cascade="all, delete-orphan"
    )
    consistency_checks: Mapped[list["BiMetricConsistencyCheck"]] = relationship(
        back_populates="metric", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # 核心唯一约束：同租户下指标名不重复（MC_001）
        UniqueConstraint("tenant_id", "name", name="uq_bmd_tenant_name"),
        # 索引（与 Spec §3.6 对应）
        Index("ix_bmd_tenant", "tenant_id", "is_active"),
        Index("ix_bmd_datasource", "datasource_id"),
        Index("ix_bmd_domain", "tenant_id", "business_domain"),
        Index("ix_bmd_sensitivity", "tenant_id", "sensitivity_level"),
        # ix_bmd_name 由 UniqueConstraint 自动创建，无需重复定义
    )


# ---------------------------------------------------------------------------
# bi_metric_lineage（血缘关系表 — Append-Only）
# ---------------------------------------------------------------------------

class BiMetricLineage(Base):
    __tablename__ = "bi_metric_lineage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bi_metric_definitions.id"),
        nullable=False,
    )
    datasource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # relationship_type: source / upstream_joined / upstream_calculated
    relationship_type: Mapped[str] = mapped_column(String(16), nullable=False)
    hop_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transformation_logic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    metric: Mapped["BiMetricDefinition"] = relationship(
        back_populates="lineage_records"
    )

    __table_args__ = (
        Index("ix_bml_metric", "metric_id"),
        Index("ix_bml_tenant", "tenant_id", "metric_id"),
    )


# ---------------------------------------------------------------------------
# bi_metric_versions（版本历史 — Append-Only）
# ---------------------------------------------------------------------------

class BiMetricVersion(Base):
    __tablename__ = "bi_metric_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bi_metric_definitions.id"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # change_type: created / formula_updated / description_updated /
    #              threshold_updated / archived
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # changes 格式：{"before": {...}, "after": {...}}
    changes: Mapped[Any] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[int] = mapped_column(Integer, nullable=False)
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    metric: Mapped["BiMetricDefinition"] = relationship(back_populates="versions")

    __table_args__ = (
        Index("ix_bmv_metric_version", "metric_id", "version"),
        Index("ix_bmv_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# bi_metric_anomalies（指标异常记录）
# ---------------------------------------------------------------------------

class BiMetricAnomaly(Base):
    __tablename__ = "bi_metric_anomalies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bi_metric_definitions.id"),
        nullable=False,
    )
    datasource_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # detection_method: zscore / quantile / trend_deviation / threshold_breach
    detection_method: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_score: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    dimension_context: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(nullable=False)

    # status: detected / investigating / resolved / false_positive
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="detected")
    resolved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    metric: Mapped["BiMetricDefinition"] = relationship(back_populates="anomalies")

    __table_args__ = (
        Index("ix_bma_metric", "metric_id", "detected_at"),
        Index("ix_bma_status", "tenant_id", "status", "detected_at"),
        Index("ix_bma_datasource", "datasource_id", "detected_at"),
    )


# ---------------------------------------------------------------------------
# bi_metric_consistency_checks（一致性校验记录）
# ---------------------------------------------------------------------------

class BiMetricConsistencyCheck(Base):
    __tablename__ = "bi_metric_consistency_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bi_metric_definitions.id"),
        nullable=False,
    )
    # 保留 metric_name 用于跨数据源展示，不做 FK
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)

    datasource_id_a: Mapped[int] = mapped_column(Integer, nullable=False)
    datasource_id_b: Mapped[int] = mapped_column(Integer, nullable=False)
    value_a: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_b: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difference: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difference_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tolerance_pct: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)

    # check_status: pass / warning / fail
    check_status: Mapped[str] = mapped_column(String(16), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    metric: Mapped["BiMetricDefinition"] = relationship(
        back_populates="consistency_checks"
    )

    __table_args__ = (
        Index("ix_bmcc_metric", "metric_id", "checked_at"),
        Index("ix_bmcc_tenant_status", "tenant_id", "check_status", "checked_at"),
    )
```

### 1.3 Alembic 迁移执行思路

迁移文件不在本交接书内生成，执行步骤如下：

1. 在 `backend/models/__init__.py` 中 import `BiMetricDefinition` 等 5 个 Model，确保 Alembic autogenerate 可发现。
2. 运行 `alembic revision --autogenerate -m "add_metrics_agent_tables"` 生成迁移脚本。
3. 检查生成脚本，确认：
   - 5 张表均在 `upgrade()` 中按依赖顺序创建（`bi_metric_definitions` 最先，其余 4 张表引用其 `id`）。
   - `UniqueConstraint("tenant_id", "name")` 已生成为 `UNIQUE` 约束，而非重复索引。
   - JSONB 列类型正确（Alembic 需要 `postgresql.JSONB`，非通用 `JSON`）。
4. 运行 `alembic upgrade head` 完成迁移。
5. 回滚方案：`alembic downgrade -1`，`downgrade()` 函数中按反向顺序 `drop_table`（先删子表，后删 `bi_metric_definitions`）。

---

## Part 2：模块边界与底层复用

### 2.1 Metrics Agent 与 SQL Agent 的边界

| 职责 | Metrics Agent | SQL Agent |
|------|--------------|-----------|
| 指标定义的 CRUD | 全权负责 | 禁止写入 |
| 指标名合法性校验 | 提供 lookup API | 调用 lookup，不自行查表 |
| 生成执行 SQL | 不负责（仅提供 formula） | 负责生成完整 SQL 并执行 |
| 执行目标数据库查询 | **调用** `sql_agent/executor.py` | 同样调用，两者共享执行器 |
| 安全校验（注入防护、超时） | 调用 `sql_agent/security.py` | 自行调用，Metrics 不另起炉灶 |
| 血缘解析 SQL 生成 | 负责（调用 LLM Layer） | 不参与 |
| 异常检测数学计算 | 全权负责 | 不参与 |

**越界红线：**
- Metrics Agent 不得直接查询 `bi_data_sources` 并拼接 SQL 自行执行；必须通过 `get_executor()` 工厂方法。
- SQL Agent 不得直接读取 `bi_metric_definitions` 表；必须通过 `GET /api/metrics/lookup`。

### 2.2 Metrics Agent 调用 sql_agent/executor.py

用途场景：一致性校验时，需向两个数据源各发一条聚合 SQL，取回指标值进行比对。

**调用链（伪代码）：**

```python
# backend/services/metrics_agent/consistency.py

from backend.services.sql_agent.executor import get_executor
from backend.services.sql_agent.security import validate_sql  # 安全白名单校验

async def run_consistency_check(
    metric: BiMetricDefinition,
    datasource_a: dict,   # bi_data_sources.decrypt() 结果
    datasource_b: dict,
    db_type_a: str,
    db_type_b: str,
    timeout_seconds: int = 30,
) -> tuple[float | None, float | None]:
    """
    对两个数据源执行同一指标的聚合查询，返回 (value_a, value_b)。
    """
    # 1. 根据 metric.formula 构造安全 SQL（只允许 SELECT + 聚合）
    sql = _build_metric_sql(metric)          # Metrics Agent 内部函数
    validate_sql(sql)                        # 复用 SQL Agent 安全校验

    # 2. 获取对应方言执行器（复用 SQL Agent 工厂）
    executor_a = get_executor(db_type_a, datasource_a, timeout_seconds)
    executor_b = get_executor(db_type_b, datasource_b, timeout_seconds)

    # 3. 执行并取结果第一行第一列
    rows_a, _ = executor_a.execute(sql)
    rows_b, _ = executor_b.execute(sql)

    value_a = _extract_scalar(rows_a)
    value_b = _extract_scalar(rows_b)
    return value_a, value_b
```

异常检测场景中，Metrics Agent 同样通过 `get_executor()` 向目标数据源拉取历史数据点，然后在 Python 层完成 Z-Score / 分位数计算，不依赖数据库侧统计函数。

### 2.3 可直接复用的现有组件

| 组件 | 路径 | 复用方式 |
|------|------|---------|
| 多方言执行器 | `backend/services/sql_agent/executor.py` | `get_executor()` 工厂直接 import |
| SQL 安全校验 | `backend/services/sql_agent/security.py` | `validate_sql()` 直接调用 |
| LLM Layer | `docs/specs/08-llm-layer-spec.md` | 血缘解析时调用 LLM API，遵循 Spec 08 约定的调用规范 |
| 数据源管理 | `bi_data_sources` 表 + 现有服务 | 通过 `datasource_id` FK 查询，复用现有 `decrypt()` 方法获取连接配置 |
| Auth/RBAC | `backend/app/api/deps.py`（推测路径） | `get_current_user` / `require_role` 依赖注入，与其他模块一致 |
| 错误处理 | `app/core/errors.py` → `MulanError` | 统一使用 `MulanError(error_code, message, http_status)` |

---

## Part 3：接口契约设计

### 3.1 通用约定

- 所有路径前缀：`/api/metrics`
- 认证：Bearer JWT（用户 token）或 `X-Scan-Service-JWT`（服务间 token）
- `tenant_id` 统一从 JWT Payload 解析，不在请求体中透传（内部服务调用例外，见 lookup 接口）
- 分页响应统一格式：`{items, total, page, page_size, pages}`
- 错误响应统一格式：`{error_code, message, detail}`

### 3.2 指标注册接口（优先稳定，Data Agent 强依赖）

#### POST /api/metrics — 创建指标

**角色要求：** `data_admin+`

**请求 Body：**
```json
{
  "name": "gmv",
  "name_zh": "商品交易总额",
  "metric_type": "atomic",
  "business_domain": "commerce",
  "description": "统计周期内所有已完成订单的支付金额之和",
  "formula": "SUM(order_amount)",
  "formula_template": "SUM(order_amount) WHERE status = '{{status}}'",
  "aggregation_type": "SUM",
  "result_type": "float",
  "unit": "元",
  "precision": 2,
  "datasource_id": 1,
  "table_name": "orders",
  "column_name": "order_amount",
  "filters": {"status": "completed"},
  "sensitivity_level": "internal"
}
```

**字段约束：**
- `name`：必填，`^[a-z][a-z0-9_]{1,127}$`（小写字母、数字、下划线）
- `metric_type`：必填，枚举 `atomic | derived | ratio`
- `aggregation_type`：枚举 `SUM | AVG | COUNT | COUNT_DISTINCT | MAX | MIN | none`
- `result_type`：枚举 `float | integer | percentage | currency`
- `sensitivity_level`：枚举 `public | internal | confidential | restricted`，默认 `public`
- `datasource_id`：必填，需存在于 `bi_data_sources`

**响应 201：**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "gmv",
  "metric_type": "atomic",
  "lineage_status": "unknown",
  "is_active": false,
  "created_at": "2026-04-21T10:00:00Z"
}
```

**错误码：**
| 错误码 | HTTP | 触发条件 |
|--------|------|---------|
| MC_001 | 409 | 同 tenant 下 name 重复 |
| MC_403 | 403 | 角色不足 |
| DS_004 | 400 | datasource_id 不存在 |

#### GET /api/metrics — 指标列表

**角色要求：** `analyst+`

**Query 参数：**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页条数，max 100 |
| business_domain | string | - | 精确匹配 |
| metric_type | string | - | 精确匹配 |
| datasource_id | int | - | 精确匹配 |
| is_active | bool | true | 启用状态 |
| sensitivity_level | string | - | 精确匹配 |
| search | string | - | 对 name、name_zh、description 做 ILIKE 模糊搜索 |

**响应 200：** 见 Spec §5.2 `GET /api/metrics`，字段与 Model 对应。

#### GET /api/metrics/{id} — 指标详情

**角色要求：** `analyst+`

响应包含完整字段，见 Spec §5.2。`id` 为 UUID 格式，非法格式返回 422；不存在返回 MC_404 / 404。

#### PUT /api/metrics/{id} — 更新指标

**角色要求：** `data_admin+`

**请求 Body：** 与 POST 相同结构，所有字段可选（PATCH 语义，仅更新传入字段）。

**副作用：**
- 若 `formula` 或 `formula_template` 发生变更，自动将 `lineage_status` 重置为 `unknown`，并写入 `bi_metric_versions`（`change_type=formula_updated`）。
- 若指标处于 `published` 状态，任何字段变更均需重新走审核流（`is_active` 置回 false）。

**错误码：** MC_404 / MC_403 / MC_001（改名冲突）

#### DELETE /api/metrics/{id} — 软删除（下线）

**角色要求：** `admin`

软删除：将 `is_active=false` + `lineage_status` 保持不变。写入 `bi_metric_versions`（`change_type=archived`）。不物理删除行。

**响应 200：**
```json
{"id": "uuid", "is_active": false, "archived_at": "2026-04-21T10:00:00Z"}
```

### 3.3 审核流接口

#### POST /api/metrics/{id}/submit-review

**角色要求：** `data_admin+`

**响应 200：** `{"id": "uuid", "status": "review"}`

**前置条件：** 指标处于 `draft` 状态，否则 400。

#### POST /api/metrics/{id}/approve

**角色要求：** `data_admin+`（不得与创建人相同，建议服务层校验）

**响应 200：** `{"id": "uuid", "reviewed_by": 456, "reviewed_at": "..."}`

#### POST /api/metrics/{id}/reject

**请求 Body：** `{"reason": "公式口径不明确"}`

**响应 200：** `{"id": "uuid", "status": "draft"}`

#### POST /api/metrics/{id}/publish

**角色要求：** `data_admin+`

**前置校验（服务层按序执行）：**
1. `lineage_status` 必须为 `resolved` 或 `manual`（MC_002）
2. `formula_template` 中所有参数需有默认值（MC_003）
3. 上游字段 `sensitivity_level` ≤ 指标 `sensitivity_level`；若违规则自动升级到上游最高级别（MC_004）

**副作用：** `is_active=true`，写 `bi_metric_versions`（`change_type=created`），发射 `metric.published` 事件。

**响应 200：** `{"id": "uuid", "published_at": "..."}`

### 3.4 指标查询接口（内部服务 — 优先稳定）

#### GET /api/metrics/lookup

**认证：** Service JWT（`X-Scan-Service-JWT` Header），不接受普通用户 Token。

**Query 参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| names | string | 是 | 逗号分隔指标名，max 50 个 |
| tenant_id | UUID | 是 | 服务间调用必须指定 |
| datasource_id | int | 否 | 进一步缩小范围 |

**响应 200：**
```json
{
  "metrics": [
    {
      "name": "gmv",
      "name_zh": "商品交易总额",
      "formula": "SUM(order_amount)",
      "formula_template": "SUM(order_amount) WHERE status = '{{status}}'",
      "aggregation_type": "SUM",
      "result_type": "float",
      "unit": "元",
      "precision": 2,
      "filters": {"status": "completed"},
      "sensitivity_level": "internal",
      "datasource_id": 1,
      "table_name": "orders",
      "column_name": "order_amount",
      "lineage_status": "resolved",
      "description": "统计周期内所有已完成订单的支付金额之和"
    }
  ],
  "not_found": ["unknown_metric"]
}
```

**说明：**
- 只返回 `is_active=true` 的指标。
- `not_found` 列表列出请求中未命中的指标名；调用方（SQL Agent）据此判断是否触发 `SQLA_005` 拒绝执行。
- 部分命中时 HTTP 仍返回 200，`not_found` 非空。
- 全部未命中时返回 200，`metrics: []`，`not_found` 包含所有请求名。

**错误码：** MC_403（Service JWT 无效）

### 3.5 版本历史接口

#### GET /api/metrics/{id}/versions

**角色要求：** `analyst+`

**Query 参数：** `page`（默认 1）、`page_size`（默认 20）

**响应 200：**
```json
{
  "items": [
    {
      "id": "uuid",
      "version": 3,
      "change_type": "formula_updated",
      "changes": {"before": {"formula": "..."}, "after": {"formula": "..."}},
      "changed_by": 123,
      "change_reason": "口径调整，去掉退款订单",
      "created_at": "2026-04-20T09:00:00Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

### 3.6 血缘关系接口

#### GET /api/metrics/{id}/lineage

**角色要求：** `analyst+`

**响应 200：**
```json
{
  "metric_id": "uuid",
  "lineage_status": "resolved",
  "records": [
    {
      "id": "uuid",
      "datasource_id": 1,
      "table_name": "orders",
      "column_name": "order_amount",
      "column_type": "DECIMAL",
      "relationship_type": "source",
      "hop_number": 0,
      "transformation_logic": null,
      "created_at": "2026-04-01T08:00:00Z"
    }
  ]
}
```

#### POST /api/metrics/{id}/lineage/resolve

**角色要求：** `data_admin+`

**行为：**
1. 调用 LLM Layer（Spec 08）解析 `formula` 中的字段引用，生成血缘记录。
2. 在 `bi_metric_lineage` 中 upsert 血缘行。
3. 将 `bi_metric_definitions.lineage_status` 更新为 `resolved`。

**请求 Body（可选）：**
```json
{
  "manual_override": false,
  "lineage_records": []
}
```
当 `manual_override=true` 时，跳过 LLM 解析，直接将 `lineage_records` 写入，`lineage_status` 置为 `manual`。

**响应 200：**
```json
{"lineage_count": 3, "lineage_status": "resolved"}
```

**错误码：** MC_429（解析超时 30s）

### 3.7 异常检测接口

#### POST /api/metrics/detect-anomalies — 主动触发检测

**角色要求：** `data_admin+`

**请求 Body：**
```json
{
  "metric_ids": ["uuid1", "uuid2"],
  "detection_method": "zscore",
  "window_days": 30,
  "threshold": 3.0
}
```

**字段约束：**
- `detection_method`：枚举 `zscore | quantile | trend_deviation | threshold_breach`
- `metric_ids` 为空时，对当前 tenant 所有 `is_active=true` 指标执行检测
- `threshold` 默认 3.0（Z-Score），分位数检测时忽略此字段

**响应 200：**
```json
{
  "checked_count": 10,
  "anomaly_count": 2,
  "anomaly_ids": ["uuid_a", "uuid_b"]
}
```

#### GET /api/metrics/{id}/anomalies — 异常历史

**角色要求：** `analyst+`

**Query 参数：** `page`、`page_size`、`status`（枚举过滤）、`detection_method`

**响应 200：** 分页列表，每项字段对应 `bi_metric_anomalies` 完整字段。

#### PATCH /api/metrics/anomalies/{anomaly_id} — 更新异常状态

**角色要求：** `data_admin+`

**请求 Body：**
```json
{
  "status": "resolved",
  "resolution_note": "数据源延迟导致，非真实异常"
}
```

**合法状态流转：** `detected → investigating → resolved | false_positive`

**响应 200：** 更新后的异常记录完整字段。

### 3.8 一致性校验接口

#### POST /api/metrics/consistency-check — 执行校验

**角色要求：** `data_admin+`

**请求 Body：**
```json
{
  "metric_id": "uuid",
  "datasource_id_a": 1,
  "datasource_id_b": 2,
  "tolerance_pct": 5.0
}
```

**行为：**
1. 向两个数据源执行指标聚合查询（通过 `get_executor()`）。
2. 计算差值与差值百分比。
3. 写入 `bi_metric_consistency_checks`。
4. 若 `check_status=fail`，发射 `metric.consistency.failed` 事件。

**响应 200：**
```json
{
  "check_id": "uuid",
  "metric_name": "gmv",
  "value_a": 1000000.0,
  "value_b": 1050000.0,
  "difference": -50000.0,
  "difference_pct": -5.0,
  "check_status": "fail",
  "checked_at": "2026-04-21T10:00:00Z"
}
```

**错误码：** MC_429（查询超时）、MC_005（一致性失败，仍返回 200，仅在 `check_status=fail` 时额外携带 `warning` 字段）

#### GET /api/metrics/consistency-checks — 校验历史

**角色要求：** `analyst+`

**Query 参数：** `page`、`page_size`、`metric_id`、`check_status`

---

## Part 4：开发任务拆分与验收标准

任务按依赖顺序排列，T1 → T5 依次解锁。T1、T2 完成后 Data Agent 可开始集成测试。

---

### T1：数据库迁移与 Model 注册

**范围：** 创建 5 张表的 Model 文件并完成 Alembic 迁移。

**输出产物：**
- `backend/models/metrics.py`（新建，上文 Part 1 骨架）
- `backend/models/__init__.py`（修改，新增 5 个 Model import）
- `backend/alembic/versions/XXXXXX_add_metrics_agent_tables.py`（autogenerate 后人工检查）

**DoD：**
```bash
# 1. 迁移成功执行
alembic upgrade head
# 预期：无报错，exit 0

# 2. 验证表结构
psql $DATABASE_URL -c "\d bi_metric_definitions"
# 预期：输出包含 id(uuid), tenant_id, name, formula, is_active 等字段

# 3. 验证唯一约束
psql $DATABASE_URL -c "\d+ bi_metric_definitions" | grep uq_bmd_tenant_name
# 预期：约束名 uq_bmd_tenant_name 存在

# 4. 验证回滚
alembic downgrade -1
# 预期：无报错，5 张表被删除
alembic upgrade head
# 预期：重新建表成功
```

**并发风险：** 此任务不与其他任务冲突，但必须最先完成。迁移期间不得有其他 alembic 操作并行执行。

---

### T2：指标注册 CRUD + 审核流 API

**范围：** 实现指标的完整 CRUD 与状态机流转，包括 lookup 内部接口。此任务是 Data Agent 集成的最高优先级前置条件。

**输出产物：**
- `backend/services/metrics_agent/__init__.py`（新建目录）
- `backend/services/metrics_agent/registry.py`（新建，CRUD + 状态机逻辑）
- `backend/services/metrics_agent/schemas.py`（新建，Pydantic 入参/出参 Schema）
- `backend/app/api/metrics.py`（新建，FastAPI Router）
- `backend/app/main.py`（修改，注册 metrics router：`app.include_router(metrics_router, prefix="/api/metrics")`）
- `tests/services/metrics_agent/test_registry.py`（新建）

**DoD：**
```bash
# 1. 创建指标
curl -X POST http://localhost:8000/api/metrics \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"gmv","metric_type":"atomic","datasource_id":1,"table_name":"orders","column_name":"order_amount"}'
# 预期：201，返回 id

export METRIC_ID=<上一步返回的 id>

# 2. 重名冲突（MC_001）
curl -X POST http://localhost:8000/api/metrics \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"name":"gmv","metric_type":"atomic","datasource_id":1,"table_name":"orders","column_name":"order_amount"}'
# 预期：409，error_code=MC_001

# 3. 审核流走通
curl -X POST http://localhost:8000/api/metrics/$METRIC_ID/submit-review -H "Authorization: Bearer $ADMIN_TOKEN"
curl -X POST http://localhost:8000/api/metrics/$METRIC_ID/approve -H "Authorization: Bearer $ADMIN_TOKEN"
curl -X POST http://localhost:8000/api/metrics/$METRIC_ID/publish -H "Authorization: Bearer $ADMIN_TOKEN"
# 预期：最后一步因 lineage_status=unknown 返回 400, error_code=MC_002

# 4. lookup 接口（Service JWT）
curl "http://localhost:8000/api/metrics/lookup?names=gmv&tenant_id=$TENANT_ID" \
  -H "X-Scan-Service-JWT: $SERVICE_TOKEN"
# 预期：200，metrics=[] (因 is_active=false，还未发布)

# 5. 单元测试
cd backend && pytest tests/services/metrics_agent/test_registry.py -v
# 预期：全部通过，覆盖率 ≥ 80%
```

---

### T3：血缘解析引擎

**范围：** 实现 `lineage/resolve` 接口，对接 LLM Layer 完成字段级上游溯源，并支持手动 override。

**输出产物：**
- `backend/services/metrics_agent/lineage.py`（新建）
- `tests/services/metrics_agent/test_lineage.py`（新建）

**DoD：**
```bash
# 前置：已有已创建且处于 review/approved 状态的指标

# 1. 自动解析血缘（需 LLM 服务可用）
curl -X POST http://localhost:8000/api/metrics/$METRIC_ID/lineage/resolve \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# 预期：200，lineage_count >= 1，lineage_status=resolved

# 2. 手动 override
curl -X POST http://localhost:8000/api/metrics/$METRIC_ID/lineage/resolve \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"manual_override":true,"lineage_records":[{"datasource_id":1,"table_name":"orders","column_name":"order_amount","relationship_type":"source","hop_number":0}]}'
# 预期：200，lineage_status=manual

# 3. 血缘解析后可发布
curl -X POST http://localhost:8000/api/metrics/$METRIC_ID/publish -H "Authorization: Bearer $ADMIN_TOKEN"
# 预期：200，published_at 非空

# 4. 敏感性级别自动升级（MC_004）
# 先将上游字段 sensitivity_level 设为 restricted，然后发布 sensitivity_level=public 的指标
# 预期：published 成功，但指标 sensitivity_level 被自动升级为 restricted

# 5. 单元测试（mock LLM 响应）
pytest tests/services/metrics_agent/test_lineage.py -v
```

---

### T4：异常检测引擎

**范围：** 实现 Z-Score / 分位数 / 趋势偏离三种检测算法，完成异常写入与状态管理接口。

**输出产物：**
- `backend/services/metrics_agent/anomaly_detector.py`（新建，算法实现）
- `backend/services/metrics_agent/anomaly_service.py`（新建，服务编排）
- `tests/services/metrics_agent/test_anomaly_detector.py`（新建）

**DoD：**
```bash
# 1. Z-Score 检测（构造超出阈值的数据点）
curl -X POST http://localhost:8000/api/metrics/detect-anomalies \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"metric_ids":["'$METRIC_ID'"],"detection_method":"zscore","threshold":3.0}'
# 预期：200，anomaly_count >= 0（取决于测试数据）

# 2. 异常状态流转
curl -X PATCH http://localhost:8000/api/metrics/anomalies/$ANOMALY_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"status":"investigating"}'
curl -X PATCH http://localhost:8000/api/metrics/anomalies/$ANOMALY_ID \
  -d '{"status":"resolved","resolution_note":"测试"}'
# 预期：两步均返回 200，最终 status=resolved

# 3. 非法状态流转（resolved → investigating）
curl -X PATCH http://localhost:8000/api/metrics/anomalies/$ANOMALY_ID \
  -d '{"status":"investigating"}'
# 预期：400，状态不可逆

# 4. 算法单元测试（纯 Python，无需数据库）
pytest tests/services/metrics_agent/test_anomaly_detector.py -v
# 预期：Z-Score、分位数、趋势偏离三个算法各有正负样本覆盖，全部通过
```

---

### T5：一致性校验引擎 + 事件发射

**范围：** 实现跨数据源一致性校验，对接 sql_agent/executor.py，并完成三类事件的发射（metric.published / metric.anomaly.detected / metric.consistency.failed）。

**输出产物：**
- `backend/services/metrics_agent/consistency.py`（新建）
- `backend/services/metrics_agent/events.py`（新建，事件发射封装）
- `tests/services/metrics_agent/test_consistency.py`（新建）

**DoD：**
```bash
# 1. 一致性校验（需两个测试数据源）
curl -X POST http://localhost:8000/api/metrics/consistency-check \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"metric_id":"'$METRIC_ID'","datasource_id_a":1,"datasource_id_b":2,"tolerance_pct":5.0}'
# 预期：200，返回 check_status（pass/warning/fail 取决于测试数据）

# 2. 差值 > tolerance 时 check_status=fail
# （构造两数据源查询结果差值 > 5%）
# 预期：check_status=fail，bi_metric_consistency_checks 有对应记录

# 3. 事件发射验证（通过日志或 mock 消费方）
# 发布指标时：日志中应出现 metric.published 事件 payload
# 检测到异常时：日志中应出现 metric.anomaly.detected 事件 payload

# 4. 超时保护
# 构造慢查询（30s+），触发超时
# 预期：返回 429，error_code=MC_429

# 5. 单元测试（mock executor）
pytest tests/services/metrics_agent/test_consistency.py -v
```

---

## 附：并发修改风险说明

| 文件/模块 | 风险 | 处置方式 |
|----------|------|---------|
| `backend/alembic/versions/` | 多 agent 同时生成迁移脚本会产生冲突 | T1 完成并合并后，其他任务才可开始 alembic 操作 |
| `backend/app/main.py` | T2 需修改此文件注册 router | T2 独占修改，其余任务不得同时改动 main.py |
| `backend/services/sql_agent/executor.py` | Metrics Agent 只读调用，不修改 | 无并发修改风险 |
| `backend/models/metrics.py` | T1 新建后 T2-T5 只读 import | 无冲突风险 |
| `backend/services/metrics_agent/` | T2-T5 各自新建独立文件 | 无冲突风险，目录由 T2 初始化 |
