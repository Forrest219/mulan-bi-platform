# 项目结构与目录约束

```
mulan-bi-platform/
├── backend/app/api/         # FastAPI 路由层
│                            #   职责：HTTP 请求/响应、参数校验、权限检查
│                            #   约束：禁止在此写业务逻辑，调用 services/ 层
│
├── backend/app/core/        # 基础设施（DB、依赖注入、加密、常量）
│                            #   约束：不得引入业务逻辑；改动须评估全局影响
│
├── backend/services/        # 纯业务逻辑层（不依赖 Web 框架）
│                            #   职责：所有核心计算、外部调用、数据持久化
│                            #   约束：不得直接 import FastAPI/Request 对象
│
├── backend/alembic/         # 数据库迁移脚本（高风险）
│                            #   约束：见 .claude/rules/alembic.md
│
├── frontend/src/pages/      # 页面组件（路由级别）
│                            #   约束：只做布局组合，业务逻辑下沉到 hooks/
│
├── frontend/src/components/ # 公共 UI 组件
│                            #   约束：无业务状态，props 驱动，可单独测试
│
├── frontend/src/context/    # 全局状态（Auth、Scope 等）
│                            #   约束：useCallback/useRef 避免循环依赖，改前先读注释
│
├── docs/                    # PRD、Spec、Tech doc 权威目录（单一来源）
│                            #   约束：所有设计决策必须落地此处，不得散落根目录
│
└── modules/ddl_check_engine/ # DDL 检查引擎（独立模块）
                             #   约束：不得依赖 backend/ 内部模块，保持独立可测试
```

> 根目录只放协作总纲 + 构建入口。阶段产出物完成后归档至 `docs/archive/`。
