# 项目清理与结构调整方案

> 生成时间：2026-05-14-14  
> 执行人：Coder  
> 约束：不影响启停、只归档不删除、仅指定方案不执行

---

## 一、僵尸文件清单（7 项）

### Z-1 `data/*.db` — SQLite 历史残留
**问题**：项目已全面迁移 PostgreSQL，`data/` 目录下 9 个 `.db` 文件（datasources.db、llm_config.db、llm.db 等）是迁移前遗留的 SQLite 数据库，当前运行无需读写。  
**方案**：整体归档至 `docs/archive/sqlite-legacy-data/`，或移出版本库仅在本地保留。

### Z-2 `SESSION.md`（根目录）— 会话临时文件
**问题**：会话记录/上下文续接文件，临时性强，不属于项目正式资产。  
**方案**：移入 `inbox/`，按命名规范加时间前缀：`20260514-14-SESSION.md`。

### Z-3 `TESTER_PASS.md`（根目录）— 流水线产物错位
**问题**：AGENT_PIPELINE.md 规定测试报告应为 `TESTER_PASS.md` 或 `TESTER_FAIL.md`，但 inbox/README.md 和 CLAUDE.md 均规定正式测试报告应在 `docs/tests/`，不应在根目录。  
**方案**：归档至 `docs/archive/`。

### Z-4 `cookies.txt`（根目录）— 敏感文件
**问题**：Cookie 存储文件，可能含认证凭据，不应进入版本库。  
**方案**：确认是否已在 `.gitignore`，若未被忽略应立即添加，文件本身保持本地，不归档。

### Z-5 `backend/IMPLEMENTATION_NOTES.md` — 错误位置
**问题**：IMPLEMENTATION_NOTES 是 coder 阶段产物，权威位置为 `docs/` 体系，backend/ 根目录不应存放文档类制品。  
**方案**：归档至 `docs/archive/`，在 backend/ 根目录删除（或创建指向归档位置的 README 引用）。

### Z-6 `docs/roles/Context_Summary__sql-agent-spec-29.md` + `docs/roles/SPEC_Review__sql-agent-spec-29.md`
**问题**：两个文件是 spec-29（SQL Agent）流水线产物（Context_Summary 和 SPEC_Review），错误放入了角色目录 `docs/roles/`。  
**方案**：归档至 `docs/archive/spec29/`。

### Z-7 `docs/specs/spec25/IMPLEMENTATION_NOTES.md` + `docs/specs/bi-events-extra-data-fix-IMPLEMENTATION_NOTES.md`
**问题**：两个孤立的 IMPLEMENTATION_NOTES，应在 `docs/archive/` 而非 `docs/specs/`。  
**方案**：归档至 `docs/archive/spec25/` 和 `docs/archive/`。

---

## 二、单一来源原则违反（4 项）

### D-1 `agents/` vs `docs/roles/` — 角色定义双份
**问题**：两个目录均存有 architect/coder/designer/fixer/pm/reviewer/shipper/tester 共 8 个角色文件，内容重叠。CLAUDE.md 指向 `agents/`，AGENT_PIPELINE.md 指向 `docs/roles/`，混乱。  
**方案**：
- 权威来源定为 `agents/`（CLAUDE.md 已指向此处）
- `docs/roles/` 中 8 个角色文件归档至 `docs/archive/roles-legacy/`
- `docs/roles/` 保留目录但更新 README，注明权威源在 `agents/`

### D-2 `CHANGELOG.md`（根目录）与 `docs/CHANGELOG.md` — 重复
**问题**：同名文件存在两处，违反单一事实来源。  
**方案**：`docs/CHANGELOG.md` 归档至 `docs/archive/`，以根目录版本为唯一来源。

### D-3 `docs/` 根目录的 `prd-*.md` 与 `docs/prd/` 子目录并存
**问题**：`docs/prd/` 目录存在但只有 1 个文件（PRD-open-webui-query.md），其余 5 个 prd-*.md（prd-database-monitor、prd-llm-layer、prd-status、prd-tableau-mcp、prd-tableau-v2）直接散落在 `docs/` 根目录。  
**方案**：将 5 个 prd-*.md 全部移入 `docs/prd/`，统一来源。

### D-4 `docs/` 根目录的 `tech-*.md` 与 `docs/tech/` 子目录并存
**问题**：`docs/tech/` 存在，但 7 个 tech-*.md 文件散落在 `docs/` 根目录。  
**方案**：将 7 个 tech-*.md 全部移入 `docs/tech/`。

---

## 三、docs/ 根目录散落文件归档（10 项）

当前 `docs/` 根目录有大量不属于根层的文件，按目标分类：

| 文件 | 建议归档位置 | 原因 |
|------|------------|------|
| `MVP_测试指引.md` | `docs/archive/mvp/` | MVP 阶段已完成 |
| `MVP_外部服务配置指引.md` | `docs/archive/mvp/` | MVP 阶段已完成 |
| `MVP_验证记录.md` | `docs/archive/mvp/` | MVP 阶段已完成 |
| `INCIDENT_REPORT_2026-05-10_SYS-001_LOGIN.md` | `docs/archive/incidents/` | 已完结事故报告 |
| `SPEC_Compliance_Check.md` | `docs/archive/` | 历史 reviewer 产物 |
| `SPEC_Compliance_Check__data_agent.md` | `docs/archive/` | 历史 reviewer 产物 |
| `REALWORLD_Risk_Check.md` | `docs/archive/` | 历史 reviewer 产物 |
| `PM_INVESTIGATION_20260419.md` | `docs/archive/` | 历史 PM 调查 |
| `PM_LLM_CONFIG_FEEDBACK.md` | `docs/archive/` | 历史 PM 反馈 |
| `RETROSPECTIVE_SPEC25.md` | `docs/archive/` | 已完成复盘 |
| `DEV_PROGRESS.md` | `docs/archive/` | 进度追踪类临时文档 |
| `DESIGN_SPEC_HOMEPAGE_V2.md` | `docs/archive/` | 已实施的设计规格 |
| `SPEC_DEVELOPER_PROMPT_TEMPLATE.md` | `docs/specs/` 或 `.claude/` | 若仍在用，移入 specs；否则归档 |
| `qa-llm-config-test-cases.md` | `docs/tests/`（需新建） | 测试用例应入测试目录 |
| `prd-status.md` + `prd-status-spec24-rollout-plan.md` | `docs/prd/` | PRD 状态追踪文件 |
| `semantic-governance-spec-v0.1.md` | `docs/specs/` | 规格文档错放根目录 |

**保留在 `docs/` 根目录的文件**（高价值、常用）：
- `ARCHITECTURE.md` — 架构总览，高频引用
- `TESTING.md` — 测试规范，CLAUDE.md 中 @引用
- `RISK_REGISTER.md` — 风险登记，属于持续维护文件
- `references-mcp-servers.md` — 外部参考，当前活跃使用

---

## 四、OpenSpec 目录不合规（3 项）

### O-1 `openspec/specs/` 命名约定不符
**问题**：当前 `openspec/specs/` 下使用 `<order>-<spec-number>-<name>.md` 格式（如 `00-34-connection-management-spec.md`），OpenSpec 标准为 `<domain>/spec.md` 格式。  
**方案**：在 `openspec/` 下建立 `config.yaml`，显式声明当前命名约定（brownfield 模式允许自定义），**不强制重命名**，但需文档化偏差原因。

### O-2 `openspec/changes/` 目录缺失
**问题**：OpenSpec 的核心工作流依赖 `changes/` 目录管理活跃变更，当前缺失导致变更生命周期无法追踪。  
**方案**：建立 `openspec/changes/` 和 `openspec/changes/archive/` 目录，并补充占位 README，说明变更管理流程。

### O-3 `openspec/config.yaml` 缺失
**问题**：没有 config.yaml，无法注入项目上下文到 OpenSpec 工作流。  
**方案**：创建 `openspec/config.yaml`，注入技术栈（React 19/FastAPI/PostgreSQL）、API 约定（`/api` 前缀）、命名约定（按现有 CLAUDE.md 摘录）。

---

## 五、backend/ 结构问题（1 项）

### B-1 `backend/check_*.py` 散落根目录
**问题**：`check_grants.py`、`check_keywords.py`、`check_load.py`、`check_truncate.py` 直接放在 `backend/` 根目录，`project-structure.md` 规范中此类脚本应在 `backend/scripts/`。  
**方案**：移入 `backend/scripts/`（不影响任何启动流程，这些是独立运行脚本）。

---

## 六、frontend/ 结构问题（1 项）

### F-1 `frontend/screenshots_*.png` 散落根目录
**问题**：多个页面截图文件直接在 frontend/ 根目录，属于测试产物。  
**方案**：集中移入 `frontend/screenshots/`（已有 `puppeteer-config.json` 和 `save-screenshots.cjs`，但未建目录）。

---

## 七、Agent-OS 最佳实践缺口（1 项）

### A-1 没有 `agent-os/` 标准目录
**问题**：项目已将代码标准拆入 `.claude/rules/`，但缺少 Agent-OS 建议的 `agent-os/standards/index.yml` 索引，导致跨工具可发现性差。  
**方案（可选）**：建立 `agent-os/standards/index.yml` 作为 `.claude/rules/` 文件的索引（不迁移内容，只建立指针），并创建 `agent-os/product/` 存放使命/路线图/技术栈摘要。

---

## 执行优先级

| 优先级 | 分类 | 理由 |
|--------|------|------|
| P0（立即） | Z-4（cookies.txt） | 安全风险 |
| P1（本次迭代） | D-1（角色双份）、D-3/D-4（docs 散落 prd/tech）、三、（docs 根目录清理） | 违反单一来源，影响日常协作 |
| P2（下次迭代） | Z-1/Z-2/Z-3（僵尸文件）、B-1（backend 脚本）、F-1（截图）、O-2/O-3（openspec 补全） | 整洁度问题 |
| P3（可选） | A-1（agent-os 目录）、O-1（命名约定文档化） | 最佳实践对齐 |

---

## 归档后目标目录结构（docs/ 层）

```
docs/
├── ARCHITECTURE.md          ← 保留（高频）
├── TESTING.md               ← 保留（CLAUDE.md @引用）
├── RISK_REGISTER.md         ← 保留（持续维护）
├── references-mcp-servers.md ← 保留（活跃使用）
├── archive/                 ← 已完成流水线产物、历史文件
│   ├── mvp/
│   ├── incidents/
│   ├── roles-legacy/        ← docs/roles/ 原有角色文件
│   ├── spec25/
│   ├── spec29/
│   └── *.md
├── diagrams/                ← 不变
├── prd/                     ← 所有 prd-*.md 集中此处
├── specs/                   ← 仅保留规格文档（清理 IMPL_NOTES）
├── tech/                    ← 所有 tech-*.md 集中此处
└── tests/                   ← qa-*.md 测试用例（需新建）
```
