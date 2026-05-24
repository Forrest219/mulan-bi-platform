# OSI Semantic Model Integration — Tasks

**Change ID**: `osi-semantic-model-integration`
**Status**: Draft

---

## 批次划分原则

- **P0**：核心链路打通，后续批次独立可验
- **P1**：增强体验，非阻塞
- **P2**：优化打磨，可延后

---

## P0 — 核心链路（第一批次）

### P0.1 OSI Parser 核心实现

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P0.1.1 | 创建 `osi_parser/models.py`，实现 OSI dataclass 模型（对应 osi-schema.json 核心结构） | osi-schema.json | dataclass 可序列化/反序列化 |
| P0.1.2 | 创建 `osi_parser/parser.py`，实现 YAML → Python 对象解析，含基础校验 | P0.1.1 | `OSIParser.parse(yaml_content)` 可用，不读取文件 |
| P0.1.3 | 创建 `osi_parser/dialects.py`，基于 sqlglot 实现 `resolve_metric_expr(dialect)` | P0.1.1 | ansi_sql → snowflake 转换正确 |
| P0.1.4 | 创建 `backend/semantic_models/ecommerce_sales.osi.yaml` 示例文件（seed only，不作为运行时源） | P0.1.2 | 通过 OSI schema 校验 |

### P0.1.5 OSI Repository 层（新增 P0）

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P0.1.5 | 创建 `osi_repository/models.py`（Alembic 迁移 + SQLAlchemy model：`bi_osi_semantic_models` / `bi_osi_semantic_model_versions`） | P0.1.1 | 表结构符合 design.md §4.2 |
| P0.1.6 | 创建 `osi_repository/repository.py`（`OSIRepository`：PG 读写 + YAML seed 导入 + 版本管理） | P0.1.5 | `load_active()` / `save_version()` / `activate_version()` 可用 |
| P0.1.7 | 创建 `osi_semantic_cache.py`（cache invalidation 实现，基于 version_id / updated_at） | P0.1.6 | 缓存按 version 刷新，非文件系统监听 |

### P0.2 metrics/ 接入 OSI

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P0.2.1 | 在 `metrics/service.py` 中引入 `OSIParser`，读取 YAML 而非直接查库（双写期） | P0.1.2 | `get_metric("total_revenue")` 从 YAML 返回 |
| P0.2.2 | 实现 `sync_to_legacy_db()` 双写逻辑，将 OSI metric 同步到 `bi_metric_definitions` | P0.2.1 | DB 记录与 YAML 一致 |
| P0.2.3 | 改造 `list_metrics()` 优先读 OSI，fallback 读 `bi_metric_definitions` | P0.2.1 | 回归测试通过 |

### P0.3 nlq_service/ 注入 OSI filters

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P0.3.1 | 改造 `ContextAssembler`，新增 `build_nlq_semantic_context(model_name, dialect)` 方法，返回 instructions + required_filters + field_context | P0.1.7 | 方法返回结构完整，包含 OSI filters |
| P0.3.2 | 改造 `nlq_service.py`，移除对 `osi_parser.parse()` 的直接调用，改为调用 `context_assembler.build_nlq_semantic_context()` | P0.3.1 | nlq_service 不引用 `settings.OSI_YAML_PATH` |
| P0.3.3 | 添加 NL2SQL 单元测试，验证 `is_returned = false` 通过 ContextAssembler 链路自动注入 | P0.3.2 | 测试通过，无 hardcode |

**关键约束**：P0.3.2 是 blocker——NLQ 对 OSIParser 的直接依赖必须在 P0 就消除。

---

## P1 — 增强与扩展

### P1.1 semantic_maintenance/ 改造

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P1.1.1 | 改造 `context_assembler.py`，从 OSI YAML 读取 `ai_context` | P0.1.2 | `get_ai_context("ecommerce_sales")` 返回标准格式 |
| P1.1.2 | `semantic_maintenance/field_sync.py` 改造为 OSI field 同步 | P0.1.1 | 字段语义从 OSI 读取，不再独立维护 |

### P1.2 热重载机制

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P1.2.1 | 实现 `osi_parser` 文件监听（watchdog），支持热重载 | P0.1.2 | 配置文件变更后 5 秒内自动重载 |
| P1.2.2 | 配置项 `osi_watch_changes` 控制开关 | P1.2.1 | 测试通过 |

### P1.3 校验工具

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P1.3.1 | 复制 `validation/validate.py` 到 `backend/semantic_models/validate.py`，适配 Python 3.10+ | osi-schema.json | 本地 `python validate.py ecommerce_sales.osi.yaml` 通过 |
| P1.3.2 | 集成到 `metrics/service.py` 启动检查（schema 校验失败告警） | P1.3.1 | 服务启动时自动校验 YAML |

---

## P2 — 优化与打磨

### P2.1 双写→OSI Only 迁移

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P2.1.1 | 实现 `bi_metric_definitions` 历史数据迁移脚本（分批） | P1.2.2 | 迁移后数据无丢失 |
| P2.1.2 | 配置项 `osi_write_mode` 切换到 `osi_only` | P2.1.1 | 读写全部走 OSI |
| P2.1.3 | 废弃 `bi_metric_definitions` 写入口，清理双写代码 | P2.1.2 | 代码无死代码 |

### P2.2 多方言增强

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P2.2.1 | 支持 snowflake 方言 `expression.dialects` 切换 | P0.3.1 | 方言切换测试通过 |
| P2.2.2 | 支持 databricks 方言（如果业务需要） | P2.2.1 | 同上 |

### P2.3 Open Questions 待决

| Task | 描述 | 依赖 | 验收标准 |
|------|------|------|---------|
| P2.3.1 | 多租户 OSI YAML 隔离方案 | P1.1.1 | 设计文档输出 |
| P2.3.2 | 热重载后缓存失效策略细化 | P1.2.1 | 设计文档输出 |

---

## 任务依赖图

```
P0.1.1 ──┬── P0.1.2 ──┬── P0.1.3
         │             │
         │             └── P0.1.5 ──┬── P0.1.6 ──┬── P0.1.7 ──┬── P0.3.1
         │                         │            │            │
         │                         │            │            └── P0.3.2 ──┬── P0.3.3 (NLQ 边界修正 blocker)
         │                         │            │
         │                         │            └── P1.1.1 ── P1.1.2
         │                         │
         └── P0.1.4 (seed YAML)
```

**关键路径**：
- `P0.1.5 → P0.1.6 → P0.1.7 → P0.3.1 → P0.3.2` 是 NLQ 边界修正的关键路径
- `P0.3.2` 是 blocker，所有 NLQ 直接调用 OSIParser 的代码必须在 P0.3 完成前消除

---

## 估算（P0 批次）

| Task | 估算 | 说明 |
|------|------|------|
| P0.1.1-1.3 | 0.5d | Parser 核心，结构清晰 |
| P0.1.5-1.7 | 1.5d | Repository 层 + DB model + cache（含 Alembic 迁移） |
| P0.2.x | 0.5d | 已有 `bi_metric_definitions` 接口，改接 OSI repository |
| P0.3.x | 0.5d | ContextAssembler 增强 + NLQ 边界修正 + 单元测试 |
| **P0 合计** | **3-3.5d** | 较原估算增加 1d（新增 repository 层） |

---

## 验收 Checklist

- [ ] `ecommerce_sales.osi.yaml` seed 文件通过 OSI schema 校验（仅作为 seed，不作为运行时源）
- [ ] `OSIParser.parse(yaml_content)` 可用，parser 不读取文件
- [ ] `bi_osi_semantic_models` 和 `bi_osi_semantic_model_versions` Alembic 迁移通过
- [ ] `OSIRepository.load_active()` 从 PostgreSQL 读取 active OSI model
- [ ] `OSIRepository.save_version()` / `activate_version()` 版本管理正常
- [ ] `OSISemanticModelCache.get()` 基于 version_id 刷新缓存（非文件系统监听）
- [ ] `get_metric("total_revenue")` 从 PostgreSQL 返回，`filters` 正确
- [ ] `ContextAssembler.build_nlq_semantic_context()` 返回 instructions + required_filters
- [ ] NL2SQL Prompt 通过 ContextAssembler 获取 filters，无 hardcode
- [ ] **nlq_service.py 不引用 `settings.OSI_YAML_PATH`，不直接调用 OSIParser**
- [ ] 回归测试：`/api/metrics/*` 接口行为不变