# Mulan BI Platform

数据建模与治理平台 — 面向 BI 运维团队的数据质量、DDL 规范、Tableau 资产治理、语义维护工具。

@AGENT_PIPELINE.md
@docs/TESTING.md

---

## 产品定位

**用户画像**（主要三类）
- **数据工程师**：负责数仓 DDL 规范审查、数据源管理、健康扫描
- **BI 运维人员**：Tableau 资产巡检、语义治理、健康评分监控
- **数据管理员**：LLM 配置、用户权限管理、规则配置

**典型 Workflow**
1. 工程师提交 DDL → 平台自动合规检查 → 输出违规报告
2. 运维人员在工作台查看 Tableau 资产健康分 → 钻取问题字段 → 触发语义修复

**当前阶段**：v0.x，面向内部 BI 团队 dogfooding

**成功指标**
- 数仓 DDL 合规率 ≥ 90%
- Tableau 资产健康分 ≥ 80（全连接平均）
- 语义发布日志覆盖所有字段变更

**Non-Goals**：不做 ETL 数据集成、不做 BI 可视化本身、不做多租户 SaaS

---

## 参考文档

| 文档 | 说明 |
|------|------|
| [`AGENT_PIPELINE.md`](AGENT_PIPELINE.md) | Agent 流水线完整规则（角色、阶段、铁规则） |
| [`docs/TESTING.md`](docs/TESTING.md) | 测试规范、CI 分层、tester 检查清单 |
| [`docs/specs/README.md`](docs/specs/README.md) | 技术规格书索引（24+ 份 spec） |
| [`docs/references-mcp-servers.md`](docs/references-mcp-servers.md) | 外部 MCP Server 接入参考（含 Tableau MCP、Gemini MCP） |
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

**每次修改代码后，根据改动范围执行对应命令，全部通过才算完成。**

### 改了后端 Python 文件（`backend/app/` 或 `backend/services/`）

```bash
# 1. 语法检查
cd backend && python3 -m py_compile $(git diff --name-only | grep '\.py$')

# 2. 运行相关测试
cd backend && pytest tests/ -x -q

# 3. 如果改了 API 路由，验证服务可启动
cd backend && uvicorn app.main:app --port 8000 &
sleep 2 && curl -s http://localhost:8000/health && kill %1
```

### 改了前端文件（`frontend/src/`）

```bash
# 1. 类型检查（零错误才算通过）
cd frontend && npm run type-check

# 2. Lint
cd frontend && npm run lint

# 3. 单元测试
cd frontend && npm test -- --run

# 4. 构建验证（改了路由/入口必须跑）
cd frontend && npm run build
```

### 改了数据库 Model（`backend/services/*/models.py`）

```bash
# 必须生成迁移脚本，不得手动修改表结构
cd backend && alembic revision --autogenerate -m "describe_your_change"

# 检查生成的迁移文件是否符合预期（人工确认）
# 然后执行
cd backend && alembic upgrade head

# 验证可回滚
cd backend && alembic downgrade -1 && alembic upgrade head
```

### 改了 `config/rules.yaml` 或 DDL 引擎（`modules/ddl_check_engine/`）

```bash
# 运行 DDL 引擎专项测试
cd backend && pytest tests/ -k "ddl" -v
```

---

## 常用命令

```bash
# 启动 PostgreSQL（Docker）
docker-compose up -d

# 后端启动
cd backend && uvicorn app.main:app --reload --port 8000

# 前端启动
cd frontend && npm run dev

# 后端全量测试（含覆盖率）
cd backend && pytest tests/ --cov=services --cov=app --cov-fail-under=50

# 前端全量测试
cd frontend && npm test -- --run
```

---

## 项目结构与目录约束

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
│                            #   约束：见"Alembic 硬性操作规范"节，禁止手动建表
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

---

## 数据库与 Alembic 硬性操作规范

⚠️ **DDL 变更是本项目最高风险操作，以下规范强制执行。**

### 禁止行为

- ❌ 直接在 PostgreSQL 执行 `ALTER TABLE` / `DROP TABLE` / `CREATE TABLE`（绕过 Alembic）
- ❌ 手动编辑已提交的迁移文件（破坏迁移链完整性）
- ❌ 在生产数据库执行未经本地验证的迁移
- ❌ 迁移脚本中写不可逆操作而不提供 `downgrade()` 实现
- ❌ 一次迁移混入多个不相关的表变更

### 必须遵守

1. **Model 先行**：先改 SQLAlchemy Model，再 `alembic revision --autogenerate`，不得反向操作
2. **检查自动生成内容**：autogenerate 可能遗漏 `server_default`、索引、自定义类型，提交前人工核查迁移文件
3. **本地验证三步**：`upgrade head` → 验证功能 → `downgrade -1` → `upgrade head`，三步全通过才可提交
4. **迁移描述清晰**：`-m` 参数使用 `动词_表名_字段名` 格式，如 `add_llm_api_key_updated_at`
5. **不可逆操作登记 ADR**：删列、删表、字段类型变更等操作须在 `docs/adr/` 登记，说明数据处理方案
6. **生产执行前备份**：生产环境执行迁移前，必须确认有当日备份

### 迁移文件命名约定

```
backend/alembic/versions/YYYYMMDD_HHMMSS_<描述>.py
```

---

## 数据库

PostgreSQL 16 — 单库统一管理：

| 前缀 | 模块 | 表名示例 |
|------|------|---------|
| `auth_` | 用户认证 | auth_users, auth_user_groups |
| `bi_` | 核心业务 | bi_data_sources, bi_scan_logs, bi_requirements |
| `ai_` | LLM/AI | ai_llm_configs |
| `tableau_` | Tableau | tableau_connections, tableau_assets, tableau_field_semantics |

环境变量：`DATABASE_URL=postgresql://mulan:mulan@localhost:5432/mulan_bi`

---

## 认证

- 默认管理员通过 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 环境变量配置
- 普通用户需由管理员创建
- Session 存储在 HTTP Only Cookie，有效期 7 天
- 四级角色：admin, data_admin, analyst, user

## API 基础路径

- 本地后端：`http://localhost:8000`
- 前端代理：`/api` → `http://localhost:8000`

---

## ⚠️ 项目特有技术陷阱

**遇到过的真实 Bug，改代码前必读。**

### 陷阱 1：AuthContext useCallback 无限重渲染

**现象**：登录后页面持续发送 `/api/auth/me` 请求，CPU 飙升。

**根因**：将 token 过期时间存为 `useState`，导致 `checkAuth` 的 `useCallback` 依赖数组包含该 state，state 更新触发 `checkAuth` 重新创建，`useEffect` 重新触发，形成闭环。

**正确做法**：不需要触发重渲染的内部计时器值用 `useRef`，不要用 `useState`。

```ts
// ❌ 错误
const [tokenExpiresAt, setTokenExpiresAt] = useState<number | null>(null);

// ✅ 正确
const tokenExpiresAtRef = useRef<number | null>(null);
```

---

### 陷阱 2：React.lazy 不支持具名导出（named export）

**现象**：`lazy(() => import('./AssetInspector'))` 报错，组件 undefined。

**根因**：`React.lazy` 只接受 default export，具名导出需要手动转换。

**正确做法**：

```ts
// ❌ 错误
const AssetInspector = lazy(() => import('./AssetInspector'));

// ✅ 正确
const AssetInspector = lazy(() =>
  import('./AssetInspector').then(m => ({ default: m.AssetInspector }))
);
```

---

### 陷阱 3：react-router `<a href>` 触发全页刷新

**现象**：页面间跳转导致所有状态丢失，SPA 失效。

**根因**：在 React Router 应用中使用原生 `<a href>` 而非 `<Link to>`，会绕过客户端路由触发完整页面重载。

**正确做法**：项目内所有跳转一律使用 `<Link to>` 或 `useNavigate()`，只有外部链接使用 `<a href target="_blank">`。

---

### 陷阱 4：Alembic autogenerate 遗漏 `server_default`

**现象**：本地迁移成功，生产执行后新行的默认值为 NULL，导致应用报错。

**根因**：SQLAlchemy `Column(default=...)` 是 Python 层默认值，Alembic autogenerate 不会将其转换为数据库层 `server_default`，已有行不受影响，只有新行通过 Python 插入才有值。

**正确做法**：需要数据库级默认值时，明确写 `server_default`：

```python
# ❌ 只有 Python 插入时生效
is_active = Column(Boolean, default=True)

# ✅ 数据库层保证，迁移后存量行也有值
is_active = Column(Boolean, server_default=sa.true(), nullable=False)
```

---

### 陷阱 5：LLM 多配置 `purpose` 路由静默降级

**现象**：配置了专用 `embedding` 模型，但实际调用走了 `general` 模型，日志无报错。

**根因**：LLM 路由按 `purpose` 字段优先匹配，找不到时 fallback 到 `general`，整个过程静默进行，不抛出异常也不记录警告。

**正确做法**：任何 `purpose` 专用调用，若无匹配配置应显式抛错或告警，不允许静默 fallback 到 general——静默降级在生产中会导致向量维度不匹配等隐蔽故障。

---

## 🤖 Agent 协作流水线（速查）

> 完整规则详见 [`AGENT_PIPELINE.md`](AGENT_PIPELINE.md)

### 角色速查

| 短名 | 职责 |
|------|------|
| **pm** | 需求、范围、PRD、用户故事、优先级 |
| **designer** | 体验、交互、页面结构、视觉方向、文案 |
| **architect** | 技术架构、spec、任务拆分、验收标准 |
| **coder** | 主力开发 |
| **tester** | 阶段二产出验收：happy path、AC 覆盖、类型检查、无遗留临时代码 |
| **fixer** | 补测试、修 bug、处理 review 意见、覆盖率达标 |
| **reviewer** | 独立代码复核，优先 Codex MCP |
| **shipper** | 发布检查、release notes、ADR 过期扫描、回滚方案 |

### 铁规则（完整版见 AGENT_PIPELINE.md）

1. **coder 可以修实现，不可以私改 SPEC**
2. **Human 确认 PRD 前，coder 不得进入实现阶段**
3. **所有交接均为文件交接，不以口头上下文传递**
4. **reviewer 不得做大规模代码修改（量化标准见 AGENT_PIPELINE.md 阶段四）**
5. **Final Approval 必须输出 SPEC 合规 + 真实风险两维报告**
6. **禁止救急方案；紧急例外必须走 ADR 登记（≤14 天），过期阻塞发布**
7. **交接制品命名严格遵循制品清单，禁止写 `HANDOVER.md` 等非规范名称**
   - coder 阶段唯一合法交接文件名：`IMPLEMENTATION_NOTES.md`
   - 钩子 `scripts/check-handover.sh` 检测到非法命名立即阻塞，不得绕过

> 规则编号永不重用、永不跳号。废止的规则保留编号并标注 `(Deprecated)`。

---

## 规则 6 细则：禁止救急方案

**适用场景**：设计评估、技术选型、代码实现、UI 交互

**含义**：
- 不做"先救急、后优化"的两步方案；直接做长期正确的版本
- 不以"当前够用"为由跳过安全校验、权限控制、审计日志、错误处理
- UI 不做临时占位：颜色、状态必须和真实 API 结果绑定
- 前端和后端各自独立校验，两层都做，不以前端兜底代替后端校验
- 能在本次实现的，不留"TODO: 后续优化"注释

**违反示例**：
- ❌ 用假绿色圆点代替真实连通性检测
- ❌ 用 `catch (e: any)` 替代类型安全的错误处理
- ❌ 只做前端 disabled 不做后端 min_length 校验

**紧急豁免通道（ADR 机制）**：

1. 在 `docs/adr/ADR-XXXX-emergency-<topic>.md` 登记：原因、影响、回滚、**失效日期（≤14 天）**、责任人
2. 代码用 `# EMERGENCY-ADR-XXXX` 注释引用，不得使用裸 `TODO`
3. shipper 每次发布前扫描过期 ADR；过期未清理 → **阻塞发布**

---

## 实现原则：核心链路避免 mock

- 核心业务链路禁止使用 mock、假数据、占位实现冒充完成。
- 面向用户可见的功能，优先打通真实契约、真实数据流、真实依赖。
- 若外部依赖暂时不可用，先完成真实接口定义与调用链路，并明确标注阻塞点。
- mock 仅允许用于局部单元测试或不稳定的第三方依赖隔离，不得作为功能已完成的依据。
- 任何基于 mock 的结果，必须明确标注为演示态或过渡态。

---

## 测试规范（摘要）

> 完整规范见 [`docs/TESTING.md`](docs/TESTING.md)

| CI 阶段 | 触发时机 | 内容 |
|---------|---------|------|
| PR 级 | coder PR 提交 | smoke test + lint + type-check |
| merge-to-main | fixer 完成后合并 | 全量测试 + 覆盖率 ≥ 50% |

- 硬断言：`assert resp.status_code == 200`，禁止静默通过
- 不跑的测试 = 不存在的测试
