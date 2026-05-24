# OSI Semantic Model Integration — Design

**Change ID**: `osi-semantic-model-integration`
**Status**: Draft

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      OSI Semantic Model YAML                     │
│              (single source of truth for business semantics)     │
└─────────────────────────┬───────────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              │    osi_parser/        │  ← 新增：YAML 解析层
              │   OSI YAML → Python  │
              └───────────┬───────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   metrics/   │  │ semantic_    │  │llm/nlq_     │
│   service    │  │maintenance/  │  │service      │
│              │  │context       │  │             │
│ bi_metric_def│  │assembler     │  │ Prompt 组装  │
│ ← OSI metric │  │← OSI ai_ctx  │  │← OSI filters│
└──────────────┘  └──────────────┘  └──────────────┘
```

**核心设计原则**：OSI YAML 是唯一写入源，各模块只读不写。双写期 `bi_metric_definitions` 由 metrics service 同步写入，迁移完成后退役。

---

## 2. OSI Parser 模块设计

### 2.1 目录结构

```
backend/services/osi_parser/
├── __init__.py
├── models.py          # OSI YAML → Python dataclass（对应 osi-schema.json）
├── parser.py          # YAML 解析 + schema validation
├── validators.py      # 基于 osi-schema.json 的结构校验
└── dialects.py        # 方言转换（基于 sqlglot）
```

### 2.2 核心模型（models.py）

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class OSIDialectExpression:
    ansi_sql: Optional[str] = None
    snowflake: Optional[str] = None
    databricks: Optional[str] = None
    # ... 其他方言

@dataclass
class OSIFilter:
    expr: str
    dialect: str  # "ansi_sql" / "snowflake" / etc.

@dataclass
class OSIField:
    name: str
    description: Optional[str] = None
    dimension: Optional[dict] = None  # {"dimension_type": "time" / "categorical"}
    expression: Optional[OSIDialectExpression] = None

@dataclass
class OSIDataset:
    name: str
    source: str  # e.g. "sales.public.orders"
    primary_key: list[str] = field(default_factory=list)
    fields: list[OSIField] = field(default_factory=list)

@dataclass
class OSIMetric:
    name: str
    description: Optional[str] = None
    aggregation_method: str  # sum / count / avg / min / max
    expression: OSIDialectExpression
    filters: list[OSIFilter] = field(default_factory=list)
    ai_context: Optional[dict] = None

@dataclass
class OSISemanticModel:
    name: str
    description: Optional[str] = None
    datasets: list[OSIDataset] = field(default_factory=list)
    metrics: list[OSIMetric] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    ai_context: Optional[dict] = None
```

### 2.3 Parser 逻辑（parser.py）

```python
import yaml
from .models import OSISemanticModel
from .validators import OSIValidator

class OSIParser:
    def __init__(self, schema_path: str):
        self.validator = OSIValidator(schema_path)

    def parse(self, yaml_path: str) -> list[OSISemanticModel]:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        # Schema validation
        self.validator.validate(data)

        # YAML → Python objects
        models = []
        for sm in data.get("semantic_model", []):
            models.append(self._parse_semantic_model(sm))
        return models

    def _parse_semantic_model(self, raw: dict) -> OSISemanticModel:
        # 递归解析 datasets / metrics / fields
        ...
```

---

## 3. 各模块接入设计

### 3.1 metrics/service.py — 指标定义源切换

**现状**：从 `bi_metric_definitions` 表读取 metric 定义

**改造后**：
```python
# 双写期：OSI YAML 为主，bi_metric_definitions 同步写入
# 迁移完成后：只读 OSI YAML

class MetricsService:
    def __init__(self, osi_parser: OSIParser):
        self.osi_parser = osi_parser
        self.osi_models = self.osi_parser.parse(
            settings.OSI_YAML_PATH
        )

    def get_metric(self, name: str) -> Optional[OSIMetric]:
        for model in self.osi_models:
            for metric in model.metrics:
                if metric.name == name:
                    return metric
        return None

    def list_metrics(self) -> list[OSIMetric]:
        # 从 OSI 读取，不查数据库
        ...

    def sync_to_db(self):
        # 双写：同步到 bi_metric_definitions（迁移期用）
        ...
```

### 3.2 semantic_maintenance/context_assembler.py — AI 上下文标准化

**现状**：`ai_context` 分散在各处理函数里

**改造后**：
```python
class ContextAssembler:
    def __init__(self, osi_parser: OSIParser):
        self.osi_parser = osi_parser
        self.osi_models = self.osi_parser.parse(
            settings.OSI_YAML_PATH
        )

    def get_ai_context(self, entity_name: str) -> dict:
        """返回标准化 ai_context，供 LLM Prompt 组装使用"""
        for model in self.osi_models:
            if model.name == entity_name:
                return model.ai_context or {}
            for dataset in model.datasets:
                if dataset.name == entity_name:
                    return dataset.ai_context or {}
            for metric in model.metrics:
                if metric.name == entity_name:
                    return metric.ai_context or {}
        return {}

    def get_field_context(self, dataset_name: str, field_name: str) -> dict:
        """返回特定字段的语义上下文（synonyms / description）"""
        ...
```

### 3.3 llm/nlq_service.py — Prompt 注入 OSI 语义

**原则**：NLQService **不直接调用 OSIParser**，只通过 `ContextAssembler`（或 `SemanticContextProvider`）获取语义上下文。

**现状**（需修正）：`nlq_service.py` 直接调 `osi_parser.parse(settings.OSI_YAML_PATH)` 获取 filters

**改造后**：
```python
class NLQService:
    def __init__(self, context_assembler: ContextAssembler):
        self.context_assembler = context_assembler  # NLQ 唯一入口

    def build_prompt(self, user_query: str, semantic_model_name: str) -> str:
        # 通过 ContextAssembler 获取完整语义上下文
        semantic_ctx = self.context_assembler.build_nlq_semantic_context(
            semantic_model_name,
            dialect=settings.default_dialect
        )

        # semantic_ctx 包含：
        #   - instructions: ai_context.instructions
        #   - required_filters: list[OSIFilter]（OSI filters，机器可执行）
        #   - field_context: 各字段的 description / synonyms
        #   - token_budgeted_prompt_blocks

        filters_text = self._format_filters(semantic_ctx.required_filters)
        instructions = semantic_ctx.instructions or ""

        prompt = f"""
        业务规则：
        {instructions}

        强制过滤条件（必须应用于 SQL WHERE）：
        {filters_text}

        用户问题：{user_query}
        """
        return prompt

    def _format_filters(self, filters: list[OSIFilter]) -> str:
        """将 OSI filters 格式化为 Prompt 中的可执行条件"""
        return "\n".join(f"  - {f.expr}  // dialect: {f.dialect}" for f in filters)
```

**关键约束**：
- NLQService **永远不直接调用 OSIParser**
- NLQService **不读** `settings.OSI_YAML_PATH`
- 所有 OSI 相关数据必须经过 `ContextAssembler` 或其等价抽象

---

## 4. OSI YAML 持久化方案

### 4.1 决策结论

**PostgreSQL 作为 production 源**，文件系统降为 seed / import / export / CI 校验。

**原因**：
- Mulan 架构使用 PostgreSQL 16 作为唯一持久化层（见 `ARCHITECTURE.md` §7）
- 生产环境多 Gunicorn/Uvicorn workers + Celery workers 并发，文件系统作为源会有一致性问题
- 容器化部署时 app workers 不应写入部署目录
- RBAC / 审批状态 / 审计日志 / rollback / active-version 选择都是"数据库形状"的问题

**文件系统 + Git 的保留场景**：
- 开发环境的 seed fixture
- YAML import / export 交换格式
- CI schema 校验
- 可选的 GitOps 可见性（commit 后触发 export，不作为运行时源）

### 4.2 数据库设计

```sql
-- bi_osi_semantic_models：OSI 语义模型主表
CREATE TABLE bi_osi_semantic_models (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID,                          -- P1 多租户预留，当前可 NULL
    name            VARCHAR(255) NOT NULL UNIQUE,
    osi_schema_version VARCHAR(20) NOT NULL,      -- e.g. "0.2.0.dev"
    status          VARCHAR(20) NOT NULL DEFAULT 'draft',  -- draft / active / deprecated
    yaml_content    TEXT NOT NULL,                -- 原始 OSI YAML，保持可读性
    parsed_json     JSONB NOT NULL,               -- 解析后的结构化数据，供快速查询
    content_hash    VARCHAR(64) NOT NULL,          -- SHA256，用于变更检测
    active_version_id UUID,                       -- 指向 bi_osi_semantic_model_versions
    validation_status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / valid / invalid
    validation_errors JSONB,                      -- OSI schema 校验错误详情
    created_by      UUID,
    updated_by      UUID,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- bi_osi_semantic_model_versions：不可变版本快照
CREATE TABLE bi_osi_semantic_model_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id        UUID NOT NULL REFERENCES bi_osi_semantic_models(id),
    version_number  INTEGER NOT NULL,
    yaml_content    TEXT NOT NULL,
    parsed_json     JSONB NOT NULL,
    content_hash    VARCHAR(64) NOT NULL,
    change_reason   VARCHAR(500),
    created_by      UUID,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(model_id, version_number)
);
```

### 4.3 Repository 层抽象（P0 必须）

```
osi_parser/           ← 只负责解析，不关心数据来源
osi_repository/       ← 决定数据从 PostgreSQL 还是 file 加载
semantic_context/     ← 暴露 LLM 可消费的语义上下文
```

`OSIParser` 只接受 yaml_content（字符串），不直接读取文件或数据库。

`OSIRepository` 负责：
- 从 PostgreSQL 加载 active 版本
- 提供 YAML seed 导入（初始 bootstrap）
- 版本切换和 rollback

### 4.4 Cache Invalidation（替代热重载）

不再依赖文件系统监听。热重载通过以下机制实现：

```python
class OSI SemanticModelCache:
    def __init__(self, repository: OSIRepository):
        self.repository = repository
        self._cache: dict[str, OSISemanticModel] = {}
        self._version_ids: dict[str, UUID] = {}

    def get(self, name: str) -> Optional[OSISemanticModel]:
        current_vid = self._get_active_version_id(name)
        if self._version_ids.get(name) != current_vid:
            # 版本变化，刷新缓存
            self._version_ids[name] = current_vid
            self._cache[name] = self.repository.load_active(name)
        return self._cache.get(name)

    def invalidate(self, name: str):
        """外部调用：写入新版本后触发"""
        self._version_ids.pop(name, None)
        self._cache.pop(name, None)
```

P1 阶段可增加 API endpoint 触发特定 model 的 cache invalidation。

---

## 5. 过渡期双写策略

### 5.1 核心变更：DB transaction first

**原设计**（错误）：先写 YAML 文件，再同步到 `bi_metric_definitions`

**新设计**（正确）：**DB transaction first**，可选 YAML export

```python
def save_metric(metric: OSIMetric):
    # 1. PostgreSQL OSI store（主写入，事务性）
    new_version = osi_repository.save_version(metric)
    osi_repository.activate_version(metric.name, new_version.id)

    # 2. 同步到 bi_metric_definitions（双写，过渡期）
    legacy_sync.sync_metric_to_db(metric)

    # 3. 可选：commit 后触发 YAML export（GitOps 可见性）
    if settings.OSI_YAML_EXPORT_ENABLED:
        yaml_exporter.export_to_file(metric.name)
```

**关键**：`yaml_content` 的权威来源是 PostgreSQL，不是文件系统。YAML export 是给人类 review 和 CI 校验用的，不是运行时源。

### 5.2 三阶段演进

```
Phase 1（DB 主写，YAML 可选 export）：
  写入：PG 事务 → 可选 YAML export for GitOps
  读取：PostgreSQL OSI store（无 fallback）
  bi_metric_definitions：双写同步（只写 legacy）

Phase 2（OSI 主写，legacy 只读）：
  写入：只写 bi_osi_semantic_models
  读取：只读 bi_osi_semantic_models
  bi_metric_definitions：只读，历史数据

Phase 3（bi_metric_definitions 退役）：
  清理双写代码，完成迁移
```

### 5.3 bi_metric_definitions 迁移（P2）

- 分批迁移脚本（batch size 可配置）
- 迁移后 100% 数据一致性校验
- 回滚预案：保留 `bi_metric_definitions` 只读访问能力

---

## 6. 方言转换层

### 6.1 设计目标

OSI 的 `expression.dialects` 支持多方言，但 Mulan 目前主要消费 ANSI SQL 和 Snowflake 方言。

### 6.2 实现方式

利用已有 `sqlglot`（已引入）做方言转换：

```python
# osi_parser/dialects.py
import sqlglot

class DialectConverter:
    def to_dialect(self, osi_expression: str, target: str) -> str:
        """将 ANSI SQL 表达式转换为目标方言"""
        return sqlglot.transpile(
            osi_expression,
            read="ansi",
            write=target
        )[0]

    def resolve_metric_expr(self, metric: OSIMetric, dialect: str) -> str:
        """解析 metric 的目标方言表达式"""
        if dialect in metric.expression:
            return metric.expression[dialect]
        # Fallback 到 ansi_sql，再转换
        ansi_expr = metric.expression.get("ansi_sql", "")
        return self.to_dialect(ansi_expr, dialect)
```

---

## 7. 配置项

```python
# backend/app/config.py
class Settings(BaseSettings):
    # OSI YAML 文件路径
    osi_yaml_dir: Path = Path("backend/semantic_models")

    # 是否启用热重载（生产关闭）
    osi_watch_changes: bool = False

    # 双写模式
    # "osi_only" | "dual_write" | "legacy_only"
    osi_write_mode: str = "dual_write"

    # 默认 SQL 方言
    default_dialect: str = "ansi_sql"
```

---

## 8. API 兼容性

**无 API 变更**。所有改动在内部完成：
- `metrics/service.py` 对外接口不变
- `semantic_maintenance/context_assembler.py` 是内部组件
- `llm/nlq_service.py` Prompt 组装逻辑内部变更

---

## 9. 测试策略

| 测试类型 | 覆盖范围 |
|---------|---------|
| 单元测试 | `osi_parser/` 解析、校验、方言转换 |
| 集成测试 | YAML 文件解析端到端 |
| NL2SQL 测试 | Prompt 注入 filters 后 SQL 正确性 |
| 回归测试 | 现有 API 行为不变 |

---

## 10. 尚未明确的决策（Open Questions）

1. **热重载策略**：文件变化后是自动重载还是需要手动触发？
2. **多租户支持**：不同租户是否需要独立 OSI YAML？
3. **bi_metric_definitions 迁移批次**：历史数据量大，如何分批迁移？