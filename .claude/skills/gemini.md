---
name: gemini
description: Route a development task to Gemini 2.5 Pro via MCP. Use for large-context refactoring, cross-module analysis, bulk SQL/DDL work, and full-project understanding.
user_invocable: true
---

# /gemini — Gemini 2.5 Pro 开发协作

将当前任务委派给 Gemini 2.5 Pro 处理，利用其 1M token 上下文优势。

## 使用场景

- 大范围重构（需要同时理解多个模块）
- 跨模块影响分析（改一个接口，哪些地方受影响）
- 批量 DDL/SQL 校验和生成
- 全项目架构理解和问答
- 长文件分析（超大组件、长配置）

## 执行流程

1. **收集上下文** — 根据用户请求，读取所有相关文件内容
2. **组装 prompt** — 将文件内容 + 用户指令 + 项目约定（CLAUDE.md）打包
3. **调用 Gemini** — 通过 `gemini_chat` MCP 工具发送，使用 `gemini-2.5-pro` 模型，session 设为 `mulan-dev`
4. **接收结果** — 如果是代码修改，使用 `change_mode: true` 获取结构化 diff
5. **应用修改** — 将 Gemini 返回的修改通过 Edit 工具应用到本地文件
6. **验证** — 运行类型检查或相关测试确认修改正确

## 调用规范

```
gemini_chat 参数：
- model: "gemini-2.5-pro"
- session: "mulan-dev"
- change_mode: true（如果需要代码修改）
- message: 包含完整上下文的 prompt
```

## Prompt 模板

发送给 Gemini 的消息必须包含：

```
你是 Mulan BI Platform 的开发者。这是一个数据建模与治理平台。

技术栈：React 19 + TypeScript + Vite（前端）、FastAPI + SQLAlchemy 2.x + PostgreSQL 16（后端）

项目约定：
- 前端：Tailwind only，functional components，fetch + credentials: 'include'
- 后端：Pydantic v2，HTTPException 中文消息，SQLAlchemy ORM（禁止 raw SQL 拼接）
- 数据库表前缀：auth_、bi_、ai_、tableau_

以下是相关文件内容：
{files}

请完成以下任务：
{user_request}
```

## 注意事项

- Gemini 返回的代码需要 Opus 最终确认安全模块的修改
- 如果涉及认证/加密逻辑，标记为需要 Opus review
- session 保持为 `mulan-dev` 以维持对话上下文连续性
