# Mulan BI Platform

数据建模与治理平台 — 面向 BI 团队的数据质量、DDL 规范、Tableau 资产治理、语义维护工具。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 19 + TypeScript + Vite + Tailwind CSS + React Router v7 |
| 后端 | FastAPI + SQLAlchemy 2.x + PostgreSQL 16 |
| 数据库 | PostgreSQL 16（JSONB、连接池、Alembic 迁移） |
| 认证 | Session/Cookie (HTTP Only) + PBKDF2-SHA256 密码哈希 |
| 测试 | Playwright (前端冒烟测试) |

## 常用命令

```bash
# 启动 PostgreSQL（Docker）
docker-compose up -d

# 数据库迁移
cd backend && alembic upgrade head

# 后端启动
cd backend && uvicorn app.main:app --reload --port 8000

# 前端启动
cd frontend && npm run dev

# 前端构建
cd frontend && npm run build

# 类型检查
cd frontend && npm run type-check
```

## 项目结构

```
mulan-bi-platform/
├── backend/
│   ├── app/
│   │   ├── api/                    # FastAPI 路由
│   │   │   ├── auth.py             # 登录/登出/注册
│   │   │   ├── tableau.py          # Tableau 资产管理
│   │   │   ├── semantic_maintenance/ # 语义维护 API
│   │   │   └── ...
│   │   ├── core/
│   │   │   ├── database.py         # 中央数据库配置（PG 连接池）
│   │   │   ├── dependencies.py     # FastAPI 依赖注入
│   │   │   ├── crypto.py           # 加密工具
│   │   │   └── constants.py        # 常量
│   │   └── utils/
│   │       └── auth.py             # 共享权限校验工具
│   ├── services/                   # 纯业务逻辑层（不依赖 Web 框架）
│   │   ├── auth/                   # 用户认证
│   │   ├── tableau/                # Tableau 集成
│   │   ├── llm/                    # LLM 能力层
│   │   ├── semantic_maintenance/   # 语义维护
│   │   ├── health_scan/            # 数仓健康检查
│   │   └── ...
│   ├── alembic/                    # 数据库迁移脚本
│   └── alembic.ini
├── frontend/src/
│   ├── pages/                      # 页面组件
│   ├── context/AuthContext.tsx      # 认证状态管理
│   └── components/                 # 公共组件
├── docker-compose.yml              # PostgreSQL 本地开发环境
├── config/rules.yaml               # DDL 规范规则
└── modules/ddl_check_engine/       # DDL 检查引擎模块
```

## 数据库

PostgreSQL 16 — 单库统一管理，表名按模块前缀分类：

| 前缀 | 模块 | 表名示例 |
|------|------|---------|
| `auth_` | 用户认证 | auth_users, auth_user_groups |
| `bi_` | 核心业务 | bi_data_sources, bi_scan_logs, bi_requirements |
| `ai_` | LLM/AI | ai_llm_configs |
| `tableau_` | Tableau | tableau_connections, tableau_assets, tableau_field_semantics |

环境变量：`DATABASE_URL=postgresql://mulan:mulan@localhost:5432/mulan_bi`

## 认证

- 默认管理员通过 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 环境变量配置
- 普通用户需由管理员创建
- Session 存储在 HTTP Only Cookie，有效期 7 天
- 四级角色：admin, data_admin, analyst, user

## API 基础路径

- 本地后端：`http://localhost:8000`
- 前端代理：`/api` → `http://localhost:8000`
