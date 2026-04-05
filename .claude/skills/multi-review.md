---
name: multi-review
description: Multi-model code review — MiniMax does first pass, Gemini checks cross-module impact, Opus does final security audit. More thorough than single-model /review.
user_invocable: true
---

# /multi-review — 三模型联合 Code Review

比 `/review` 更彻底：三个模型从不同视角审查代码。

## 流程

### Pass 1: MiniMax-M1 — 基础质量检查（快速、低成本）

通过 MiniMax API 执行：
- 代码风格和约定一致性
- TypeScript 类型完整性
- Python Pydantic 模型规范
- 中文错误消息质量
- 命名规范（前端 PascalCase / 后端 snake_case）
- 明显的逻辑错误

Prompt 要点：
```
审查以下代码变更，关注：代码风格、命名规范、类型完整性、中文消息质量、明显逻辑错误。
按 P0/P1/P2 分级输出问题。
```

### Pass 2: Gemini 2.5 Pro — 跨模块影响分析（大上下文）

通过 gemini_chat (model: gemini-2.5-pro) 执行：
- 加载变更文件 + 所有相关依赖文件
- 分析修改对其他模块的影响
- 检查 API 契约一致性（前后端接口是否对齐）
- 数据库 schema 变更的影响范围
- 是否有遗漏的文件需要同步修改

Prompt 要点：
```
以下是代码变更及其依赖的上下文文件。分析：
1. 变更对其他模块的影响
2. 前后端 API 契约是否一致
3. 是否有遗漏的文件需要同步修改
4. 数据库变更是否需要迁移脚本
```

### Pass 3: Opus 4.6 — 安全终审（当前会话直接执行）

由 Opus 亲自执行（不委派）：
- 认证/授权逻辑正确性
- 加密实现安全性
- SQL 注入 / XSS / CSRF 风险
- 敏感数据泄露风险
- 权限检查前后端一致性
- 最终 Verdict 决定

### 汇总报告

将三个 Pass 的结果合并为一份报告：

```
## Multi-Model Review

### Pass 1: 基础质量 (MiniMax-M1)
{minimax_findings}

### Pass 2: 影响分析 (Gemini 2.5 Pro)
{gemini_findings}

### Pass 3: 安全终审 (Opus 4.6)
{opus_findings}

---

### 合并结论

**P0 Blockers:**
- [ ] ...

**P1 Warnings:**
- [ ] ...

**P2 Suggestions:**
- [ ] ...

**Verdict: APPROVE / REQUEST CHANGES / NEEDS DISCUSSION**
（基于三个模型的综合判断，P0 一票否决）
```
