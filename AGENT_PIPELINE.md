# Agent 执行流水线 v3

> 目标：多模型分工协作，Token 高效流转，链路可审计，边界清晰。

---

## 参与角色

| 角色 | 模型 | 职责定位 |
|------|------|---------|
| Human | — | PRD 提供者、业务确认者、最终验收者 |
| Opus | Claude Opus 4 | 架构设计、终审把关 |
| Flash | Gemini 2.5 Flash | Context 压缩、机械 QA、文档同步 |
| MiniMax | MiniMax 2.7 | 填充式实现、自愈修复 |

---

## 完整流水线

```
Human 提供需求（1-2 段话）
       ↓
Opus 起草 PRD.md + SPEC.md
       ↓
Human 确认 PRD（业务层）→ 解锁流水线
       ↓
  阶段一（设计确认）
  阶段二（实现）
  阶段三 A（机械 QA）
  阶段三 B（文档同步）
  阶段四（终审）
       ↓
Human 最终 review PRD 变更 + 代码
       ↓
合并
```

---

## 阶段 0：需求输入（Human → Opus）

### Human 提供（最低限度）
- 一段话描述需求（背景 + 目标）
- 业务约束（非技术）
- 优先级 / 截止时间

### Opus 产出两份文件

#### PRD.md（Human 可阅读的业务版）

```markdown
# PRD.md

## 1. Problem Statement
（业务问题是什么）

## 2. User Story
（用户视角：作为 X，我希望 Y，以便 Z）

## 3. Business Constraints
（业务层约束：合规、权限、业务规则）

## 4. Success Criteria（业务层面）
（如何衡量这个需求成功了）
```

#### SPEC.md（技术团队版）

```markdown
# SPEC.md

## 1. Overview
（1-2 句，说明目标）

## 2. Non-Goals
（明确不做什么，避免实现阶段偷偷扩需求）

## 3. Acceptance Criteria
- 输入 A → 输出 B
- 异常场景 X → 抛错/返回 Y
- 性能约束：响应时间 ≤ X ms
- 兼容性约束：Python 3.x / Node 18+

## 4. Change Budget
- 可修改文件范围：a.py, b.py
- 禁止触碰模块：core/auth.py, shared/utils.py
- 是否允许 schema 变更：否
- 是否允许 API 变更：仅新增，不得修改已有接口

## 5. Design
- 函数签名 + I/O 定义
- 核心算法伪代码
- 边界异常处理
- Design_Rationale（决策冲突与取舍记录）
```

### 门控

> Human 阅读 PRD.md，确认业务层意图
> **Human 点头后，流水线解锁，进入阶段一**

---

## 阶段一：架构设计 (Design Phase)

**执行者：** Opus

### 前置机制

> Gemini 2.5 Flash 扫描代码库 → 产出 `Context_Summary.md`

#### Flash 输出规范（只输出这 5 类，禁止散文）

| 字段 | 内容 |
|------|------|
| `Relevant Files` | 涉及改动的文件路径列表 |
| `Current Behavior` | 现有实现逻辑（1-3 句） |
| `Existing Constraints` | 硬约束：依赖、接口、向后兼容要求 |
| `Dependency / Call Chain` | 上游调用方、下游依赖 |
| `Potential Risks` | 风险点列表（可不处理，但必须标注） |

### Opus 职责

- 基于 `Context_Summary.md` 补充 `SPEC.md` 的 Design 章节
- 输出设计决策说明

### 门控

> Opus 输出 SPEC.md → MiniMax 阅读 → 输出 `Clarification_Questions.md`（如有）→ Opus 回复 → 双方达成共识

---

## 阶段二：代码实现 (Implementation Phase)

**执行者：** MiniMax 2.7

### 策略

严格按 `SPEC.md` 填空式开发。

### 产出文件

> `IMPLEMENTATION_NOTES.md` — 记录实现过程中的决策、遇到的问题、临时方案

### MiniMax 权限边界（铁规则）

| 允许修改 | 禁止修改 |
|---------|---------|
| 实现代码（.py / .ts） | SPEC.md |
| 测试代码（仅限与 SPEC 一致的补充） | PRD.md |
| | 公共接口定义 |
| | 外部契约 |

### 自愈机制

> 测试报错 → 内部修复 → 重跑 → 直至通过
> **最多 3 次循环**，仍未通过输出 `IMPLEMENTATION_BLOCKER.md`，人工介入

### 若发现 SPEC 遗漏或冲突

> 输出 `SPEC_GAP_REPORT.md`，**回退给 Opus**，不得擅自决策

---

## 阶段三 A：机械验证 (Mechanical QA)

**执行者：** Gemini 2.5 Flash

### 职责（纯机械验证）

- Lint 检查（ESLint / flake8）
- 变量命名规约
- 格式化 / import order
- Docs drift 检查（文档与代码不一致）

---

## 阶段三 B：文档同步 (Documentation Sync)

**执行者：** Gemini 2.5 Flash

### 职责（偏语义整理）

- 更新 README.md（如有新增 API、使用示例）
- 补充内联注释
- 更新函数文档字符串

### 流量平替（独立容灾机制，不是第三职责）

> 若 Flash 触发 Rate Limit，MiniMax 2.7 暂代阶段三 A+B
> Rate Limit 结束后恢复原分工，不自动补跑

---

## 阶段四：终审与合入 (Final Approval)

**执行者：** Opus

### 产出文件（两段独立输出）

#### SPEC_Compliance_Check.md
> 代码是否照 SPEC 实现

#### RealWorld_Risk_Check.md
> SPEC 本身是否遗漏关键真实约束

### 判定逻辑

```
代码符合 SPEC + 无真实风险遗漏 → PASS（准予合并）

逻辑有误 → 输出 Refactor_Instructions.md（含修复示例）
         → 回传给 MiniMax 2.7 修复
         → 回到阶段三 A 重跑测试
         → Opus 再审
```

### Opus 可执行动作（量化版）

| 允许 | 禁止 |
|------|------|
| 小范围批注 | 跨文件重构 |
| 1-2 处微修复 | 接口改动 |
| 补一句注释 | 大段逻辑重写 |
| | 改动超出 Change Budget 范围 |
| | 以"优化"名义修改 SPEC.md |

---

## 完整制品清单

| 阶段 | 产出文件 | 必须 |
|------|---------|------|
| 阶段 0 | `PRD.md` | ✅ |
| 阶段 0 | `SPEC.md` | ✅ |
| 阶段 0 | `Context_Summary.md` | ✅ |
| 阶段一 | `Clarification_Questions.md` | 如有 |
| 阶段二 | `IMPLEMENTATION_NOTES.md` | ✅ |
| 阶段二 | `IMPLEMENTATION_BLOCKER.md` | 如有 |
| 阶段二 | `SPEC_GAP_REPORT.md` | 如有 |
| 阶段四 | `SPEC_Compliance_Check.md` | ✅ |
| 阶段四 | `RealWorld_Risk_Check.md` | ✅ |
| 阶段四 | `Refactor_Instructions.md` | 如有 |

---

## 迭代上限

| 场景 | 上限 |
|------|------|
| 阶段二自愈循环 | 3 次 |
| 阶段四返工次数 | 2 次 |
| 超限 | 人工介入，暂停流水线 |

---

## 铁规则汇总

1. **MiniMax 可以修实现，不可以私改 SPEC**
2. **Human 确认 PRD 前，Opus 不得进入实现阶段**
3. **所有交接均为文件交接，不以口头上下文传递**
4. **Opus 终审不得做大规模代码修改（量化标准见阶段四）**
5. **流量平替是独立容灾机制，不改变角色职责**
