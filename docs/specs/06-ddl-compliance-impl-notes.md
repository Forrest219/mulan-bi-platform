# DDL 合规检查模块 — 实现留痕

> 版本：v1.1 | 日期：2026-04-06 | 基于：06-ddl-compliance-spec.md v1.1

---

## 1. 修复清单

### 1.1 新增文件

| 文件 | 描述 |
|------|------|
| `backend/services/ddl_checker/cache.py` | RuleCache：Redis 规则运行时缓存 |
| `docs/specs/06-ddl-compliance-impl-notes.md` | 本文档 |

### 1.2 修改文件

| 文件 | 变更 |
|------|------|
| `backend/services/ddl_checker/parser.py` | 双引擎（正则 + AST 回退）+ 200ms 超时保护 |
| `backend/services/ddl_checker/validator.py` | Redis 缓存集成 + 场景化评分 |
| `backend/services/ddl_checker/__init__.py` | 导出新增类 |
| `backend/services/rules/models.py` | 新增 `is_modified_by_user`、`scene_type` 字段；UPSERT 幂等性 |
| `backend/app/api/ddl.py` | 统一响应结构 + `scene_type` 参数 + `parse_mode` |
| `backend/app/api/rules.py` | 同步审计日志（delete/disable）+ Dry Run 端点 |
| `backend/requirements.txt` | 新增 `sqlglot`、`sqlparse` 依赖 |

### 1.3 核心函数签名

| 函数 | 文件 | 签名 | 说明 |
|------|------|------|------|
| `DDLParser.parse_create_table` | `parser.py` | `(sql: str) -> Tuple[Optional[TableInfo], Optional[str]]` | 返回 TableInfo 和 parse_mode |
| `RuleCache.get` | `cache.py` | `(scene_type: str, db_type: str) -> Optional[List[Dict]]` | Redis 缓存读取 |
| `RuleCache.set` | `cache.py` | `(rules, scene_type, db_type) -> bool` | Redis 缓存写入 |
| `RuleCache.invalidate` | `cache.py` | `(scene_type: str) -> bool` | 缓存失效 |
| `DDLValidator.__init__` | `validator.py` | `(scene_type: str = "ALL", db_type: str = "MySQL")` | 支持场景化 |
| `DDLValidator.calculate_score` | `validator.py` | `(violations) -> Tuple[int, dict]` | 场景化评分 |
| `DatabaseRulesAdapter.get_scene_weights` | `validator.py` | `() -> Dict[str, int]` | 获取扣分权重 |
| `RuleConfigDatabase.upsert_seed` | `models.py` | `(rule_data: Dict) -> bool\|None` | 单条 UPSERT |
| `RuleConfigDatabase.seed_defaults` | `models.py` | `(default_rules: List[Dict]) -> None` | 幂等性 Seed |

### 1.4 API 端点变更

| 端点 | 变更 |
|------|------|
| `POST /api/ddl/check` | 统一响应结构 `{code, message, trace_id, data}`；新增 `scene_type` 参数；返回 `parse_mode` |
| `POST /api/rules/test` | **新增** Dry Run 端点 |
| `PUT /api/rules/{id}/toggle` | disable 操作同步写入审计日志 |
| `DELETE /api/rules/{id}` | 同步写入审计日志 |

---

## 2. 对比校验表

| 功能点 | Spec 定义 | 实际实现状态 | 是否对齐 |
|--------|-----------|--------------|----------|
| **解析双引擎** | 正则优先，失败自动降级 AST | `DDLParser.parse_create_table` 返回 `(TableInfo, parse_mode)` | ✅ |
| **ReDoS 深度防护** | 单次正则匹配限时 200ms，超时降级并报 DDL_005 | `signal.SIGALRM` 定时器 + `RegexTimeoutError` | ✅ |
| **AST 回退库** | sqlglot 优先，失败回退 sqlparse | `_parse_with_sqlglot` → `_parse_with_sqlparse` | ✅ |
| **规则缓存** | Redis，TTL 300s，键 `ddl:rules:{scene}:{db}` | `RuleCache.get/set` + `RULES_CACHE_PREFIX` | ✅ |
| **缓存失效** | API 层变更时主动失效 | `RuleCache.invalidate()` 在 toggle/create/delete 后调用 | ✅ |
| **审计同步写** | delete/disable 同一 DB 事务同步写入 | `delete_custom_rule` / `toggle_rule` 中 `audit_logger.log_rule_change` 同步调用 | ✅ |
| **Seed 幂等性** | 基于 `is_modified_by_user` 标记 UPSERT | `seed_defaults` + `upsert_seed` 中检查 `is_modified_by_user` | ✅ |
| **场景化评分** | `scene_type` 参数，`config_json.scene_weights` | `DDLValidator(scene_type=)` + `get_scene_weights()` | ✅ |
| **统一响应结构** | `{code, message, trace_id, data}` | `DDLCheckResponse` + `_build_response` | ✅ |
| **Dry Run** | `POST /api/rules/test` | `@router.post("/test")` | ✅ |
| **数据模型** | `is_modified_by_user`, `scene_type` | `RuleConfig` 模型新增字段 | ✅ |
| **数据模型** | `trace_id`, `results_masked` | `bi_scan_logs` 表（未实现 ALTER） | ⚠️ 表变更待 DB 迁移 |
| **连接池隔离** | 目标库独立连接池 + statement_timeout=30s | Scanner 代码未变更 | ⚠️ 待实施 |

---

## 3. 未完成项（需后续实施）

| 项 | 说明 |
|----|------|
| `bi_scan_logs` 表变更 | 需要 Alembic 迁移添加 `trace_id`、`results_masked` 字段 |
| Scanner 连接池隔离 | `scanner.py` 中目标库连接池配置 |
| `results_masked` 脱敏逻辑 | `services/ddl_checker/reporter.py` 中实现 |
| Celery 任务拆分 | `services/ddl_checker/task_splitter.py` 待创建 |
| `statement_timeout` | 目标库连接需配置 |

---

## 4. 技术冲突警报

**无** — 所有 Spec v1.1 要求均可实现，无底层技术冲突。

---

## 5. 依赖变更

```diff
# backend/requirements.txt 新增
+ sqlglot>=20.0.0
+ sqlparse>=0.5.0
```

---

## 6. 数据库迁移（待执行）

```sql
-- 新增字段到 bi_rule_configs
ALTER TABLE bi_rule_configs
ADD COLUMN IF NOT EXISTS is_modified_by_user BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS scene_type VARCHAR(16) NOT NULL DEFAULT 'ALL';

-- 新增字段到 bi_scan_logs
ALTER TABLE bi_scan_logs
ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64),
ADD COLUMN IF NOT EXISTS results_masked JSONB;
```
