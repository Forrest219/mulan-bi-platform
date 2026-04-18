# 多角色并行执行模板

用于需要多个角色同时启动、互不依赖的任务场景。

## 使用方式

```
/parallel <任务描述>
```

## 执行规则

以下角色组合可并行启动（无依赖关系）：

| 并行组 | 角色 | 条件 |
|--------|------|------|
| A | pm + designer | 需求澄清阶段，UI 方向与业务需求可同步展开 |
| B | architect + designer | SPEC 设计与交互设计可并行，最后对齐 |
| C | tester + fixer | tester 发现问题，fixer 同步修复不同模块 |
| D | reviewer（SPEC 维度）+ reviewer（风险维度） | 两维报告可独立撰写 |

## 并行任务指令格式

当前任务：$ARGUMENTS

**Agent 1 — [角色名]**
目标：[具体产出]
约束：[边界限制]
产出文件：[文件名]

---

**Agent 2 — [角色名]**
目标：[具体产出]
约束：[边界限制]
产出文件：[文件名]

---

**同步点**：两个 Agent 完成后，由 [角色] 对齐产出，解决冲突后进入下一阶段。

## 禁止并行的组合

- coder + reviewer（reviewer 必须在 coder 完成后才能审查）
- coder + fixer（同一代码库并发修改产生冲突）
- shipper + 任何开发角色（发布阶段代码必须冻结）

---

## Best Practice: Good vs Bad Dispatch

> **Few-shot 示例**：展示高质量 dispatch 指令与低质量指令的差异，供 AI 参照输出。

### 场景：需求澄清阶段（并行组 A：pm + designer）

---

#### ❌ Bad Dispatch（模糊、无边界、无产出文件）

```
Agent 1 — pm
目标：梳理需求
约束：无
产出文件：不限

Agent 2 — designer
目标：做设计
约束：无
产出文件：不限

同步点：两个 Agent 完成后对齐。
```

**问题**：
- 目标不可验收（"梳理需求"无完成标准）
- 两个 Agent 没有共享输入（designer 不知道 pm 在处理哪条需求）
- 同步点没有说明谁负责对齐、对齐什么、冲突怎么裁决

---

#### ✅ Good Dispatch（具体产出、边界清晰、依赖显式）

```
当前任务：为「DDL 合规检查」功能补充需求细节并确定交互方向

Agent 1 — pm
目标：输出 PRD.md，覆盖以下内容：
  - 用户故事（数据工程师视角，≥ 3 条 AC）
  - 触发条件与输入格式（SQL 文本 or 文件上传）
  - 成功/失败状态定义
约束：不涉及 UI 布局，不做技术选型，范围仅限本功能模块
产出文件：docs/prd/DDL_compliance_PRD.md

Agent 2 — designer
目标：输出交互说明，覆盖以下内容：
  - 上传入口位置与触发方式
  - 检查结果的展示形态（行内标注 or 独立报告页）
  - 错误状态与空状态设计
约束：不依赖 pm 产出，基于现有 UI 风格（参考 frontend/src/pages/）独立判断
产出文件：docs/design/DDL_compliance_interaction.md

同步点：两份文件均完成后，由 architect 执行对齐：
  - 检查 PRD AC 是否能被交互方案覆盖
  - 冲突由 Human 裁决后再进入 SPEC 阶段
```

**为什么好**：
- 每个 Agent 的目标可用 checklist 验收
- 两个 Agent 互不依赖（designer 不等 pm），真正并行
- 同步点明确了：谁负责（architect）、对齐什么（AC 覆盖）、冲突怎么处理（Human 裁决）

---

### 核心规则（dispatch 时自检）

1. **目标可验收**：目标描述必须能被 checklist 核对，不写"做好 X"，写"产出 Y，包含 A、B、C"
2. **依赖显式**：Agent 2 若依赖 Agent 1 的产出，必须说明等待条件；若独立则明确写"不依赖"
3. **产出文件精确**：文件名 + 路径，不留空白
4. **同步点三要素**：负责人 + 对齐内容 + 冲突裁决路径
