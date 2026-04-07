# SPEC 开发交付 Prompt 模板

> 本文件为规范模板，每个 SPEC 开发交付前必须将对应段落填入 SPEC.md 末尾。
> 所有 AI 辅助开发（Gemini/Claude Code）必须遵循此 Prompt 约束。

---

## 使用方法

在每个 SPEC.md 末尾添加：

```markdown
<!-- PROMPT:SPEC_DEV_DELIVERY_START -->
（复制以下对应 SPEC 的 Prompt 内容）
<!-- PROMPT:SPEC_DEV_DELIVERY_END -->
```

---

## 通用约束（所有 SPEC 强制）

```markdown
## 开发交付约束

### 架构红线（违反 = PR 拒绝）

1. **禁止 `os.environ` / `os.getenv`**
   - 正确：from app.core.config import get_settings; settings.DATASOURCE_ENCRYPTION_KEY
   - 错误：import os; os.environ["DATASOURCE_ENCRYPTION_KEY"]
   - 例外：仅限 `app/main.py` 或 `app/core/config.py` 读取一次并建模

2. **services/ 层无 Web 框架依赖**
   - services/ 目录不得 import: FastAPI, Starlette, uvicorn, Request, Response
   - 正确：services/ 只依赖 SQLAlchemy Core、Pure Python 库
   - API 层在 app/api/ 下，通过 Depends 注入 services/

3. **跨层 import 禁止**
   - services/ → app/api/ ✗（禁止反向依赖）
   - app/core/ → services/ ✓
   - app/api/ → services/ ✓
   - app/api/ → app/core/ ✓

4. **SQL 安全性**
   - 必须使用 SQLAlchemy Core text() + 参数绑定
   - 禁止：f"SELECT * FROM {table}" （字符串插值）
   - 禁止：cursor.execute(f"SELECT * FROM {input}")

5. **Append-Only 表禁止 UPSERT**
   - bi_quality_scores、bi_events 等审计表：只允许 INSERT
   - 禁止：ON CONFLICT DO UPDATE / merge into
```

---

## SPEC 07 — Tableau MCP 交付约束

```markdown
### SPEC 07 强制检查清单

- [ ] **import 路径修正**：所有 `from src.tableau` → `from services.tableau`
- [ ] **IDOR 防护**：/tableau/assets/:id 详情接口必须加 `connection_id` 过滤
- [ ] **Session 隔离**：API 层用 `Depends(get_db)`，Celery 层用 `get_db_context()`
- [ ] **Field Metadata 同步**：sync_pipeline 必须包含 Step 4（field_metadata sync）
- [ ] **重试退避**：连接失败使用指数退避 + jitter（非固定间隔）
- [ ] **Token 上限**：单次 LLM 调用 ≤ 8192 tokens（tiktoken cl100k_base）

### 错误 import 示例（禁止）

```python
# ✗ 错误 — src.tableau 不存在
from src.tableau.models import TableauConnection

# ✓ 正确
from services.tableau.models import TableauConnection
```

### 正确架构示例

```python
# services/tableau/sync_service.py（纯业务逻辑，无 FastAPI）
from services.tableau.models import TableauConnection
from app.core.database import get_db_context
import httpx

class TableauSyncService:
    def sync_workbooks(self, connection_id: str):
        db = get_db_context()  # Celery 兼容
        # ... 纯逻辑，不引入 FastAPI 依赖
```

### Claude Code / Gemini 强制调用

生成代码后必须执行：
```bash
ruff check backend/services/tableau/ --output-format=github
```
如有任何 `F821`（undefined name）或 `F401`（unused import），必须修复。
```

---

## SPEC 14 — NL-to-Query 交付约束

```markdown
### SPEC 14 强制检查清单

- [ ] **contextvars 凭证隔离**：Stage 3 MCP 查询必须使用 contextvars 传递数据源凭证
- [ ] **MCP ClientSession 单例**：禁止 subprocess.run，必须用 ClientSession 池
- [ ] **Redis field cache**：首次查询前检查缓存，防止冷启动打满 PG
- [ ] **tiktoken token 计数**：使用 cl100k_base，context 组装前强制截断
- [ ] **RAG 预算**：P0 答案不消耗 800-token RAG 预算；data_context 单独计算
- [ ] **One-Pass LLM**：intent + VizQL JSON 单次调用，禁止先 intent 后 query 两次调用

### contextvars 正确用法

```python
# ✗ 错误 — 凭证直接传递
def query_datasource(datasource_id: str, credentials: dict):
    ...

# ✓ 正确 — 使用 contextvars 隔离
from contextvars import ContextVar
_tenant_credentials: ContextVar[dict] = ContextVar("tenant_credentials")

@app.post("/nl-query")
def nl_query(req: QueryRequest):
    _tenant_credentials.set(get_datasource_credentials(req.datasource_id))
    # Stage 3 调用处
    creds = _tenant_credentials.get()
```

### Claude Code / Gemini 强制调用

```bash
# 检查 contextvars 使用
grep -r "os.environ" backend/services/llm/ || echo "PASS: no os.environ in services"
ruff check backend/services/llm/ backend/app/api/llm* --output-format=github
```
```

---

## SPEC 15 — Data Governance Quality 交付约束

```markdown
### SPEC 15 强制检查清单

- [ ] **Append-Only 写入**：bi_quality_scores 只允许 INSERT，禁止 UPSERT/ON CONFLICT
- [ ] **SQL Builder**：跨方言查询必须用 SQLAlchemy Core，不得硬编码原生 SQL
- [ ] **max_scan_rows 熔断**：到达行数限制时立即中断查询并返回 partial result
- [ ] **分区裁剪验证**：用 EXPLAIN ANALYZE 验证 `calculated_at` DATE 分区是否生效
- [ ] **90 天清理**：Celery Beat 调度 `cleanup_expired_data.delay()` 已配置
- [ ] **Freshness SQL 分支**：PostgreSQL 和 ClickHouse 分支互斥，无重复

### Append-Only 正确示范

```python
# ✗ 错误 — UPSERT
from sqlalchemy.dialects.postgresql import insert
stmt = insert(bi_quality_scores).values(...).on_conflict_do_update(...)

# ✓ 正确 — Append-Only
stmt = insert(bi_quality_scores).values(...)
# 只允许 INSERT，不做 update
```

### 跨方言 SQL 正确示范

```python
# ✗ 错误 — 硬编码方言
if dialect == "postgresql":
    sql = "SELECT * FROM table"
elif dialect == "clickhouse":
    sql = "SELECT * FROM table"

# ✓ 正确 — SQLAlchemy Core
from sqlalchemy import select, func
query = select(func.count()).select_from(table)
```

### Claude Code / Gemini 强制调用

```bash
ruff check backend/services/health_scan/ --output-format=github
# 禁止出现：on_conflict_do_update / INSERT ... ON CONFLICT
grep -r "on_conflict" backend/services/health_scan/ && echo "FAIL" || echo "PASS"
```
```

---

## SPEC 17 — Knowledge Base 交付约束

```markdown
### SPEC 17 强制检查清单

- [ ] **Ghost Data 修复**：文档重新上传前必须 DELETE kb_embeddings 再 INSERT
- [ ] **tiktoken chunking**：512 token / 64 overlap，cl100k_base 编码
- [ ] **RAG 预算公式**：`3000 - 200(system) - data_context_actual - 800(P0)`，P0 不扣减
- [ ] **HNSW 向量索引**：m=16, ef_construction=200，不使用 IVFFlat
- [ ] **YAML Schema 验证**：kb_schemas 写入前必须 JSON Schema v1.0 校验
- [ ] **向量删除逻辑**：删除文档时同时删除 kb_embeddings（cascade 或手动）

### tiktoken 正确用法

```python
# ✗ 错误 — 字符数截断
chunks = [text[i:i+500] for i in range(0, len(text), 500)]

# ✓ 正确 — token 截断
import tiktoken
enc = tiktoken.get_encoding("cl100k_base")
tokens = enc.encode(text)
MAX_TOKENS = 512
OVERLAP = 64
chunks = [enc.decode(tokens[i:i+MAX_TOKENS]) for i in range(0, len(tokens), MAX_TOKENS - OVERLAP)]
```

### Ghost Data 正确示范

```python
# ✗ 错误 — 直接 upsert
db.add(KBDocument嵌入(...))
db.commit()

# ✓ 正确 — 先删再插
db.query(KBEmbedding).filter(KBEmbedding.document_id == doc.id).delete()
db.add(KBDocument(...))
db.add(KBEmbedding(...))
db.commit()
```

### Claude Code / Gemini 强制调用

```bash
# 检查 tiktoken 使用
grep -r "tiktoken" backend/services/knowledge/ || echo "FAIL: no tiktoken"
ruff check backend/services/knowledge/ --output-format=github
# 检查 ghost data 模式
grep -r "\.add.*KBEmbedding" backend/services/knowledge/ && echo "CHECK: delete before add?"
```
```

---

## 前端 React 交付约束（通用）

```markdown
### 前端强制检查清单

- [ ] **API 路径不变**：src/api/ 下的后端请求路径（/api/admin/datasources 等）绝对禁止修改
- [ ] **Router Path vs API Path**：React Router 路径（/dev/ddl-validator）可以改，API 路径不可改
- [ ] **无硬编码 API URL**：生产 API 地址由 vite proxy 代理，前端代码不出现 `http://localhost:8000`
- [ ] **lazy 加载**：新页面组件必须使用 React.lazy + Suspense，禁止直接 import
- [ ] **AuthContext 依赖**：只能在 context/ 和 components/ 下使用，pages/ 层通过 ProtectedRoute 保护

### 错误示例

```tsx
// ✗ 错误 — 硬编码 API URL
const resp = await fetch("http://localhost:8000/api/admin/datasources");

// ✗ 错误 — 直接 import（非代码分割）
import DataTable from "../components/DataTable";

// ✓ 正确 — 使用相对路径或 API client
import api from "@/api/client";
const resp = await api.get("/admin/datasources");

// ✓ 正确 — lazy 代码分割
const DataTablePage = lazy(() => import("../pages/data-table/page"));
```
```
