# Agent 执行流水线 v5

> 目标：角色驱动分工协作，链路可审计，边界清晰。
> 角色详情：[`docs/roles/`](docs/roles/)

---

## 参与角色

| 短名 | 职责（一句话） | 详情 |
|------|--------------|------|
| **pm** | 需求 → PRD | [docs/roles/pm.md](docs/roles/pm.md) |
| **designer** | 交互 + 视觉方向 | [docs/roles/designer.md](docs/roles/designer.md) |
| **architect** | Context_Summary + SPEC | [docs/roles/architect.md](docs/roles/architect.md) |
| **coder** | 按 SPEC 填空式开发 | [docs/roles/coder.md](docs/roles/coder.md) |
| **tester** | 阶段二产出验收 | [docs/roles/tester.md](docs/roles/tester.md) |
| **fixer** | 补测试 / 修 bug / 覆盖率达标 | [docs/roles/fixer.md](docs/roles/fixer.md) |
| **reviewer** | 两维独立复核 | [docs/roles/reviewer.md](docs/roles/reviewer.md) |
| **shipper** | 审计脚本 + 发布 checklist | [docs/roles/shipper.md](docs/roles/shipper.md) |
| **Human** | 业务确认 / 最终验收 | — |

---

## 流水线阶段跳转

```
Human 提需求
    ↓
[阶段 0] pm → PRD.md ──► Human 确认（门控）
    ↓
[阶段 0] designer → 交互说明（涉及 UI 时）
    ↓
[阶段 0] architect → Context_Summary.md + SPEC.md
    ↓
[阶段一] architect + coder 澄清对齐
    ↓
[阶段二] coder → 实现 + IMPLEMENTATION_NOTES.md
    ↓
[阶段二] tester → TESTER_PASS.md / TESTER_FAIL.md（失败 → 回阶段二）
    ↓
[阶段三] fixer → 补测试 + 修 bug + 覆盖率 ≥ 50%
    ↓
[阶段四] reviewer → SPEC_Compliance_Check.md + RealWorld_Risk_Check.md
         FAIL → Refactor_Instructions.md → fixer → reviewer（最多 2 次）
    ↓
[Audit]  shipper 运行 scripts/audit-todos.sh + scripts/audit-adrs.sh（任意失败阻塞）
    ↓
[阶段五] shipper → RELEASE_NOTES.md + 回滚方案
    ↓
Human 最终 review + 合并
```

---

## 制品清单

| 阶段 | 执行者 | 产出文件 | 必须 |
|------|--------|---------|------|
| 0 | pm | `PRD.md` | ✅ |
| 0 | designer | 交互说明 | 涉及 UI |
| 0/一 | architect | `Context_Summary.md` | ✅ |
| 0/一 | architect | `SPEC.md` | ✅ |
| 一 | coder | `Clarification_Questions.md` | 如有 |
| 二 | coder | `IMPLEMENTATION_NOTES.md` | ✅ |
| 二 | coder | `SPEC_GAP_REPORT.md` | 如有 |
| 二 | coder | `IMPLEMENTATION_BLOCKER.md` | 如有 |
| 二 | tester | `TESTER_PASS.md` / `TESTER_FAIL.md` | ✅ |
| 四 | reviewer | `SPEC_Compliance_Check.md` | ✅ |
| 四 | reviewer | `RealWorld_Risk_Check.md` | ✅ |
| 四 | reviewer | `Refactor_Instructions.md` | 如有 |
| 五 | shipper | `RELEASE_NOTES.md` | ✅ |

---

## 迭代上限

| 场景 | 上限 |
|------|------|
| coder 自愈循环 | 3 次 |
| reviewer 返工 | 2 次 |
| 超限 | 人工介入，暂停流水线 |

---

## 铁规则

1. **coder 可以修实现，不可以私改 SPEC**
2. **Human 确认 PRD 前，coder 不得进入实现阶段**
3. **所有交接均为文件交接，不以口头上下文传递**
4. **reviewer 不得做大规模代码修改**（详见 `.claude/rules/review-constraint.md`）
5. **Final Approval 必须输出 SPEC 合规 + 真实风险两维报告**
6. **禁止救急方案；紧急例外走 ADR 登记（≤14 天），过期阻塞发布**
7. **交接制品命名严格遵循制品清单，禁止使用 `HANDOVER.md` 等非规范名称**
   - coder 阶段唯一合法交接文件名：`IMPLEMENTATION_NOTES.md`
   - `check-handover.sh` 钩子检测到非法命名**立即阻塞写入，不得绕过**
   - 新增制品名须先修改本文件制品清单，再同步更新钩子白名单

> 规则编号永不重用、永不跳号。废止的规则保留编号并标注 `(Deprecated)`。
