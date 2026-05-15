# docs/ 重组任务清单

> 关联计划：[docs-reorg-plan.md](docs-reorg-plan.md)
> 执行方式：按编号顺序，完成一项打一个 ✅

---

## 第一批（高风险修复）

### T1-A 安全：处理凭据文件
- [ ] 确认 `docs/UAT-ConnectedApp密钥.md` 内容（真实密钥还是示例）
- [ ] 若含真实密钥：迁移至 1Password / .env.local，然后 `git rm docs/UAT-ConnectedApp密钥.md`
- [ ] 确认 `.gitignore` 已覆盖此类文件（`*密钥*.md`）
- [ ] 如果已在 git history 中，考虑是否需要 `git filter-repo` 清除

### T1-B 清理 docs/ 根目录 review 产出物
```bash
git mv docs/SPEC_Compliance_Check.md docs/archive/
git mv "docs/SPEC_Compliance_Check__data_agent.md" docs/archive/
git mv docs/RealWorld_Risk_Check.md docs/archive/
git mv docs/RETROSPECTIVE_SPEC25.md docs/archive/
```
- [ ] 执行上述命令
- [ ] `git commit -m "chore(docs): archive review artifacts from docs root"`

### T1-C 清理 docs/roles/ 流程产出物
```bash
git mv "docs/roles/Context_Summary__sql-agent-spec-29.md" docs/archive/
git mv "docs/roles/SPEC_Review__sql-agent-spec-29.md" docs/archive/
```
- [ ] 执行上述命令
- [ ] `git commit -m "chore(docs): move misplaced pipeline artifacts out of roles/"`

### T1-D 清理 docs/specs/ 实现产出物
```bash
git mv docs/specs/bi-events-extra-data-fix-IMPLEMENTATION_NOTES.md docs/archive/
git mv docs/specs/spec25/IMPLEMENTATION_NOTES.md docs/archive/
```
- [ ] 执行上述命令
- [ ] `git commit -m "chore(docs): move IMPLEMENTATION_NOTES out of specs/"`

### T1-E 更新 specs/README.md
- [ ] 在 README 末尾附录区补录以下 spec（状态待确认）：
  - `51-vanna-integration-spec.md`
  - `52-docker-one-click-deployment-spec.md`
  - `53-home-query-result-csv-download-plan.md`
  - `54-data-agent-transparent-mcp-proxy-plan.md`
  - `55-help-agent-page-context-registry-plan.md`
- [ ] 在重复编号处补注说明（26A、27B、30-handover、31/36 test-cases）
- [ ] `git commit -m "docs(specs): update README to include spec 51-55"`

---

## 第二批（批量目录整理）

### T2-A 建立 docs/ops/，迁入运营文档
```bash
mkdir -p docs/ops
git mv docs/INCIDENT_REPORT_2026-05-10_SYS-001_LOGIN.md docs/ops/
git mv "docs/MVP_测试指引.md" docs/ops/
git mv "docs/MVP_验证记录.md" docs/ops/
git mv "docs/MVP_外部服务配置指引.md" docs/ops/
git mv docs/PM_INVESTIGATION_20260419.md docs/archive/
git mv docs/PM_LLM_CONFIG_FEEDBACK.md docs/archive/
git mv docs/DEV_PROGRESS.md docs/archive/
```
- [ ] 执行上述命令
- [ ] `git commit -m "chore(docs): create ops/ dir and migrate operational docs"`

### T2-B 归并 PRD 至 docs/prd/
```bash
git mv docs/prd-database-monitor.md docs/prd/
git mv docs/prd-llm-layer.md docs/prd/
git mv docs/prd-status.md docs/prd/
git mv docs/prd-status-spec24-rollout-plan.md docs/prd/
git mv docs/prd-tableau-mcp.md docs/prd/
git mv docs/prd-tableau-v2.md docs/prd/
```
- [ ] 执行上述命令
- [ ] `git commit -m "chore(docs): consolidate all PRDs under docs/prd/"`

### T2-C 归并 tech-*.md 至 docs/tech/
```bash
git mv docs/tech-capability-audit-v1.md docs/tech/
git mv docs/tech-data-governance.md docs/tech/
git mv docs/tech-embedding-retrieval.md docs/tech/
git mv docs/tech-home-search.md docs/tech/
git mv docs/tech-homepage-askbar.md docs/tech/
git mv docs/tech-mcp-client-rewrite.md docs/tech/
git mv docs/tech-menu-restructure.md docs/tech/
git mv docs/tech-semantic-publish-logs.md docs/tech/
```
- [ ] 执行上述命令
- [ ] `git commit -m "chore(docs): move tech-*.md into docs/tech/"`

### T2-D 解决 specs/ 重复编号
```bash
git mv docs/specs/26-viz-agent-addendum.md docs/specs/26A-viz-agent-addendum.md
git mv docs/specs/27-rollout-plan.md docs/specs/27B-rollout-plan.md
git mv docs/specs/30-metrics-agent-handover.md docs/archive/
mkdir -p docs/specs/testcases
git mv docs/specs/31-governance-dqc-pipeline-test-cases.md docs/specs/testcases/
git mv docs/specs/36-data-agent-architecture-test-cases.md docs/specs/testcases/
```
- [ ] 执行上述命令
- [ ] 更新 `docs/specs/README.md` 中对应的链接
- [ ] `git commit -m "chore(docs): fix duplicate spec numbers, move test-cases to testcases/"`

### T2-E 清理 docs/ 根目录剩余杂项
- [ ] 确认 `docs/DESIGN_SPEC_HOMEPAGE_V2.md` 是否仍有效 → 有效归 specs/，过期归 archive/
- [ ] 确认 `docs/semantic-governance-spec-v0.1.md` 对应哪个编号 spec → 归并或 archive
```bash
git mv docs/design-reference-open-webui.md docs/tech/
git mv docs/qa-llm-config-test-cases.md docs/specs/testcases/
git mv docs/SPEC_DEVELOPER_PROMPT_TEMPLATE.md docs/specs/
git mv docs/references-mcp-servers.md docs/tech/
```
- [ ] 执行上述命令
- [ ] `git commit -m "chore(docs): clean up remaining scattered files in docs root"`

---

## 完成验证

```bash
cd mulan-bi-platform

# 根目录 md 只剩 3 个
echo "=== docs root ===" && ls docs/*.md

# roles/ 只剩角色定义
echo "=== roles ===" && ls docs/roles/

# specs/ 无 IMPLEMENTATION_NOTES
echo "=== specs check ===" && ls docs/specs/*IMPLEMENTATION* 2>/dev/null && echo "FAIL" || echo "PASS"

# prd/ 汇总
echo "=== prd ===" && ls docs/prd/

# tech/ 汇总
echo "=== tech ===" && ls docs/tech/
```

---

## 状态

- 第一批：⬜ 未开始
- 第二批：⬜ 未开始（等第一批完成后执行）
