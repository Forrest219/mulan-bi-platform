# Mulan BI Platform

数据建模与治理平台 — 面向 BI 团队的数据质量、DLL 规范、结构治理工具。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React + TypeScript + Vite + Tailwind CSS + React Router v7 |
| 后端 | FastAPI + SQLAlchemy + SQLite |
| 认证 | Session/Cookie (HTTP Only) + bcrypt 密码哈希 |

## 常用命令

```bash
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
├── backend/app/api/        # FastAPI 路由
│   ├── auth.py             # 登录/登出/注册
│   └── users.py            # 用户管理 API
├── frontend/src/
│   ├── pages/              # 页面组件
│   │   ├── home/           # 首页（Agentic AI 搜索）
│   │   ├── login/          # 登录
│   │   └── register/       # 注册
│   ├── context/AuthContext.tsx  # 认证状态管理
│   └── components/        # 公共组件
├── src/auth/               # 后端认证模块（服务+模型）
├── src/logs/               # 日志模块
├── data/                   # SQLite 数据库
│   ├── users.db            # 用户数据
│   ├── requirements.db     # 需求数据
│   └── logs.db             # 日志数据
└── modules/                # 后端业务模块
```

## 认证

- 默认管理员：`admin` / `admin123`
- 普通用户需由管理员创建
- Session 存储在 HTTP Only Cookie，有效期 7 天
- 登录字段已改为用户名（不再使用邮箱）

## 数据库

SQLite 文件位于 `data/` 目录：
- `users.db` — 用户账户、权限、分组
- `requirements.db` — 需求信息
- `logs.db` — 操作日志

## API 基础路径

- 本地后端：`http://localhost:8000`
- 前端代理：`/api` → `http://localhost:8000`
