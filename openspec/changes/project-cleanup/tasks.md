# Tasks: Project Cleanup & Structure Alignment

> 关联提案：[proposal.md](proposal.md)  
> 参考详情：[inbox/20260514-14-cleanup-proposal.md](../../../inbox/20260514-14-cleanup-proposal.md)  
> 执行方式：按组顺序，完成一项打 ✅，每组 commit 一次

---

## 并行线路（多 coder 分工说明）

本次清理可拆分为三条互不依赖的执行线路，允许三个 coder 并行推进：

| 线路 | 负责 Groups | 触碰目录 | 执行约束 |
|------|------------|---------|---------|
| **线路 A（docs 专线）** | Group 1 → 2 → 3 → 4 | `docs/`, `.gitignore` | 组内必须顺序执行，每组独立 commit |
| **线路 B（工程专线）** | Group 5 + 6 | `data/`, `backend/`, `frontend/` | Group 5、6 可同时开工 |
| **线路 C（治理专线）** | Group 7 + 8 | `openspec/`, `agent-os/` | Group 7、8 可同时开工 |

**合并顺序**：三路并行完成后，按 A → B → C 顺序 merge 到 main（避免 conflict）。  
**线路 A 优先**：Group 1（安全）应第一个完成，不依赖其他线路。

---

## Group 0 — 已完成

- [x] **D-1** `agents/` 与 `docs/roles/` 合并（2026-05-15）
- [x] **Z-6** `docs/roles/` 的 spec-29 产物已在 `docs/archive/`，无需操作

---

## Group 1 — 安全

### 1.1 cookies.txt
- [ ] 确认 `cookies.txt` 是否在根目录 `.gitignore` 中
- [ ] 若未被忽略，立即追加：`echo 'cookies.txt' >> .gitignore && git add .gitignore`

### 1.2 UAT ConnectedApp 密钥文档
- [ ] 打开 `docs/UAT-ConnectedApp密钥.md`，确认是否含真实凭据
- [ ] 若含真实密钥：将内容转移至 1Password / .env.local，然后执行：
  ```bash
  git rm "docs/UAT-ConnectedApp密钥.md"
  echo '*密钥*.md' >> .gitignore
  git add .gitignore
  git commit -m "security: remove credential doc and block pattern in .gitignore"
  ```
- [ ] 若仅为示例：`git mv "docs/UAT-ConnectedApp密钥.md" docs/archive/`

---

## Group 2 — 单一来源治理

### 2.1 CHANGELOG 去重（D-2）
```bash
git mv docs/CHANGELOG.md docs/archive/
git commit -m "chore(docs): archive duplicate docs/CHANGELOG.md, root version is canonical"
```
- [ ] 执行上述命令

### 2.2 PRD 文件收归 docs/prd/（D-3）
```bash
git mv docs/prd-database-monitor.md docs/prd/
git mv docs/prd-llm-layer.md docs/prd/
git mv docs/prd-status.md docs/prd/
git mv docs/prd-status-spec24-rollout-plan.md docs/prd/
git mv docs/prd-tableau-mcp.md docs/prd/
git mv docs/prd-tableau-v2.md docs/prd/
git commit -m "chore(docs): consolidate all PRDs under docs/prd/"
```
- [ ] 执行上述命令

### 2.3 tech 文档收归 docs/tech/（D-4）
```bash
git mv docs/tech-capability-audit-v1.md docs/tech/
git mv docs/tech-data-governance.md docs/tech/
git mv docs/tech-embedding-retrieval.md docs/tech/
git mv docs/tech-home-search.md docs/tech/
git mv docs/tech-homepage-askbar.md docs/tech/
git mv docs/tech-mcp-client-rewrite.md docs/tech/
git mv docs/tech-menu-restructure.md docs/tech/
git mv docs/tech-semantic-publish-logs.md docs/tech/
git mv docs/design-reference-open-webui.md docs/tech/
git mv docs/references-mcp-servers.md docs/tech/
git commit -m "chore(docs): move all tech-*.md into docs/tech/"
```
- [ ] 执行上述命令

---

## Group 3 — 历史产出物归档

### 3.1 docs/ 根目录 reviewer 产出物（Z-3 + Z-7 部分）
```bash
git mv docs/SPEC_Compliance_Check.md docs/archive/
git mv "docs/SPEC_Compliance_Check__data_agent.md" docs/archive/
git mv docs/REALWORLD_Risk_Check.md docs/archive/
git mv docs/RETROSPECTIVE_SPEC25.md docs/archive/
git commit -m "chore(docs): archive reviewer artifacts from docs root"
```
- [ ] 执行上述命令

### 3.2 docs/specs/ 内的实现产出物（Z-7）
```bash
git mv docs/specs/bi-events-extra-data-fix-IMPLEMENTATION_NOTES.md docs/archive/
git mv docs/specs/spec25/IMPLEMENTATION_NOTES.md docs/archive/
rmdir docs/specs/spec25   # 清理已空目录
git commit -m "chore(docs): move IMPLEMENTATION_NOTES out of specs/"
```
- [ ] 执行上述命令

### 3.3 backend/ 实现笔记归档（Z-5）
```bash
git mv backend/IMPLEMENTATION_NOTES.md docs/archive/
git commit -m "chore(backend): move misplaced IMPLEMENTATION_NOTES to docs/archive/"
```
- [ ] 执行上述命令

### 3.4 SESSION.md 移入 inbox（Z-2）
```bash
mv SESSION.md "inbox/20260515-00-SESSION.md"
git add -A
git commit -m "chore: move SESSION.md to inbox (temporary file)"
```
- [ ] 执行上述命令

### 3.5 根目录 TESTER_PASS.md 归档（Z-3）
```bash
git mv TESTER_PASS.md docs/archive/
git commit -m "chore: archive root-level TESTER_PASS.md to docs/archive/"
```
- [ ] 执行上述命令

---

## Group 4 — docs/ 根目录清理

### 4.1 建立 docs/ops/ 并迁入运营文档
```bash
mkdir -p docs/ops
git mv "docs/INCIDENT_REPORT_2026-05-10_SYS-001_LOGIN.md" docs/ops/
git mv "docs/MVP_测试指引.md" docs/ops/
git mv "docs/MVP_验证记录.md" docs/ops/
git mv "docs/MVP_外部服务配置指引.md" docs/ops/
git mv docs/PM_INVESTIGATION_20260419.md docs/archive/
git mv docs/PM_LLM_CONFIG_FEEDBACK.md docs/archive/
git mv docs/DEV_PROGRESS.md docs/archive/
git commit -m "chore(docs): create ops/ dir and migrate operational/incident docs"
```
- [ ] 执行上述命令

### 4.2 清理 docs/ 根目录剩余杂项
- [ ] 确认 `docs/DESIGN_SPEC_HOMEPAGE_V2.md`：有效 → `docs/specs/`，过期 → `docs/archive/`
- [ ] 确认 `docs/semantic-governance-spec-v0.1.md`：有对应编号 spec → 合并或归档
```bash
git mv docs/qa-llm-config-test-cases.md docs/specs/testcases/   # 需先 mkdir -p docs/specs/testcases
git mv docs/SPEC_DEVELOPER_PROMPT_TEMPLATE.md docs/specs/
git commit -m "chore(docs): clean up remaining scattered files in docs root"
```
- [ ] 执行上述命令（需先 `mkdir -p docs/specs/testcases`）

### 4.3 specs/ 重复编号修复
```bash
git mv docs/specs/26-viz-agent-addendum.md docs/specs/26A-viz-agent-addendum.md
git mv docs/specs/27-rollout-plan.md docs/specs/27B-rollout-plan.md
git mv docs/specs/30-metrics-agent-handover.md docs/archive/
mkdir -p docs/specs/testcases
git mv docs/specs/31-governance-dqc-pipeline-test-cases.md docs/specs/testcases/
git mv docs/specs/36-data-agent-architecture-test-cases.md docs/specs/testcases/
git commit -m "chore(docs): fix duplicate spec numbers, move test-cases to testcases/"
```
- [ ] 执行上述命令
- [ ] 更新 `docs/specs/README.md`：修复重命名文件的链接，补录 spec 51–55

---

## Group 5 — SQLite 僵尸文件（Z-1）

- [ ] 确认 `data/` 下哪些 .db 文件还在被任何脚本引用：
  ```bash
  grep -r "\.db" backend/ --include="*.py" | grep -v "__pycache__" | grep "data/"
  ```
- [ ] 若无引用，移动至 docs/archive/sqlite-legacy-data/（或移出 git 追踪）：
  ```bash
  mkdir -p docs/archive/sqlite-legacy-data
  git mv data/*.db docs/archive/sqlite-legacy-data/
  git commit -m "chore: archive legacy SQLite files, project now uses PostgreSQL"
  ```

---

## Group 6 — 工程目录整理

### 6.1 backend/check_*.py → backend/scripts/（B-1）
```bash
git mv backend/check_grants.py backend/scripts/
git mv backend/check_keywords.py backend/scripts/
git mv backend/check_load.py backend/scripts/
git mv backend/check_truncate.py backend/scripts/
git commit -m "chore(backend): move check_*.py scripts to backend/scripts/"
```
- [ ] 执行上述命令（注意：若文件名与上述不符，先 `ls backend/check_*.py` 确认）

### 6.2 frontend 截图集中（F-1）
```bash
mkdir -p frontend/screenshots
git mv frontend/screenshots_*.png frontend/screenshots/
git commit -m "chore(frontend): consolidate screenshots into frontend/screenshots/"
```
- [ ] 执行上述命令（先 `ls frontend/screenshots_*.png` 确认文件名）

---

## Group 7 — OpenSpec 工作流补全

### 7.1 建立 changes 目录结构（O-2）
```bash
mkdir -p openspec/changes/archive
# changes/project-cleanup 已在此 change 中建立
git add openspec/changes/
git commit -m "chore(openspec): initialize changes/ and changes/archive/ directories"
```
- [ ] 执行上述命令

### 7.2 创建 openspec/config.yaml（O-3）
- [ ] 创建 `openspec/config.yaml`，内容包含：
  - 技术栈（React 19 / FastAPI / PostgreSQL 16）
  - API 约定（`/api` 前缀，JSON 响应）
  - 命名约定（表前缀 bi\_ / auth\_ / tableau\_ 等）
  - 说明当前 specs/ 命名为 `<number>-<name>.md` 格式（非标准，已知偏差）
```bash
git add openspec/config.yaml
git commit -m "chore(openspec): add config.yaml with project context"
```

---

## Group 8 — 可选：Agent-OS 标准索引（A-1）

- [ ] 创建 `agent-os/standards/index.yml`，作为 `.claude/rules/` 文件的索引（不迁移内容）
- [ ] 创建 `agent-os/product/`，放置使命/路线图/技术栈摘要

---

## 完成验证

```bash
cd mulan-bi-platform

# docs 根目录只剩核心文件（预期 ≤ 4 个）
echo "=== docs root ===" && ls docs/*.md

# prd/ 汇总（预期 ≥ 7 个）
echo "=== prd ===" && ls docs/prd/ | wc -l

# tech/ 汇总（预期 ≥ 10 个）
echo "=== tech ===" && ls docs/tech/ | wc -l

# specs/ 无 IMPLEMENTATION_NOTES（预期 PASS）
ls docs/specs/*IMPLEMENTATION* 2>/dev/null && echo "FAIL" || echo "PASS"

# cookies.txt 已被忽略
git check-ignore -v cookies.txt && echo "PASS" || echo "FAIL: not ignored"
```
