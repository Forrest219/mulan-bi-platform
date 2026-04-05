---
name: minimax
description: Route a development task to MiniMax-M1 via API. Primary workhorse for daily coding — CRUD, pages, components, business logic, Chinese NLP, and cost-efficient bulk development. Also supports multimodal (image/video/TTS) via MCP.
user_invocable: true
---

# /minimax — MiniMax-M1 主力开发

将任务委派给 MiniMax-M1 处理。日常开发的默认选择：快、便宜、中文好。

## 两条通道

| 通道 | 方式 | 用途 |
|------|------|------|
| **Chat/Coding** | curl 调用 OpenAI 兼容 API | 编码、推理、中文 NLP |
| **多模态** | minimax-mcp-js MCP 工具 | 图片生成、视频生成、TTS 语音合成 |

## Chat/Coding 场景

- 日常功能开发（新页面、新接口、新组件）
- FastAPI 路由 + Pydantic 模型编写
- React 页面和组件开发
- DDL 检查规则实现
- 中文语义标注功能
- 中文 NLP 相关逻辑（搜索理解、意图识别）
- 单元测试编写
- 文档和配置编写
- Bug 修复（非安全类）

## 多模态场景（通过 MCP）

- 生成 UI 设计稿 / 图表配图 → `minimax_generate_image`
- 生成产品演示视频 → `minimax_generate_video`
- 生成中文语音旁白 → `minimax_text_to_speech`

## 执行流程（Chat/Coding）

1. **收集上下文** — 读取相关文件（保持精简，M1 上下文虽长但精简更高效）
2. **组装 prompt** — 文件内容 + 项目约定 + 任务指令
3. **调用 MiniMax API** — 通过 curl 调用 MiniMax Chat Completion API
4. **解析结果** — 提取代码块
5. **应用修改** — 通过 Edit/Write 工具写入文件
6. **验证** — 运行类型检查 / lint / 相关测试

## API 调用方式（Chat/Coding）

```bash
curl -s https://api.minimax.chat/v1/text/chatcompletion_v2 \
  -H "Authorization: Bearer $MINIMAX_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MiniMax-M1",
    "messages": [
      {"role": "system", "content": "<system_prompt>"},
      {"role": "user", "content": "<user_message>"}
    ],
    "temperature": 0.2,
    "max_tokens": 16384
  }'
```

环境变量 `MINIMAX_API_KEY` 需要预先配置（.mcp.json 中已配置同一 key）。
如未配置，提示用户设置：
```bash
export MINIMAX_API_KEY="your-key-here"
```

## System Prompt 模板

```
你是 Mulan BI Platform 的高级全栈开发者。

技术栈：
- 前端：React 19 + TypeScript + Vite + Tailwind CSS + React Router v7
- 后端：Python 3.11+ / FastAPI + SQLAlchemy 2.x + PostgreSQL 16
- 认证：Session/Cookie (HTTP Only) + PBKDF2-SHA256

编码约定：
- 前端：functional components, export default, Tailwind utility classes, fetch + credentials:'include', API_BASE from config
- 后端：Pydantic v2 BaseModel, HTTPException 中文消息, SQLAlchemy ORM, logger 日志
- 数据库：表前缀 auth_/bi_/ai_/tableau_, Alembic 迁移
- 错误消息使用中文

请直接输出可用的代码。对修改的文件标注文件路径。
```

## User Message 模板

```
以下是相关文件：

--- {filepath1} ---
{content1}

--- {filepath2} ---
{content2}

任务：{user_request}

输出格式：对每个需要修改的文件，标注完整路径，输出完整的修改后代码或 diff。
```

## 何时升级到 Opus

遇到以下情况时，标记任务需要 Opus 介入：
- M1 返回的代码有明显逻辑错误（重试一次后仍错）
- 涉及认证/加密/权限的安全敏感修改
- 需要跨 3 个以上模块的架构决策
- 复杂的并发/事务/竞态问题

## 注意事项

- M1 的 temperature 建议设为 0.1-0.3（代码生成更稳定）
- 单次请求控制在必要文件范围内，不要一次灌太多无关代码
- M1 中文注释和变量命名质量很高，不需要额外润色
