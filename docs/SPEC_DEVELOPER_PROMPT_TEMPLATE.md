# SPEC 开发交付 Prompt 模板（已退役）

> **状态：Deprecated — 2026-04-24**
>
> 本文件已拆分迁移，不再维护。

---

## 迁移去向

| 原内容 | 新位置 | 加载方式 |
|--------|--------|---------|
| 通用约束（5 条架构红线） | `.claude/rules/dev-constraints.md` | Claude Code 自动加载 |
| 前端 React 约束 | `.claude/rules/dev-constraints.md` | Claude Code 自动加载 |
| 模块特有约束（SPEC 07/14/15/17） | 各 SPEC 的 §11 开发交付约束 | 随 SPEC 文件一起提供给 coder |

## 新的工作流

1. **通用约束**：coder 无需手动查阅，`.claude/rules/dev-constraints.md` 会被自动注入上下文
2. **模块约束**：architect 在 SPEC §11 中填写，coder 读 SPEC 即可看到
3. **测试约束**：architect 在 SPEC §9.3 中填写，coder 读 SPEC 即可看到

> 模板结构见 `docs/specs/00-spec-template.md`
