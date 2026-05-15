# docs/ 目录重组计划

> 创建日期：2026-05-14
> 背景：docs/ 根目录文件散乱，单一来源原则被多处破坏，存在安全风险。
> 权威来源：本文件。执行时以本文件为准，不以对话记录为准。

---

## 目标结构

```
docs/
├── ARCHITECTURE.md          ← 保留（全局架构总览）
├── TESTING.md               ← 保留（CLAUDE.md 引用）
├── RISK_REGISTER.md         ← 保留（长期维护）
│
├── prd/                     ← 所有 PRD 统一入口
├── specs/                   ← 技术规格书（编号体系）
├── tech/                    ← 技术方案 / 实施规划
├── roles/                   ← 仅角色定义（无过程产出物）
├── ops/                     ← 运营 / 事故 / MVP 文档（新建）
├── adr/                     ← 架构决策记录（确认位置）
└── archive/                 ← 已完成 / 废弃的过程产出物
```

---

## 批次划分

### 第一批：高风险修复（优先执行）

目标：消除安全风险、清理过程产出物污染、修复 README 缺口。

**1-A 安全**
- `docs/UAT-ConnectedApp密钥.md` → 从 docs/ 删除，内容转移至密钥管理方式（1Password / .env / Vault），确认加入 .gitignore

**1-B 清理 docs/ 根目录的 review 产出物**（移至 `docs/archive/`）
- `docs/SPEC_Compliance_Check.md`
- `docs/SPEC_Compliance_Check__data_agent.md`
- `docs/RealWorld_Risk_Check.md`
- `docs/RETROSPECTIVE_SPEC25.md`

**1-C 清理 docs/roles/ 的流程产出物**（移至 `docs/archive/`）
- `docs/roles/Context_Summary__sql-agent-spec-29.md`
- `docs/roles/SPEC_Review__sql-agent-spec-29.md`

**1-D 清理 docs/specs/ 的实现产出物**（移至 `docs/archive/`）
- `docs/specs/bi-events-extra-data-fix-IMPLEMENTATION_NOTES.md`
- `docs/specs/spec25/IMPLEMENTATION_NOTES.md`

**1-E 更新 specs/README**
- 补录 51～55 号 spec（目前全部缺失）
- 在附录区标注重复编号说明（26/27/30/31/36）

---

### 第二批：批量目录整理（可按序执行）

目标：将散落文件归入正确目录，建立缺失目录。

**2-A 建立 docs/ops/ 目录，迁入运营文档**
```
docs/INCIDENT_REPORT_2026-05-10_SYS-001_LOGIN.md → docs/ops/
docs/MVP_测试指引.md                              → docs/ops/
docs/MVP_验证记录.md                              → docs/ops/
docs/MVP_外部服务配置指引.md                      → docs/ops/
docs/PM_INVESTIGATION_20260419.md                 → docs/archive/
docs/PM_LLM_CONFIG_FEEDBACK.md                   → docs/archive/
docs/DEV_PROGRESS.md                             → docs/archive/
```

**2-B 归并 PRD 文件至 docs/prd/**
```
docs/prd-database-monitor.md         → docs/prd/
docs/prd-llm-layer.md                → docs/prd/
docs/prd-status.md                   → docs/prd/
docs/prd-status-spec24-rollout-plan.md → docs/prd/
docs/prd-tableau-mcp.md              → docs/prd/
docs/prd-tableau-v2.md               → docs/prd/
```
（`docs/prd/PRD-open-webui-query.md` 已就位，不动）

**2-C 归并 tech 文档至 docs/tech/**
```
docs/tech-capability-audit-v1.md     → docs/tech/
docs/tech-data-governance.md         → docs/tech/
docs/tech-embedding-retrieval.md     → docs/tech/
docs/tech-home-search.md             → docs/tech/
docs/tech-homepage-askbar.md         → docs/tech/
docs/tech-mcp-client-rewrite.md      → docs/tech/
docs/tech-menu-restructure.md        → docs/tech/
docs/tech-semantic-publish-logs.md   → docs/tech/
```

**2-D 解决 specs/ 重复编号**

| 当前文件 | 问题 | 处理方式 |
|----------|------|---------|
| `26-viz-agent-addendum.md` | 与 26-agentic-tableau-mcp 重号 | 重命名为 `26A-viz-agent-addendum.md` |
| `27-rollout-plan.md` | 与 27-infra-accounts 重号 | 重命名为 `27B-rollout-plan.md` |
| `30-metrics-agent-handover.md` | handover ≠ spec | 移至 `docs/archive/` |
| `31-governance-dqc-pipeline-test-cases.md` | 测试用例归 testcases | 移至 `docs/specs/testcases/` |
| `36-data-agent-architecture-test-cases.md` | 测试用例归 testcases | 移至 `docs/specs/testcases/` |

**2-E 清理 docs/ 根目录剩余杂项**
```
docs/DESIGN_SPEC_HOMEPAGE_V2.md      → docs/specs/（或 archive/，确认是否仍有效）
docs/design-reference-open-webui.md  → docs/tech/
docs/qa-llm-config-test-cases.md     → docs/specs/testcases/
docs/SPEC_DEVELOPER_PROMPT_TEMPLATE.md → docs/specs/
docs/references-mcp-servers.md       → docs/tech/
docs/semantic-governance-spec-v0.1.md → docs/specs/（或 archive/，确认编号）
```

---

## 执行后验证

```bash
# 根目录只剩 3 个文件
ls docs/*.md | wc -l   # 预期 ≤ 3

# roles/ 只剩角色定义
ls docs/roles/*.md     # 预期 7 个角色文件

# specs/ 无 IMPLEMENTATION_NOTES
ls docs/specs/*IMPLEMENTATION* 2>/dev/null && echo "FAIL" || echo "PASS"

# prd/ 有完整 PRD 文件
ls docs/prd/*.md | wc -l   # 预期 ≥ 7
```

---

## 注意事项

- 所有移动操作用 `git mv`，保留 commit 历史
- 不删除任何有内容的文件，只移动位置（archive/ 是归宿，不是垃圾桶）
- CLAUDE.md 中 `@docs/TESTING.md` 引用路径在移动后需验证是否仍有效
- `docs/specs/README.md` 中的相对链接在重命名后需同步更新
