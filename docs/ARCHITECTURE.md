# Mulan BI Platform — 架构规范

> 最后更新：2026-04-01

## 目录结构

```
mulan-bi-platform/
├── backend/
│   ├── app/                    # FastAPI 应用（路由 + 依赖注入）
│   │   ├── api/                # 路由定义
│   │   ├── core/               # 核心模块（加密、依赖注入、常量）
│   │   └── main.py             # 应用入口
│   └── services/               # 纯业务逻辑层（无 Web 框架依赖）
│       ├── auth/
│       ├── llm/
│       ├── semantic_maintenance/
│       ├── ddl_checker/
│       ├── ddl_generator/
│       ├── datasources/
│       ├── tableau/
│       ├── logs/
│       └── common/
├── frontend/                   # React + TypeScript + Vite
│   ├── src/
│   │   ├── pages/             # 页面组件
│   │   ├── components/         # 公共组件
│   │   ├── context/            # 全局状态（AuthContext）
│   │   └── api/                # 前端 API 调用层
│   └── tests/smoke/            # Playwright 冒烟测试
├── config/
│   └── rules.yaml             # DDL 规范规则
├── data/                       # SQLite 数据文件
├── docs/
│   ├── ARCHITECTURE.md         # 本文档
│   ├── SPEC.md                 # SPEC/Task 模板
│   ├── specs/                  # 各模块 SPEC 文档
│   └── tasks/                  # 各模块 Task 拆解
└── .github/workflows/ci.yml   # GitHub Actions CI
```

## 架构约束（强制）

1. **`backend/services/` = 纯业务逻辑层**
   - 禁止引入 `fastapi`、`uvicorn`、`starlette` 等 Web 框架
   - 禁止引入 `requests`、`httpx` 等 HTTP 客户端（应在 `app/api/` 层做 HTTP 调用）
   - 只处理数据、业务规则、数据库操作

2. **`backend/app/` = FastAPI 路由层**
   - 只做路由定义、参数验证、依赖注入
   - 业务逻辑委托给 `backend/services/`
   - 通过 `sys.path.insert` 将 `backend/services/` 注入 Python 模块搜索路径

3. **禁止反向依赖**
   - `backend/services/` 不得导入 `backend/app/` 中的任何模块
   - `frontend/` 不得直接操作数据库

4. **`frontend/` 独立运行**
   - Vite 开发服务器端口：`3000`（默认）
   - 生产构建输出：`frontend/out/`
   - API 请求通过 Vite proxy (`/api` → `http://localhost:8000`) 转发

## 模块命名约定

| 模块 | 目录 |
|------|------|
| DDL 规范检查 | `backend/services/ddl_checker/` |
| DDL 生成器 | `backend/services/ddl_generator/` |
| Tableau 集成 | `backend/services/tableau/` |
| 语义维护 | `backend/services/semantic_maintenance/` |
| LLM 管理 | `backend/services/llm/` |
| 用户认证 | `backend/services/auth/` |

## API 路由约定

```
/api/auth/...         — 认证相关
/api/users/...         — 用户管理
/api/groups/...       — 用户组
/api/permissions/...  — 权限
/api/ddl/...          — DDL 检查
/api/rules/...        — 规则配置
/api/tableau/...      — Tableau 集成
/api/semantic_maintenance/... — 语义维护
/api/llm/...          — LLM 配置
/api/activity/...     — 操作日志
/api/datasources/...  — 数据源
/api/requirements/... — 需求
```

## 环境变量约定

| 变量 | 说明 | 示例 |
|------|------|------|
| `SESSION_SECRET` | Session 加密密钥 | `secrets.token_hex(32)` |
| `DATASOURCE_ENCRYPTION_KEY` | 数据源密码加密密钥（32 字节） | `secrets.token_urlsafe(32)` |
| `TABLEAU_ENCRYPTION_KEY` | Tableau Token 加密密钥（32 字节） | `secrets.token_urlsafe(32)` |
| `ALLOWED_ORIGINS` | CORS 允许域名（逗号分隔） | `http://localhost:3001` |
| `SECURE_COOKIES` | 生产环境设为 `true` | `false` |

## CI/CD 约定

- **Lint**：`npm run lint`（ESLint，0 warnings 策略）
- **Type Check**：`npm run type-check`（TypeScript）
- **Build**：`npm run build`（Vite production build）
- **Backend Check**：`python3 -m py_compile` + `from app.main import app`
- 所有 job 必须通过才能 merge
