# Mulan BI Platform — 架构规范

> 最后更新：2026-04-03

---

## §1 目录结构

```
mulan-bi-platform/
├── backend/
│   ├── app/                    # FastAPI 应用（路由 + 依赖注入）
│   │   ├── api/                # 路由定义
│   │   │   └── semantic_maintenance/  # 语义维护子路由（5 个文件）
│   │   ├── core/               # 核心模块（加密、依赖注入、常量）
│   │   ├── utils/              # 共享权限校验工具
│   │   └── main.py             # 应用入口
│   └── services/               # 纯业务逻辑层（无 Web 框架依赖）
│       ├── auth/               # 用户认证 + RBAC
│       ├── llm/                # LLM 能力层（双 Provider）
│       ├── semantic_maintenance/ # 语义治理全生命周期
│       ├── ddl_checker/        # DDL 合规检查
│       ├── ddl_generator/      # DDL 生成器
│       ├── datasources/        # 数据源 CRUD + 加密
│       ├── tableau/            # Tableau TSC/REST 集成
│       ├── health_scan/        # 数仓健康扫描
│       ├── logs/               # 操作日志 + 扫描日志
│       ├── requirements/       # 需求管理
│       ├── rules/              # DDL 规则配置
│       ├── tasks/              # Celery 异步任务
│       └── common/             # 共享工具（加密等）
├── frontend/                   # React 19 + TypeScript + Vite
│   ├── src/
│   │   ├── pages/              # 页面组件（按路由组织）
│   │   ├── components/         # 公共 UI 组件
│   │   ├── context/            # 全局状态（AuthContext）
│   │   └── api/                # 前端 API 调用层
│   └── tests/smoke/            # Playwright 冒烟测试
├── config/
│   ├── rules.yaml              # DDL 规范规则
│   ├── dev/.env.dev            # 开发环境配置
│   └── prod/.env.prod          # 生产环境配置模板
├── modules/
│   └── ddl_check_engine/       # 独立 DDL 检查引擎包
├── docs/
│   ├── ARCHITECTURE.md         # 本文档
│   ├── specs/                  # 技术规格书（20 份）
│   ├── prds/                   # 产品需求文档
│   └── tech/                   # 技术方案文档
├── docker-compose.yml          # PostgreSQL 16 + Redis 7（本地开发）
└── .github/workflows/ci.yml   # GitHub Actions CI
```

---

## §2 架构约束（强制）

1. **`backend/services/` = 纯业务逻辑层**
   - 禁止引入 `fastapi`、`uvicorn`、`starlette` 等 Web 框架
   - 只处理数据、业务规则、数据库操作
   - 例外：`publish_service.py` 需 `requests` 调用 Tableau REST API

2. **`backend/app/` = FastAPI 路由层**
   - 只做路由定义、参数验证、依赖注入
   - 业务逻辑委托给 `backend/services/`
   - 通过 `sys.path.insert` 将 `backend/services/` 注入 Python 模块搜索路径

3. **禁止反向依赖**
   - `backend/services/` 不得导入 `backend/app/` 中的任何模块
   - `frontend/` 不得直接操作数据库

4. **`frontend/` 独立运行**
   - Vite 开发服务器端口：`5173`（默认）
   - 生产构建输出：`frontend/out/`
   - API 请求通过 Vite proxy (`/api` → `http://localhost:8000`) 转发

---

## §3 模块命名与路由约定

| 模块 | 服务目录 | API 前缀 | 端点数 |
|------|---------|----------|--------|
| 用户认证 | `services/auth/` | `/api/auth` | 5 |
| 用户管理 | `services/auth/` | `/api/users` | ~4 |
| 用户组 | `services/auth/` | `/api/groups` | ~4 |
| 权限配置 | `services/auth/` | `/api/permissions` | ~3 |
| 数据源管理 | `services/datasources/` | `/api/datasources` | 6 |
| DDL 检查 | `services/ddl_checker/` | `/api/ddl` | ~4 |
| 规则配置 | `services/rules/` | `/api/rules` | ~7 |
| Tableau 集成 | `services/tableau/` | `/api/tableau` | 18 |
| 语义维护 | `services/semantic_maintenance/` | `/api/semantic-maintenance` | ~20 |
| LLM 管理 | `services/llm/` | `/api/llm` | 5 |
| 健康扫描 | `services/health_scan/` | `/api/governance/health` | 6 |
| 任务管理 | `services/tasks/` | `/api/tasks` | ~2 |
| 操作日志 | `services/logs/` | `/api/activity` | ~2 |
| 日志 | `services/logs/` | `/api/logs` | ~3 |
| 需求管理 | `services/requirements/` | `/api/requirements` | ~5 |
| **合计** | | | **~94** |

详见 [02-api-conventions.md](specs/02-api-conventions.md)。

---

## §4 跨模块依赖图

```mermaid
graph TB
    subgraph 基础层
        AUTH[Auth/RBAC<br/>用户认证]
        DS[DataSources<br/>数据源管理]
        LLM[LLM Layer<br/>AI 能力层]
    end

    subgraph 核心业务层
        TAB[Tableau MCP<br/>资产管理]
        SM[Semantic<br/>语义治理]
        DDL[DDL Check<br/>合规检查]
        HS[Health Scan<br/>数仓健康]
    end

    subgraph 集成层
        SLI[Semantic↔LLM<br/>集成协议]
        NLQ[NL-to-Query<br/>自然语言查询]
        GOV[Data Governance<br/>数据质量]
    end

    subgraph 基础设施
        PG[(PostgreSQL 16)]
        REDIS[(Redis 7)]
        CELERY[Celery Worker]
    end

    %% 基础层 → 全局
    AUTH -->|守卫所有端点| TAB
    AUTH -->|守卫所有端点| SM
    AUTH -->|守卫所有端点| DDL
    AUTH -->|守卫所有端点| HS
    AUTH -->|守卫所有端点| LLM

    %% 数据源 → 健康扫描
    DS -->|提供连接凭证| HS

    %% Tableau → 语义
    TAB -->|同步字段元数据| SM
    TAB -->|资产信息| SLI

    %% LLM → 多消费方
    LLM -->|AI 生成语义| SM
    LLM -->|资产摘要/解读| TAB
    LLM -->|NL→VizQL| NLQ

    %% 语义 → LLM 集成
    SM -->|语义上下文| SLI
    LLM -->|生成能力| SLI
    SLI -->|查询构建| NLQ

    %% Celery
    CELERY -->|定时同步| TAB
    CELERY -->|异步扫描| HS
    REDIS -->|消息队列| CELERY

    %% 数据库
    AUTH --> PG
    DS --> PG
    TAB --> PG
    SM --> PG
    DDL --> PG
    HS --> PG
    LLM --> PG
```

### 依赖规则

| 原则 | 说明 |
|------|------|
| **Auth 是全局守卫** | 所有 API 端点均通过 `get_current_user` / `require_roles` 守卫 |
| **LLM 是共享服务** | Tableau 解读、语义 AI 生成、NL-to-Query 均调用同一 `LLMService` 单例 |
| **Tableau → 语义单向** | 语义模块消费 Tableau 字段元数据，不反向修改 Tableau 资产结构 |
| **发布是受控回写** | 语义发布仅回写 `description`/`caption`/`isCertified`，白名单控制 |
| **Celery 仅做异步** | 定时同步（Tableau Beat 60s）、健康扫描等耗时操作走队列 |

---

## §5 核心数据流

### 5.1 Tableau 资产同步流水线

```mermaid
sequenceDiagram
    participant Beat as Celery Beat
    participant Worker as Celery Worker
    participant Sync as TableauSyncService
    participant TSC as Tableau Server (TSC)
    participant DB as PostgreSQL

    Beat->>Worker: scheduled_sync_all (每 60s)
    Worker->>DB: 查询所有活跃连接 (auto_sync=true)
    loop 每个连接
        Worker->>Sync: sync_all_assets(connection_id)
        Sync->>TSC: PAT 认证 → sign_in()
        Sync->>TSC: 拉取 workbooks (分页)
        Sync->>TSC: 拉取 views (分页)
        Sync->>TSC: 拉取 datasources (分页)
        Sync->>DB: UPSERT tableau_assets
        Sync->>DB: UPSERT tableau_asset_datasources
        Sync->>TSC: 拉取 datasource fields
        Sync->>DB: UPSERT tableau_datasource_fields
        Sync->>DB: 写入 tableau_sync_logs
        Sync->>TSC: sign_out()
    end
```

### 5.2 语义治理生命周期

```mermaid
stateDiagram-v2
    [*] --> draft: 字段同步创建
    draft --> ai_generated: AI 生成语义
    draft --> reviewed: 人工编辑后提交审核
    ai_generated --> reviewed: 人工确认/修改后提交
    ai_generated --> draft: 退回修改
    reviewed --> approved: 审核通过
    reviewed --> rejected: 审核驳回
    rejected --> draft: 退回修改
    approved --> published: 发布到 Tableau
    published --> draft: 回滚（仅 admin）
    published --> [*]

    note right of draft: 初始状态，可编辑
    note right of ai_generated: LLM 生成，待人工确认
    note right of published: 已回写 Tableau REST API
```

### 5.3 LLM 调用链路

```mermaid
sequenceDiagram
    participant API as FastAPI 端点
    participant Svc as LLMService (单例)
    participant Crypto as CryptoHelper
    participant DB as ai_llm_configs
    participant Provider as OpenAI / Anthropic

    API->>Svc: complete(prompt, system)
    Svc->>DB: get_config() 加载活跃配置
    Svc->>Crypto: decrypt(api_key_encrypted)
    alt provider == "openai"
        Svc->>Provider: AsyncOpenAI.chat.completions.create()
    else provider == "anthropic"
        Svc->>Provider: AsyncAnthropic.messages.create()
    end
    Provider-->>Svc: response
    Svc-->>API: {content: "..."} | {error: "..."}
```

**3 种 Prompt 模板：**

| 模板 | 用途 | 消费方 |
|------|------|--------|
| `ASSET_SUMMARY_TEMPLATE` | 资产一句话摘要（100 字内） | Tableau 资产列表 |
| `ASSET_EXPLAIN_TEMPLATE` | 报表深度解读（5 维分析） | Tableau 资产详情 |
| `NL_TO_QUERY_TEMPLATE` | 自然语言 → VizQL JSON | 搜索/查询功能 |

### 5.4 数仓健康扫描流水线

```mermaid
sequenceDiagram
    participant User as 用户
    participant API as /api/governance/health
    participant Worker as Celery Worker
    participant Target as 目标数据库
    participant DB as PostgreSQL

    User->>API: POST /scan (datasource_id)
    API->>DB: 查询 bi_data_sources 获取连接信息
    API->>Worker: health_scan_task.delay()
    API-->>User: 202 {task_id}
    Worker->>Target: 连接目标数据库
    Worker->>Target: 执行检查 SQL（表统计、空值率、索引等）
    Worker->>DB: 写入 bi_health_scan_records
    Worker->>DB: 写入 bi_health_scan_issues
    User->>API: GET /scan/{id} 查询结果
    API-->>User: {score, issues[], recommendations[]}
```

---

## §6 语义层 ↔ LLM 交互标准

### 6.1 上下文组装协议

LLM 调用时，语义上下文按以下优先级组装：

```
┌─────────────────────────────────┐
│ System Prompt                    │  ← 角色定义 + 输出格式约束
├─────────────────────────────────┤
│ 数据上下文块                     │  ← 字段元数据 (优先核心字段)
│  · 数据源名称/描述               │
│  · 字段列表 (name, type, caption)│
│  · 计算字段公式                  │
│  · 业务术语映射                  │
├─────────────────────────────────┤
│ 用户指令                         │  ← 具体问题或操作要求
└─────────────────────────────────┘
```

**Token 预算**：单次调用上下文 ≤ 3000 tokens。超出时按以下策略截断：
1. 保留全部核心字段（度量 + 维度）
2. 截断计算字段公式（仅保留名称）
3. 截断低使用频率字段

### 6.2 AI 语义生成输出契约

```json
{
  "semantic_name": "string — 英文语义名",
  "semantic_name_zh": "string — 中文语义名",
  "semantic_description": "string — 业务描述",
  "semantic_type": "dimension | measure | time_dimension",
  "confidence": 0.85
}
```

- `confidence < 0.3`：标记为低置信度，需人工审核
- JSON 解析失败：重试 1 次，仍失败则返回 `SM_006` 错误

### 6.3 NL-to-Query 输出契约

```json
{
  "fields": [
    {"fieldCaption": "Sales", "function": "SUM"},
    {"fieldCaption": "Region"}
  ],
  "filters": [
    {
      "field": {"fieldCaption": "Order Date"},
      "filterType": "DATE",
      "periodType": "MONTHS",
      "dateRangeType": "LAST"
    }
  ]
}
```

输出直接匹配 Tableau VizQL Data Service `query-datasource` 工具的参数格式。

---

## §7 数据库架构

### 7.1 总览

- **引擎**：PostgreSQL 16（JSONB、全文搜索、连接池）
- **ORM**：SQLAlchemy 2.x + Alembic 迁移
- **连接池**：`pool_size=10`(dev) / `20`(prod)，`max_overflow=20`(dev) / `40`(prod)，`pool_pre_ping=True`，`pool_recycle=3600`
- **当前表数**：23 张（4 个前缀分组）
- **规划表数**：5 张（数据治理、知识库、事件）

### 7.2 前缀分组

| 前缀 | 模块 | 表数 | 代表表 |
|------|------|------|--------|
| `auth_` | 用户认证 | 4 | `auth_users`, `auth_user_groups`, `auth_group_permissions`, `auth_user_group_members` |
| `bi_` | 核心业务 | 9 | `bi_data_sources`, `bi_scan_logs`, `bi_rule_configs`, `bi_requirements`, `bi_health_scan_records` |
| `ai_` | LLM/AI | 1 | `ai_llm_configs` |
| `tableau_` | Tableau 集成 | 9 | `tableau_connections`, `tableau_assets`, `tableau_field_semantics`, `tableau_publish_logs` |

### 7.3 核心 ER 关系

```mermaid
erDiagram
    auth_users ||--o{ bi_data_sources : "owner_id"
    auth_users ||--o{ tableau_connections : "owner_id"
    auth_users ||--o{ bi_requirements : "created_by"

    tableau_connections ||--o{ tableau_assets : "connection_id"
    tableau_connections ||--o{ tableau_sync_logs : "connection_id"
    tableau_connections ||--o{ tableau_field_semantics : "connection_id"

    tableau_assets ||--o{ tableau_asset_datasources : "asset_id"
    tableau_assets ||--o{ tableau_field_semantics : "通过 datasource_id"

    tableau_field_semantics ||--o{ tableau_field_semantic_history : "field_semantic_id"
    tableau_field_semantics ||--o{ tableau_publish_logs : "field_semantic_id"

    bi_data_sources ||--o{ bi_health_scan_records : "datasource_id"
    bi_health_scan_records ||--o{ bi_health_scan_issues : "scan_id"
```

完整表定义详见 [03-data-model-overview.md](specs/03-data-model-overview.md)。

### 7.4 JSONB 使用模式

| 表 | 列 | 存储内容 |
|----|-----|---------|
| `tableau_assets` | `tags_json` | `["tag1", "tag2"]` |
| `tableau_assets` | `metadata_json` | `{"sheetType": "...", "viewUrlName": "..."}` |
| `tableau_sync_logs` | `details_json` | `{"workbooks": 10, "views": 25, "datasources": 5}` |
| `tableau_field_semantics` | `tags_json` | `["核心指标", "财务"]` |
| `tableau_field_semantic_history` | `changes_json` | `{"before": {...}, "after": {...}}` |
| `tableau_publish_logs` | `diff_json` | `[{"field": "caption", "old": "...", "new": "..."}]` |
| `bi_health_scan_issues` | `detail_json` | `{"table": "...", "null_rate": 0.15}` |

### 7.5 迁移策略

```bash
# 创建迁移
cd backend && alembic revision --autogenerate -m "描述"

# 执行迁移
cd backend && alembic upgrade head

# 回滚
cd backend && alembic downgrade -1
```

规则：
- 生产环境必须通过 Alembic 迁移，禁止手动 DDL
- 每次迁移必须可回滚（`downgrade()` 不留空）
- JSONB 列变更需显式写迁移脚本（autogenerate 不可靠）

---

## §8 部署架构

### 8.1 开发环境

```
┌──────────────┐     ┌──────────────┐
│ Vite Dev     │────▶│ FastAPI      │
│ :5173        │ /api│ :8000        │
│ (React 19)   │     │ (uvicorn     │
│              │     │  --reload)   │
└──────────────┘     └──────┬───────┘
                            │
                   ┌────────┴────────┐
                   │                 │
              ┌────▼─────┐    ┌─────▼────┐
              │PostgreSQL │    │ Redis 7  │
              │ :5432     │    │ :6379    │
              │ (Docker)  │    │ (Docker) │
              └──────────┘    └──────────┘
                                   │
                            ┌──────▼───────┐
                            │ Celery Worker│
                            │ + Beat       │
                            └──────────────┘
```

启动命令：
```bash
docker-compose up -d                          # PostgreSQL + Redis
cd backend && uvicorn app.main:app --reload   # API Server
cd backend && celery -A services.tasks worker --beat --loglevel=info  # Worker
cd frontend && npm run dev                    # Frontend
```

### 8.2 生产环境

```
┌──────────────┐     ┌──────────────────────────┐
│ Nginx / CDN  │────▶│ Gunicorn + Uvicorn Worker│
│ (静态资源 +   │     │ (N workers)              │
│  反向代理)    │     └──────────┬───────────────┘
└──────────────┘                │
                       ┌────────┴────────┐
                       │                 │
                  ┌────▼─────┐    ┌─────▼────┐
                  │PostgreSQL │    │ Redis 7  │
                  │ (托管)    │    │ (托管)   │
                  │pool=20   │    │          │
                  │overflow=40│    └──────────┘
                  └──────────┘         │
                                ┌──────▼───────┐
                                │ Celery Worker│
                                │ (独立进程)    │
                                ├──────────────┤
                                │ Celery Beat  │
                                │ (单实例)      │
                                └──────────────┘
```

关键配置（`config/prod/.env.prod`）：
- `DB_POOL_SIZE=20`、`DB_MAX_OVERFLOW=40`
- `SECURE_COOKIES=true`
- `LOG_LEVEL=WARNING`
- 4 把加密密钥必须为强随机值且互不相同

### 8.3 服务依赖矩阵

| 服务 | 依赖 | 不可用影响 |
|------|------|-----------|
| FastAPI | PostgreSQL | 全部 API 不可用 |
| FastAPI | Redis | 异步任务不可用，API 正常 |
| Celery Worker | Redis + PostgreSQL | 定时同步/扫描停止 |
| Celery Beat | Redis | 定时调度停止 |
| Tableau 同步 | Tableau Server | 同步失败，缓存数据可读 |
| LLM 功能 | OpenAI/Anthropic API | AI 功能不可用，其他正常 |

---

## §9 安全架构

### 9.1 加密密钥隔离

```
┌─────────────────────────────────────────────┐
│                密钥隔离架构                    │
├─────────────┬───────────────────────────────┤
│ SESSION_SECRET          │ JWT 签名 (HS256)   │
├─────────────┼───────────────────────────────┤
│ DATASOURCE_ENCRYPTION_KEY │ 数据源密码 (Fernet) │
├─────────────┼───────────────────────────────┤
│ TABLEAU_ENCRYPTION_KEY    │ Tableau PAT (Fernet)│
├─────────────┼───────────────────────────────┤
│ LLM_ENCRYPTION_KEY        │ LLM API Key (Fernet)│
└─────────────┴───────────────────────────────┘
```

**强制规则**：
- 4 把密钥**必须不同**
- 生产环境必须为 32 字节强随机值
- 密钥泄露时仅需轮换对应密钥，不影响其他模块

### 9.2 认证流程

```mermaid
sequenceDiagram
    participant Client as 前端
    participant API as FastAPI
    participant Guard as get_current_user
    participant DB as PostgreSQL

    Client->>API: POST /api/auth/login {username, password}
    API->>DB: 查询 auth_users
    API->>API: PBKDF2-SHA256 验证密码
    API->>API: 生成 JWT {sub, username, role, exp}
    API-->>Client: Set-Cookie: session=<JWT> (HttpOnly, SameSite=Lax)

    Client->>API: GET /api/tableau/assets (Cookie: session=<JWT>)
    API->>Guard: 提取 Cookie → 解码 JWT
    Guard->>DB: 验证用户存在且 is_active=True
    Guard-->>API: {id, username, role}
    API-->>Client: 200 资产列表
```

### 9.3 RBAC 权限模型

四级角色：`admin` > `data_admin` > `analyst` > `user`

| 能力域 | admin | data_admin | analyst | user |
|--------|:-----:|:----------:|:-------:|:----:|
| 用户/组/权限管理 | Y | - | - | - |
| 数据源 CRUD | Y | Y(own) | - | - |
| DDL 验证 | Y | Y | Y | Y |
| 规则管理 | Y | Y | - | - |
| Tableau 连接管理 | Y | Y | - | - |
| 资产浏览 + AI 解读 | Y | Y | Y | - |
| 语义 CRUD + AI 生成 | Y | Y | - | - |
| 语义审批 | Y | reviewer | - | - |
| 语义发布/回滚 | Y | - | - | - |
| LLM 配置 | Y | - | - | - |
| 健康扫描 | Y | Y | 仅查看 | - |
| 系统管理 | Y | - | - | - |

完整权限矩阵详见 [02-api-conventions.md](specs/02-api-conventions.md) §6。

### 9.4 数据敏感度分级

| 级别 | 代码 | 处理规则 |
|------|------|---------|
| 公开 | `PUBLIC` | 可发布到 Tableau，可被 NL-to-Query 使用 |
| 内部 | `INTERNAL` | 可发布，仅内部可见 |
| 高敏感 | `HIGH` | 禁止发布到 Tableau，禁止 LLM 处理 |
| 机密 | `CONFIDENTIAL` | 禁止发布，禁止 LLM，禁止导出 |

发布服务白名单控制：
```python
WRITABLE_FIELDS = {
    "datasource": ["description", "isCertified"],
    "field": ["caption", "description"],
}
BLOCKED_SENSITIVITY = {SensitivityLevel.HIGH, SensitivityLevel.CONFIDENTIAL}
```

### 9.5 安全红线

1. 密码/密钥**不得**出现在日志或 API 响应中
2. LLM 调用仅发送资产名称/描述，**不得**发送实际数据值
3. LLM 返回内容需 HTML 转义后再渲染（XSS 防护）
4. 所有 SQL 使用参数化查询（SQLAlchemy ORM），禁止字符串拼接
5. 注册端点限流：同一 IP 60 秒内最多 5 次

---

## §10 环境变量约定

| 变量 | 模块 | 说明 | 开发默认值 |
|------|------|------|-----------|
| `DATABASE_URL` | 核心 | PostgreSQL 连接字符串 | `postgresql://mulan:mulan@localhost:5432/mulan_bi` |
| `SESSION_SECRET` | Auth | JWT 签名密钥 | `dev-session-secret-do-not-use-in-prod` |
| `DATASOURCE_ENCRYPTION_KEY` | 数据源 | 密码加密 (Fernet) | `dev-ds-encryption-key-32bytes!!` |
| `TABLEAU_ENCRYPTION_KEY` | Tableau | PAT 加密 (Fernet) | `dev-tab-encryption-key-32bytes!` |
| `LLM_ENCRYPTION_KEY` | LLM | API Key 加密 (Fernet) | `dev-llm-encryption-key-32bytes!` |
| `ALLOWED_ORIGINS` | CORS | 允许域名（逗号分隔） | `http://localhost:5173,http://localhost:3002` |
| `SECURE_COOKIES` | Auth | 生产设为 `true` | `false` |
| `CELERY_BROKER_URL` | 任务 | Redis Broker | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | 任务 | Redis Backend | `redis://localhost:6379/1` |
| `DB_POOL_SIZE` | 核心 | 连接池大小 | `10` |
| `DB_MAX_OVERFLOW` | 核心 | 连接池溢出 | `20` |
| `LOG_LEVEL` | 核心 | 日志级别 | `DEBUG` |
| `ADMIN_USERNAME` | Auth | 初始管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | Auth | 初始管理员密码 | `admin123` |

---

## §11 CI/CD 约定

### Frontend Job
| 步骤 | 命令 | 说明 |
|------|------|------|
| Lint | `npm run lint` | ESLint，0 warnings |
| Type Check | `npm run type-check` | TypeScript |
| Unit Tests | `npm run test -- --coverage` | Vitest + RTL，覆盖率报告 |
| Build | `npm run build` | Vite production build |

### Backend Job (PostgreSQL service container)
| 步骤 | 命令 | 说明 |
|------|------|------|
| Syntax Check | `python3 -m py_compile` | 全量 Python 文件 |
| Import Check | `from app.main import app` | 验证无导入错误 |
| Tests + Coverage | `pytest tests/ --cov=services --cov=app --cov-fail-under=50` | pytest + pytest-cov，门槛 50% |

### 覆盖率门槛
- `services/` — ≥ 50%
- `app/` — ≥ 50%
- `frontend/src/` — 鼓励 ≥ 50%

### 断言规范
- 禁止软断言（`if resp.status_code == 200` 静默通过）
- 必须用硬断言 `assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"`

### 数据库
- CI 使用 `postgres:16` Docker service，测试库 `mulan_bi_test`
- 开发：`docker-compose up -d` 启动后手动跑测试

---

## 附录：Spec 索引

详见 [docs/specs/README.md](specs/README.md) — 20 份技术规格书的完整索引和状态跟踪。
