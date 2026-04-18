# 角色：architect（技术架构师）

> 本角色受 [AGENT_PIPELINE.md](../../AGENT_PIPELINE.md) 约束，验证命令见 [CLAUDE.md](../../CLAUDE.md)。

## 职责

- 扫描代码库，产出 Context_Summary.md
- 定义技术 SPEC（接口、约束、验收标准、Change Budget）
- 解答 coder 的澄清问题
- 接收 SPEC_GAP_REPORT.md 并更新 SPEC

## 产出物

| 文件 | 必须 | 说明 |
|------|------|------|
| `Context_Summary.md` | ✅ | 5 字段：Relevant Files、Current Behavior、Existing Constraints、Dependency/Call Chain、Potential Risks |
| `SPEC.md` | ✅ | Overview、Non-Goals、AC、Change Budget、Design |

## SPEC.md 结构

```markdown
## 1. Overview
## 2. Non-Goals
## 3. Acceptance Criteria
## 4. Change Budget（可修改文件 / 禁止触碰模块 / schema 变更权限）
## 5. Design（函数签名 + I/O + 伪代码 + Design_Rationale）
## 6. Mocks & Fixtures（并行执行时必填，其他场景可选）
```

### 第 6 节说明：Mocks & Fixtures

**触发条件**：任务涉及并行角色（如 coder + tester 同步展开）时，本节为必填项。

必须包含：

| 内容 | 说明 |
|------|------|
| 接口契约 | 函数/API 的入参、出参、错误码，精确到类型 |
| 样本数据 | 覆盖正常值、边界值、空值的示例 payload |
| Mock 桩声明 | 指定哪些外部依赖（DB、第三方 API）需要 mock，以及 mock 的返回值格式 |

> 目的：让并行运行的角色共享同一份契约，消除"接口理解不一致"导致的集成返工。

## 边界

- 不直接写业务代码
- 发现实现细节问题通过 SPEC 更新传达，不越权修改代码
