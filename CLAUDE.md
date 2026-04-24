# Mulan BI Platform

数据建模与治理平台 — 面向 BI 运维团队的数据质量、DDL 规范、Tableau 资产治理、语义维护工具。

@AGENT_PIPELINE.md
@docs/TESTING.md

---

## 参考文档

| 文档 | 说明 |
|------|------|
| [`AGENT_PIPELINE.md`](AGENT_PIPELINE.md) | Agent 流水线完整规则（角色、阶段、铁规则） |
| [`docs/TESTING.md`](docs/TESTING.md) | 测试规范、CI 分层、tester 检查清单 |
| [`docs/specs/README.md`](docs/specs/README.md) | 技术规格书索引（34 份 spec） |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 系统架构总览 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 19 + TypeScript + Vite + Tailwind CSS + React Router v7 |
| 后端 | FastAPI + SQLAlchemy 2.x + PostgreSQL 16 |
| 数据库 | PostgreSQL 16（JSONB、连接池、Alembic 迁移） |
| 认证 | Session/Cookie (HTTP Only) + PBKDF2-SHA256 密码哈希 |
| 测试 | pytest + Vitest + Playwright |

---

## 修改后必须执行的验证命令

### 改了后端 Python 文件

```bash
cd backend && python3 -m py_compile $(git diff --name-only | grep '\.py$')
cd backend && pytest tests/ -x -q
```

### 改了前端文件

```bash
cd frontend && npm run type-check
cd frontend && npm run lint
cd frontend && npm test -- --run
cd frontend && npm run build    # 改了路由/入口必须跑
```

> DB Model / Alembic 验证命令见 `.claude/rules/alembic.md`

---

## 常用命令

```bash
docker-compose up -d                                          # PostgreSQL + Redis
cd backend && uvicorn app.main:app --reload --port 8000       # 后端
cd frontend && npm run dev                                     # 前端
cd backend && pytest tests/ --cov=services --cov=app           # 后端测试
cd frontend && npm test -- --run                               # 前端测试
```

---

## 认证与 API

- 管理员：`ADMIN_USERNAME` / `ADMIN_PASSWORD` 环境变量
- 四级角色：admin, data_admin, analyst, user
- Session：HTTP Only Cookie，7 天有效期
- 后端：`http://localhost:8000`，前端代理：`/api` → 后端
- 数据库：`DATABASE_URL=postgresql://mulan:mulan@localhost:5432/mulan_bi`

---

## `.claude/rules/` 自动加载规则

以下内容已拆分为独立规则文件，Claude Code 会根据上下文自动加载：

| 文件 | 内容 |
|------|------|
| `product-positioning.md` | 用户画像、Workflow、成功指标、Non-Goals |
| `project-structure.md` | 目录结构与各层约束 |
| `alembic.md` | Alembic 硬性规范 + 表前缀约定 + 迁移验证命令 |
| `gotchas.md` | 技术陷阱 1-6（AuthContext、React.lazy、router、server_default、LLM 降级、中文文案） |
| `no-shortcut-principle.md` | 禁止救急方案 + 核心链路避免 mock |
| `review-constraint.md` | reviewer 操作约束（Change Budget） |
