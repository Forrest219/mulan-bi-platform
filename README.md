# Mulan BI Platform

数据建模与治理平台 — 面向 BI 运维团队的数据质量、DDL 规范、Tableau 资产治理、语义维护工具。

当前阶段：v0.x，内部 dogfooding。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 19 + TypeScript + Vite + Tailwind CSS + React Router v7 |
| 后端 | Python ≥ 3.10 + FastAPI + SQLAlchemy 2.x + PostgreSQL 16 |
| 认证 | Session/Cookie (HTTP Only) + PBKDF2-SHA256 |
| 测试 | pytest + Vitest + Playwright |
| MCP  | Tableau + StarRocks（通过 MCP Server 集成） |

## 快速启动

```bash
# 启动数据库
docker-compose up -d

# 后端
cd backend && uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm run dev
```

数据库迁移：

```bash
cd backend && alembic upgrade head
```

## 开发规范

- Agent 流水线：[`AGENT_PIPELINE.md`](AGENT_PIPELINE.md)
- 测试规范：[`docs/TESTING.md`](docs/TESTING.md)
- 架构约束：[`.claude/rules/`](.claude/rules/)
- Spec 索引：[`docs/specs/README.md`](docs/specs/README.md)
