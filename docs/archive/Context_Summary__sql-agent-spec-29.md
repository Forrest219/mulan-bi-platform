# Context Summary — SQL Agent SPEC §29 架构审查

> 审查对象：docs/specs/29-sql-agent-spec.md
> 审查角色：architect
> 日期：2026-04-20

---

## 1. Relevant Files

| 文件 | 关联原因 |
|------|---------|
| `docs/specs/29-sql-agent-spec.md` | 审查目标 |
| `docs/specs/28-data-agent-spec.md` | 上游调度方，HTTP API 调用本模块 |
| `docs/specs/14-nl-to-query-pipeline-spec.md` | NL→Query 上游，本模块负责执行 |
| `docs/specs/03-data-model-overview.md` | bi_data_sources 表结构参考 |
| `backend/app/core/database.py` | SQLAlchemy Base + 连接池配置 |
| `backend/services/datasources/` | bi_data_sources 读取逻辑 |
| `backend/app/api/` | 现有 API 路由约定参考 |

---

## 2. Current Behavior

SQL Agent 模块**尚不存在**，属于全新模块。当前代码库中：
- `services/` 下无 `sql_agent/` 目录
- `app/api/` 下无 `sql_agent.py`
- 无 `sql_agent_query_log` 表

---

## 3. Existing Constraints

1. `backend/services/` 必须为纯业务逻辑层（无 FastAPI/uvicorn 依赖）
2. `backend/app/api/` 只做薄路由，调用 `services/` 层
3. 所有 DB 变更必须通过 Alembic migration
4. 错误码遵循 `01-error-codes-standard.md` 规范（MOD_XXX 前缀）
5. 角色权限：admin/data_admin/analyst/user 四级
6. `bi_data_sources` 连接配置加密存储，共用 `CryptoHelper`

---

## 4. Dependency / Call Chain

```
Data Agent（Spec §28）
  └── HTTP POST /api/sql-agent/query
        └── SQL Agent Service（services/sql_agent/）
              ├── router.py → 加载 bi_data_sources 配置
              ├── security.py → sqlglot AST 校验
              ├── executor.py → 目标数据库执行
              └── formatter.py → JSON 返回

NL-to-Query（Spec §14）
  └── HTTP POST /api/sql-agent/query
        └── 同上

前端（数据预览）
  └── GET /api/sql-agent/datasource/{id}/preview
        └── router.py → DESCRIBE / SHOW TABLES
```

**下游数据源（用户数据，不在本仓库）：**
- StarRocks（OLAP）：连接凭证在 bi_data_sources
- MySQL（OLTP）：连接凭证在 bi_data_sources
- PostgreSQL（平台内部元数据库）

---

## 5. Potential Risks

| # | 风险 | 严重度 | 缓解措施 |
|---|------|--------|---------|
| 1 | sqlglot 对 StarRocks 方言支持不完整（部分语法解析失败） | 中 | P0 上线前用真实 StarRocks SQL 做解析覆盖率测试 |
| 2 | 目标数据库连接失败（网络/认证）导致 FastAPI worker 阻塞 | 高 | 每次查询新建连接，不复用；设置 5s 连接超时 |
| 3 | 恶意用户通过注释绕过后续 AST 解析（如 `SELECT 1; DROP TABLE--`） | 高 | sqlglot 在解析阶段处理注释，危险节点在 AST traversal 时拦截 |
| 4 | 无连接池复用导致 StarRocks/MySQL 连接数快速耗尽 | 中 | 控制并发查询数（未来引入连接池）；当前每次建立新连接，用完即关 |
| 5 | LIMIT 注入对复杂 CTE/子查询可能影响语义 | 低 | 仅在最外层 SELECT 注入 LIMIT（sqlglot 支持），不破坏内层语义 |
