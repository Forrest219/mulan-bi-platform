# 开发交付通用约束

> 适用于所有 SPEC 开发，人类和 AI coder 均强制遵循。违反任意一条 = PR 拒绝。

---

## 后端架构红线

### 1. 禁止 `os.environ` / `os.getenv`

- 正确：`from app.core.config import get_settings; settings.DATASOURCE_ENCRYPTION_KEY`
- 错误：`import os; os.environ["DATASOURCE_ENCRYPTION_KEY"]`
- 例外：仅限 `app/main.py` 或 `app/core/config.py` 读取一次并建模

### 2. services/ 层无 Web 框架依赖

- `services/` 目录不得 import: FastAPI, Starlette, uvicorn, Request, Response
- `services/` 只依赖 SQLAlchemy Core、Pure Python 库
- API 层在 `app/api/` 下，通过 `Depends` 注入 `services/`

### 3. 跨层 import 禁止

- `services/` → `app/api/` **禁止**（反向依赖）
- `app/core/` → `services/` 允许
- `app/api/` → `services/` 允许
- `app/api/` → `app/core/` 允许

### 4. SQL 安全性

- 必须使用 SQLAlchemy Core `text()` + 参数绑定
- 禁止：`f"SELECT * FROM {table}"`（字符串插值）
- 禁止：`cursor.execute(f"SELECT * FROM {input}")`

### 5. Append-Only 表禁止 UPSERT

- `bi_quality_scores`、`bi_events` 等审计表：只允许 INSERT
- 禁止：`ON CONFLICT DO UPDATE` / `merge into`

---

## 前端架构红线

### 6. API 路径不可变

- `src/api/` 下的后端请求路径（`/api/admin/datasources` 等）绝对禁止修改
- React Router 路径（`/dev/ddl-validator`）可以改，API 路径不可改

### 7. 无硬编码 API URL

- 生产 API 地址由 Vite proxy 代理，前端代码不得出现 `http://localhost:8000`

### 8. lazy 加载

- 新页面组件必须使用 `React.lazy` + `Suspense`，禁止直接 import

### 9. AuthContext 依赖边界

- 只能在 `context/` 和 `components/` 下使用
- `pages/` 层通过 `ProtectedRoute` 保护

---

## 验证命令

```bash
# 后端：检查禁止的 import 模式
grep -r "os\.environ\|os\.getenv" backend/services/ && echo "FAIL: os.environ in services/" || echo "PASS"
grep -r "from fastapi\|from starlette" backend/services/ && echo "FAIL: web framework in services/" || echo "PASS"

# 前端：检查硬编码 URL
grep -r "localhost:8000" frontend/src/ && echo "FAIL: hardcoded URL" || echo "PASS"
```
