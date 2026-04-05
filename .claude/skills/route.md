---
name: route
description: Smart model router — analyzes the current task and recommends which model (Opus/Gemini/MiniMax) to use, with reasoning. Call this when unsure which model fits best.
user_invocable: true
---

# /route — 智能模型路由

分析当前任务，推荐最佳模型并说明理由。

## 决策树

按以下优先级判断：

### → Opus 4.6（当前 Claude Code 直接执行）

触发条件（任一命中）：
- 涉及 `backend/app/core/` 下的安全模块（crypto.py, dependencies.py）
- 涉及认证流程（auth.py, AuthContext.tsx, Session/Cookie）
- 需要跨 3+ 模块的架构重构
- 需要多步工具调用（读文件 → 分析 → 编辑 → 测试）
- 复杂 Bug 根因分析
- 数据库迁移设计（Alembic migration）
- PR Review 终审

输出：`推荐：Opus 4.6 — 直接在当前会话中执行`

### → Gemini 2.5 Pro（/gemini）

触发条件（任一命中）：
- 需要同时理解 5+ 个文件的上下文
- 全项目级别的重构或影响分析
- 大批量 DDL/SQL 处理（>100 行 SQL）
- "这个项目的 XX 是怎么设计的" 类架构问答
- 需要对比多个大文件

输出：`推荐：Gemini 2.5 Pro — 请执行 /gemini`

### → Gemini 2.5 Flash（/gemini-flash）

触发条件（任一命中）：
- 批量生成测试（>3 个测试文件）
- 批量类型注解补全
- 简单 CRUD 脚手架
- 格式转换（YAML↔JSON↔SQL）
- 重复模式的代码生成

输出：`推荐：Gemini Flash — 请执行 /gemini-flash`

### → MiniMax-M1（/minimax）

触发条件（默认 + 以下场景）：
- 新增单个页面/组件/接口
- 常规功能开发和 Bug 修复
- 中文相关功能（语义标注、搜索理解、NLP）
- 文档和配置编写
- 日常编码任务（没有命中以上任何条件）

输出：`推荐：MiniMax-M1 — 请执行 /minimax`

## 输出格式

```
## 模型路由

任务：{简述用户任务}
复杂度：低 / 中 / 高
上下文需求：小（<5 文件）/ 中（5-15 文件）/ 大（>15 文件）
安全敏感：是 / 否

**推荐：{模型名}**
理由：{一句话}

执行方式：{直接执行 / 执行 /gemini / 执行 /minimax / 执行 /gemini-flash}
```
