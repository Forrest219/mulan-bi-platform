# Mulan BI Platform

数据建模与治理平台 — 面向 BI 团队的数据质量、DDL 规范、Tableau 资产治理、语义维护工具。

## ⚠️ Gemini MCP 使用规则

模型优先级（按顺序）：
1. **Gemini 3 Flash** — 首选
2. **Gemini 3.1 Flash Lite** — 次选
3. **Gemini 2.5 Flash** — 最后备选

- **NEVER** use `gemini-2.5-pro` via MCP. It causes quota errors on this API key.
- **ALWAYS** specify `model` 参数 when calling Gemini MCP tools.
- If `gemini_codebase_analyzer` fails due to quota, fallback to reading files manually and using current session model for analysis.
- The API key `AIzaSyAoHsKF8oO_z2Y1uXtihi0BgdvjjKBfz_A` is on free tier — use Flash models only.

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

## 🤖 Agent 协作流水线规则（强制执行）

本项目使用多模型分工流水线（详见 `AGENT_PIPELINE.md`）。以下三条为**铁律**，所有阶段必须遵守：

---

### 规则 1：所有交接必须以文件制品为准，禁止口头上下文传递

每个阶段必须产出文档，不得仅将上下文留在对话里。

| 必须产出的文件 | 适用阶段 |
|--------------|---------|
| `Context_Summary.md` | 阶段一前置 |
| `SPEC.md` | 阶段一 |
| `SPEC_GAP_REPORT.md` | 阶段二（如有） |
| `IMPLEMENTATION_NOTES.md` | 阶段二 |
| `Refactor_Instructions.md` | 阶段四返工（如有） |

> 不以文件形式留痕的决策，视为未发生。

---

### 规则 2：Final Approval 必须输出两维独立报告

Opus 终审不得只检查"是否符合 SPEC"，还必须验证：

- **SPEC Compliance Check** — 代码是否按 SPEC 实现
- **Real-World Risk Check** — SPEC 本身是否遗漏关键真实约束

现实常见问题不是"实现没照 SPEC 做"，而是"SPEC 自己漏了坑"。两维报告缺一不可。

---

### 规则 3：Opus 修改权限严格量化，禁止模糊地带

Opus 在终审阶段可执行的动作：

| ✅ 允许 | ❌ 禁止 |
|---------|---------|
| 小范围批注 | 跨文件重构 |
| 1-2 处微修复 | 接口改动 |
| 补一句注释 | 大段逻辑重写 |
| | 改动超出 Change Budget 范围 |
| | 以"优化"名义修改 SPEC.md |

> 违反以上任意一项，视为越权，须回退给对应角色执行。

---

### 铁规则汇总

1. **MiniMax 可以修实现，不可以私改 SPEC**
2. **Human 确认 PRD 前，Opus 不得进入实现阶段**
3. **所有交接均为文件交接，不以口头上下文传递**
4. **Opus 终审不得做大规模代码修改（量化标准见上方规则 3）**
5. **Final Approval 必须输出 SPEC 合规 + 真实风险两维报告**

---

## 测试规范（强制）

新功能提交前必须满足以下条件，否则 CI 失败：

### 后端测试
- **框架**: pytest + pytest-cov（已在 `backend/requirements.txt`）
- **覆盖率门槛**: 核心服务层 (`services/`) ≥ 50%，API 层 (`app/`) ≥ 50%
- **断言**: 必须使用硬断言 `assert resp.status_code == 200`，禁止 `if resp.status_code == 200` 静默通过
- **单元测试文件**: `backend/tests/test_*.py`
- **运行**: `cd backend && pytest tests/ --cov=services --cov=app --cov-fail-under=50`
- **新增测试场景**: auth (密码哈希/JWT)、health scoring (7因子算法)、encryption (Fernet)

### 前端测试
- **框架**: Vitest + React Testing Library（已在 `frontend/package.json`）
- **单元测试文件**: `frontend/tests/unit/*.test.{ts,tsx}`
- **运行**: `cd frontend && npm test`
- **覆盖率**: 鼓励达到 50%+

### CI 执行
- `.github/workflows/ci.yml` 中两个 job 均运行测试
- PostgreSQL service container 供后端测试使用
- 不跑的测试 = 不存在的测试

---

<!-- MCP:GEMINI-MCP-LOCAL:START -->
# 🤖 MCP Gemini Local - AI Asistanı Kullanım Rehberi

Bu rehber, AI asistanlarının MCP araçlarını doğru, güvenli ve verimli kullanması için optimize edilmiştir.

---

### 1) Zorunlu İş Akışı (Onay Alana Kadar Tekrarla)
1. Danış (Consult): `analyzer` ile plan al (`implementation`).
2. Kodla (Code): Plana uy.
3. İncelet (Review): `analyzer` ile değişiklikleri incelet (`review`).
4. Düzelt (Fix): Geri bildirimi uygula.
5. Doğrula (Verify): Tekrar incelet.

---

### 2) Hızlı Başlangıç
1. Token Sayısını Ölç: `calculate_token_count`.
2. Araç Seç:
- < 900K: `gemini_codebase_analyzer`
- ≥ 900K: `project_orchestrator` (2 adım)
Örnek: `{"tool_name":"calculate_token_count","params":{"projectPath":"."}}`

---

### 3) Araç Referansı
- calculate_token_count:
  - Parametreler: `projectPath`, `textToAnalyze`, `tokenizerModel`.
  - Doğru: `{"tool_name":"calculate_token_count","params":{"projectPath":"."}}`
  - Yanlış: `{"tool_name":"calculate_token_count","params":{"question":"?"}}`
  - Not: Path traversal engellenir.
- gemini_codebase_analyzer:
  - Parametreler: `projectPath`, `question`, `analysisMode`, `includeChanges`, `autoOrchestrate`.
  - Doğru: `{"tool_name":"gemini_codebase_analyzer","params":{"projectPath":".","question":"Değişiklikleri incele","analysisMode":"review","includeChanges":{"revision":"."}}}`
  - Yanlış: `{"tool_name":"gemini_codebase_analyzer","params":{"analysisMode":"general","includeChanges":{}}}`
  - Not: Büyük projede `autoOrchestrate=true`.
- project_orchestrator_create (Adım 1):
  - Parametreler: `projectPath`, `question`, `analysisMode`, `maxTokensPerGroup`.
  - Doğru: `{"tool_name":"project_orchestrator_create","params":{"projectPath":".","question":"Güvenlik açıklarını bul"}}`
  - Yanlış: `{"tool_name":"project_orchestrator_create","params":{"fileGroupsData":"..."}}`
  - Not: `groupsData` sonraki adım için zorunlu.
- project_orchestrator_analyze (Adım 2):
  - Parametreler: `projectPath`, `question`, `fileGroupsData`, `analysisMode`.
  - Doğru: `{"tool_name":"project_orchestrator_analyze","params":{"question":"Riskleri çıkar","fileGroupsData":"{...}"}}`
  - Yanlış: `{"tool_name":"project_orchestrator_analyze","params":{"question":"Analiz et"}}`
  - Not: Token limiti aşılırsa `.mcpignore`.
- gemini_dynamic_expert_create:
  - Parametreler: `projectPath`, `expertiseHint`.
  - Doğru: `{"tool_name":"gemini_dynamic_expert_create","params":{"projectPath":".","expertiseHint":"React performans"}}`
  - Yanlış: `{"tool_name":"gemini_dynamic_expert_create","params":{"expertPrompt":"..."}}`
  - Not: 1000 dosya / 100MB sınır.
- gemini_dynamic_expert_analyze:
  - Parametreler: `projectPath`, `question`, `expertPrompt`.
  - Doğru: `{"tool_name":"gemini_dynamic_expert_analyze","params":{"question":"Auth mimarisi","expertPrompt":"<prompt>"}}`
  - Yanlış: `{"tool_name":"gemini_dynamic_expert_analyze","params":{"question":"..."}}`
  - Not: Boyut limitleri geçerli.
- mcp_setup_guide:
  - Parametreler: `client`, `projectPath`, `force`.
  - Doğru: `{"tool_name":"mcp_setup_guide","params":{"client":"cursor","projectPath":"."}}`
  - Yanlış: `{"tool_name":"mcp_setup_guide","params":{"client":"unknown-client"}}`
  - Not: Diğer araçlardan önce.

---

### 4) Mod Stratejileri
- general, implementation, review, security, debugging (tek satır özet).

---

### 5) Anti-Pattern’ler
- Analyzer’ı büyük projede zorlamak.
- `includeChanges`'ı `review` olmadan.
- Orchestrator adımını atlamak (`groupsData` aktarmamak).
- `mcp_setup_guide`'ı atlamak.

---

### 6) İstemci Entegrasyonu
- [`CURSOR_SETUP.md`](CURSOR_SETUP.md), [`claude_desktop_config.example.json`](claude_desktop_config.example.json)
- Not: API anahtarlarını ortam değişkeni olarak tutun.

---

### 7) Güvenlik ve Performans
- Path traversal engellenir; `projectPath` doğrulanır.
- Rate limitlerde bekle/yeniden dene.
- `.mcpignore` ile gereksiz klasörleri hariç tut.
- `autoOrchestrate=true` ile büyük projede orchestrator.

---

### 8) SSS
- Analyzer zaman aşımı: `orchestrator` veya `autoOrchestrate=true`.
- Path traversal hatası: `.` gibi göreli yol kullan.
- `fileGroupsData missing`: `create` çıktısını `analyze`’a aktar.
<!-- MCP:GEMINI-MCP-LOCAL:END -->
