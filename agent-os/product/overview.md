mission: |
  数据建模与治理平台 — 让 BI 运维团队能高效管理数据质量、DDL 规范、
  Tableau 资产健康和语义维护。

stage: v0.x (internal dogfood)

target_users:
  - 数据工程师: DDL 规范审查、数据源管理、健康扫描
  - BI 运维人员: Tableau 资产巡检、语义治理、健康评分监控
  - 数据管理员: LLM 配置、用户权限管理、规则配置

non_goals:
  - ETL 数据集成
  - BI 可视化本身
  - 多租户 SaaS

tech_stack:
  frontend: React 19 + TypeScript + Vite + Tailwind CSS
  backend: FastAPI + PostgreSQL 16 + SQLAlchemy 2.x
  auth: Session cookie + PBKDF2-SHA256
  llm: configurable via ai_llm_configs table (multi-provider, purpose routing)
  mcp: MCP server integration for Tableau + StarRocks

roadmap_ref: docs/specs/README.md
