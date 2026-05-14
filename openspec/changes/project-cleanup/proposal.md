# Proposal: Project Cleanup & Structure Alignment

> 创建时间：2026-05-15  
> 来源：`inbox/20260514-14-cleanup-proposal.md`  
> 状态：待执行

---

## Intent（为什么）

项目经过 40+ 个 spec 迭代后，遗留了三类结构性问题：

1. **单一来源原则被破坏**：同类文件分布在多处（docs/ 根目录、docs/prd/、docs/tech/ 并存；agents/ 与 docs/roles/ 重复），协作者无法确定权威位置。
2. **流水线产出物污染正式文档目录**：IMPLEMENTATION_NOTES、SPEC_Compliance_Check、Context_Summary 等阶段性产物混入 docs/specs/ 和 docs/ 根目录，与长期规格文档混淆。
3. **OpenSpec 工作流缺失关键目录**：`openspec/changes/` 不存在，变更生命周期无法追踪；`openspec/config.yaml` 缺失，无法向工具注入项目上下文。

---

## Scope（做什么）

| 类别 | 具体内容 |
|------|---------|
| 安全 | 确认 `cookies.txt` 已被 `.gitignore` 覆盖 |
| 单一来源治理 | 消灭重复文件；将 prd-\*.md、tech-\*.md 收入对应子目录 |
| 僵尸文件归档 | SQLite .db 文件、SESSION.md、TESTER_PASS.md（根目录版）、散落 IMPLEMENTATION_NOTES |
| docs/ 根目录清理 | 历史 reviewer 产物、MVP 文档、PM 调查报告、事故报告归入 archive/ 或 ops/ |
| 工程目录整理 | backend/check_\*.py → backend/scripts/；frontend 截图集中至 screenshots/ |
| OpenSpec 补全 | 建立 changes/、changes/archive/、config.yaml |

---

## Out of Scope（不做什么）

- 不删除任何有内容的文件，只移动位置（archive/ 是归宿，不是垃圾桶）
- 不修改任何 Python / TypeScript 源代码
- 不修改 Alembic 迁移脚本
- 不触碰 `data/*.db` 中的实际数据（仅移位）

---

## Approach（怎么做）

- 所有文件移动使用 `git mv`，保留 commit 历史
- 每个逻辑组合为一个独立 commit，方便回退
- 执行后运行验证脚本确认结构符合预期
- 已完成项：`agents/ vs docs/roles/` 合并（2026-05-15 完成）

---

## 已完成

- [x] **D-1** agents/ 与 docs/roles/ 合并：以 agents/ 为权威，docs/roles/ 8 个角色文件已删除，有价值内容已合并；新增 agents/designer.md
- [x] **Z-6** docs/roles/ 流程产出物：Context_Summary 和 SPEC_Review 已确认在 docs/archive/
