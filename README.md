# Mulan BI Platform

> 数据建模与治理平台 — 面向 BI 团队的数据质量、DDL 规范、Tableau 资产及语义维护工具。

## 包管理器约定

**前端统一使用 npm**（`package-lock.json` 是唯一锁文件，勿混用 yarn）。

## 核心功能

| 模块 | 说明 |
|------|------|
| DDL 规范检查 | MySQL/PostgreSQL/SQLite 数据库扫描，规则可配置 |
| DDL 生成器 | 预置维度表、事实表、ODS、DWD 模板 |
| Tableau 集成 | MCP/REST 双协议支持，资产浏览、工作簿/视图元数据查询 |
| 语义维护 | Tableau 资产语义标注、数据源管理、字段级维护 |
| LLM 配置 | Anthropic/MiniMax 等模型接入，API Key 加密存储 |
| 用户权限 | Session/Cookie 认证，角色+权限组（admin/data_admin/analyst/user） |
| 操作日志 | 完整记录平台操作历史 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React + TypeScript + Vite + Tailwind CSS + React Router v7 |
| 后端 | Python 3.11+ / FastAPI + SQLAlchemy |
| 数据库 | SQLite（本地日志）、MySQL/PostgreSQL（目标数据库） |
| 规范规则 | YAML 配置文件 |
| 测试 | Playwright 冒烟测试 + GitHub Actions CI |

## 快速启动

```bash
# 克隆项目
git clone https://github.com/Forrest219/mulan-bi-platform.git
cd mulan-bi-platform

# 后端依赖
pip install -r backend/requirements.txt

# 环境变量（参考 .env.example）
export SESSION_SECRET=dev-secret-key-change-in-production
export DATASOURCE_ENCRYPTION_KEY=your-32-byte-key
export TABLEAU_ENCRYPTION_KEY=your-32-byte-key

# 启动后端
cd backend && uvicorn app.main:app --reload --port 8000

# 前端（新终端）
cd frontend && npm install
cd frontend && npm run dev
```

访问 http://localhost:3001 ，默认管理员账号：`admin` / `admin123`

## 项目结构

```
mulan-bi-platform/
├── backend/
│   ├── app/                    # FastAPI 应用（路由 + 依赖注入）
│   │   ├── api/               # 路由定义
│   │   ├── core/              # 核心模块（加密、依赖注入、常量）
│   │   └── main.py            # 应用入口
│   └── services/              # 纯业务逻辑层（无 Web 框架依赖）
│       ├── auth/
│       ├── llm/
│       ├── semantic_maintenance/
│       ├── ddl_checker/
│       ├── ddl_generator/
│       ├── datasources/
│       ├── tableau/
│       ├── logs/
│       └── common/
├── frontend/
│   ├── src/
│   │   ├── pages/              # 页面组件
│   │   ├── components/          # 公共组件
│   │   ├── context/            # AuthContext 等全局状态
│   │   └── api/                # 前端 API 调用层
│   └── tests/smoke/            # Playwright 冒烟测试
├── config/
│   └── rules.yaml              # DDL 规范规则
├── docs/
│   ├── ARCHITECTURE.md         # 架构规范
│   ├── SPEC.md                 # SPEC/Task 模板
│   ├── specs/                  # 模块 SPEC 文档
│   └── tasks/                  # 模块 Task 拆解
├── data/                       # SQLite 数据文件
│   ├── users.db
│   └── logs.db
└── .github/workflows/ci.yml    # GitHub Actions CI
```

## 常用命令

```bash
# 后端
cd backend && uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm run dev        # 开发服务器
cd frontend && npm run build     # 生产构建
cd frontend && npm run lint      # ESLint 检查（P0 质量门 + P1 风格门）
cd frontend && npm run type-check # TypeScript 类型检查

# 冒烟测试
cd frontend && npx playwright test
```

## Lint 策略（两层门禁）

| 层级 | 规则 | 级别 | 说明 |
|------|------|------|------|
| P0 质量门 | `no-undef` | error | 未定义变量引用 |
| P0 质量门 | TypeScript 硬错误 | error | `ban-ts-comment` 等 |
| P0 质量门 | `react-hooks/exhaustive-deps` | error | 缺失真实依赖 |
| P1 风格门 | `prefer-const` | warn | 风格提示 |
| P1 风格门 | `no-explicit-any` | warn | 类型安全提示 |
| P1 风格门 | `no-unused-vars` | warn | 未使用变量 |

`--max-warnings 50` 容忍 P1 警告存量，P0 硬错误必定失败。

## 规范规则

`config/rules.yaml` 支持配置：

- 表命名规范、字段命名规范
- 数据类型规范、主键/索引规范
- 注释规范、时间戳字段规范
- 软删除字段规范

## 团队

- 项目负责人：Forrest219
- BI 团队
