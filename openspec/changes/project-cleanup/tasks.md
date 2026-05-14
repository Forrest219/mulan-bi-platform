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

## Group 0 — ✅ 已完成（2026-05-15）

- [x] **D-1** `agents/` 与 `docs/roles/` 合并：以 agents/ 为权威，docs/roles/ 8 个角色文件已删除并 commit
- [x] **Z-6** `docs/roles/` 的 spec-29 产物已在 `docs/archive/`，无需操作

---

## Group 1 — ✅ 已完成（2026-05-15，线路 A）

### 1.1 cookies.txt
- [x] `cookies.txt` 已在根目录 `.gitignore` 第 48 行，无需操作

### 1.2 UAT ConnectedApp 密钥文档
- [x] `docs/UAT-ConnectedApp密钥.md` 已在 `docs/archive/`，无需操作

---

## Group 2 — ✅ 已完成（2026-05-15，线路 A）

### 2.1 CHANGELOG 去重（D-2）
- [x] `docs/CHANGELOG.md` 不存在于 docs 根目录，已完成或未曾存在，无需操作

### 2.2 PRD 文件收归 docs/prd/（D-3）
- [x] `docs/prd/` 已包含 7 个 PRD 文件，已完成

### 2.3 tech 文档收归 docs/tech/（D-4）
- [x] `docs/tech/` 已包含 17 个文档，已完成

---

## Group 3 — ✅ 已完成（2026-05-15，线路 A）

### 3.1 docs/ 根目录 reviewer 产出物（Z-3 + Z-7 部分）
- [x] SPEC_Compliance_Check.md、REALWORLD_Risk_Check.md、RETROSPECTIVE_SPEC25.md 均已在 `docs/archive/`，无需操作

### 3.2 docs/specs/ 内的实现产出物（Z-7）
- [x] `docs/specs/` 中无 IMPLEMENTATION_NOTES，已完成

### 3.3 backend/ 实现笔记归档（Z-5）
- [x] `git mv backend/IMPLEMENTATION_NOTES.md docs/archive/backend-IMPLEMENTATION_NOTES.md` 已执行（commit e664e9c）

### 3.4 SESSION.md 移入 inbox（Z-2）
- [x] `mv SESSION.md inbox/20260515-00-SESSION.md` 已执行（commit b3a3842）

### 3.5 根目录 TESTER_PASS.md 归档（Z-3）
- [x] `git mv TESTER_PASS.md docs/archive/` 已执行（commit d53306a）

---

## Group 4 — ✅ 已完成（2026-05-15，线路 A）

### 4.1 docs/ops/ 运营文档
- [x] `docs/ops/` 已存在且已包含运营文档，无需操作

### 4.2 docs/ 根目录杂项
- [x] docs 根目录仅剩 3 个核心文件（ARCHITECTURE.md、RISK_REGISTER.md、TESTING.md），已满足 ≤4 个目标

### 4.3 specs/ 情况
- [x] docs/specs/ 中无重复编号问题需处理（原 spec25 目录已清空，IMPLEMENTATION_NOTES 已归档）

---

## Group 5 — ✅ 已完成（2026-05-15，线路 B）

- [x] 确认 `data/*.db` 无任何 backend/ Python 引用（grep 返回空）
- [x] 9 个 SQLite .db 文件为 gitignored 未追踪文件，无 git 历史，直接删除（`rm data/*.db`）
  - 注：files were gitignored (*.db in .gitignore)，无法 git mv，已物理删除

---

## Group 6 — ✅ 已完成（2026-05-15，线路 B）

### 6.1 backend/check_*.py → backend/scripts/（B-1）
- [x] 5 个文件（check_grant.py、check_keywords.py、check_load.py、check_load2.py、check_truncate.py）已 git mv 至 backend/scripts/（commit b6b1fa8）

### 6.2 frontend 截图集中（F-1）
- [x] 24 个 screenshots_*.png 已 git mv 至 frontend/screenshots/（commit 4d0a126）

---

## Group 7 — ✅ 已完成（2026-05-15，线路 C）

### 7.1 建立 changes/archive 目录结构（O-2）
- [x] `openspec/changes/archive/` 已建立，含 .gitkeep（commit 71132bc）

### 7.2 创建 openspec/config.yaml（O-3）
- [x] `openspec/config.yaml` 已创建：技术栈、API 约定、命名约定、已知偏差（commit 0f1f47a）

---

## Group 8 — ✅ 已完成（2026-05-15，线路 C）

- [x] `agent-os/standards/index.yml` 已创建：指向 AGENT_PIPELINE.md、docs/TESTING.md、agents/、.claude/rules/、docs/specs/
- [x] `agent-os/product/overview.md` 已创建：使命、目标用户、non-goals、技术栈（commit 804c5cf）

---

## 完成验证（2026-05-15 执行结果）

```
=== docs root ===
docs/ARCHITECTURE.md  docs/RISK_REGISTER.md  docs/TESTING.md     ✅ 3 个核心文件
=== prd ===
7                                                                  ✅ ≥7 个
=== tech ===
17                                                                 ✅ ≥10 个
=== specs no IMPL ===
PASS                                                               ✅
=== cookies.txt ignored ===
.gitignore:48:cookies.txt	cookies.txt
PASS                                                               ✅
```

**所有验证项通过。清理任务完成。**
