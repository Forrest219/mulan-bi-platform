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

- OpenSpec 变更入口：[`openspec/changes/`](openspec/changes/)（需求/行为/API/数据模型/UI/Agent 流程变更必须先建 change）
- Agent 流水线：[`AGENT_PIPELINE.md`](AGENT_PIPELINE.md)
- 测试规范：[`docs/TESTING.md`](docs/TESTING.md)
- 架构约束：[`.claude/rules/`](.claude/rules/)
- Spec 索引：[`docs/specs/README.md`](docs/specs/README.md)

### OpenSpec P0 门控

以下变更必须先创建 OpenSpec change，再进入 PRD/SPEC/实现阶段：

- 需求、用户可见行为、API 契约、数据模型、权限/角色、UI 交互、Agent 流程
- 跨模块架构调整、核心链路降级/兜底策略、长期规格新增或修改

最小制品：

```text
openspec/changes/<change-id>/proposal.md
openspec/changes/<change-id>/tasks.md
```

复杂设计另加：

```text
openspec/changes/<change-id>/design.md
```

目录职责：`openspec/changes/` 管理活跃变更生命周期；`docs/specs/` 保留为长期技术规格和索引。
