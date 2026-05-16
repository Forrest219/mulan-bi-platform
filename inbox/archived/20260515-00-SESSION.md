# SESSION.md — 首页对话框体验优化施工交底

> 创建日期：2026-04-19
> 施工批次：Batch 1-4 + Feedback API
> PM：Claude Sonnet 4.6
> 铁律：不得破坏"你有几个数据源"的现有连通性（已验收里程碑）

---

## 1. 已验收的里程碑（绝对不能退步）

| 里程碑 | 说明 | 关键路径 |
|-------|------|---------|
| M1 数据源连通性 | 用户可通过 ScopePicker 选择 Tableau 连接，提交问题后能收到 AI 回答 | `AskBar.submit()` → `POST /api/search/query` → `handle_meta_query_all` |
| M2 流式 SSE | 问题发送后，消息区出现三点动画，随后 token 逐步流出，最终 `isStreaming=false` | `useStreamingChat.sendMessage()` → `GET /api/chat/stream` → `ReadableStream` 消费 |
| M3 META 查询 | "你有几个数据源"等问题走 META 路径，跨所有活跃连接聚合返回 | `classify_meta_intent()` → `handle_meta_query_all()` |
| M4 追问继承 | 多轮对话中 conversation_id 持续传递，上下文不丢失 | `currentConversationId` state → `AskBar.conversationId` prop → `body.conversation_id` |
| M5 离线检测 | 断网时页面显示 amber 提示，恢复网络后自动回到上次状态 | `window.addEventListener('offline'/'online')` |

---

## 2. 本次施工范围

### Batch 1 — 结构性修复（前端）
- 消除双回复卡片（streaming 区与 SearchResult 同时出现）
- 用户消息气泡改为右对齐蓝色样式
- 消息展示区宽度从 `max-w-3xl` 改为 `max-w-4xl`

### Batch 2 — AI 消息操作区（前端，新建组件）
- 每条完成的 AI 消息底部渲染 `MessageActions` 组件（复制、点赞、踩）
- 点赞/踩调用 `POST /api/feedback`

### Batch 3 — 输入框打磨（前端）
- AskBar 外观微调（圆角、阴影、占位符、快捷键提示颜色）
- 流式中发送按钮变停止图标，点击中止 SSE

### Batch 4 — Loading 状态统一（前端）
- 删除外部 spinner，依赖气泡内三点动画
- 每条 AI 消息左上方加品牌标识（logo 小圆 + "木兰"）

### Feedback API（后端）
- 新建 `backend/app/api/feedback.py`，路由 `POST /api/feedback`
- 新建数据库表 `message_feedback`（Alembic migration）
- 在 `main.py` 注册路由

---

## 3. 禁止改动的文件/函数（Coder 红线）

以下文件/函数是已验收连通性的关键路径，**不得修改其行为**：

### 后端（绝对禁止改动）
| 文件 | 禁止改动的函数/内容 |
|-----|----------------|
| `backend/app/api/search.py` | `query()` 函数整体、`handle_meta_query_all()`、`handle_meta_query()`、所有 `_handle_meta_*` 私有函数 |
| `backend/app/api/chat.py` | `chat_stream()`、`_resolve_answer()`、`_stream_llm_response()` |
| `backend/app/main.py` | 已有的全部 `app.include_router()` 调用（只允许追加新路由） |
| `backend/services/llm/nlq_service.py` | `META_INTENT_KEYWORDS`、`classify_meta_intent()`、`execute_query()`、`one_pass_llm()` |
| `backend/services/tableau/mcp_client.py` | 全部（MCP 连接池，不可改动） |

### 前端（禁止改动核心逻辑）
| 文件 | 禁止改动的内容 |
|-----|--------------|
| `frontend/src/hooks/useStreamingChat.ts` | `sendMessage()` 的 fetch 地址和 SSE 解析逻辑；`stopStreaming()` 的 AbortController 行为（Batch 3 新增 `abort` 方法只能包装 `stopStreaming`，不能修改其实现） |
| `frontend/src/pages/home/components/AskBar.tsx` | `submit()` 函数内调用 `askQuestion()` 和 `onLoading(true)` 的逻辑；`connectionId` 的优先级判断逻辑（`useExternalConnection`）；`noConnection` 判断 |
| `frontend/src/pages/home/page.tsx` | `handleLoading()` 中 `sendMessage()` 的调用；`currentConversationId` 的管理逻辑；`handleResult()` 对 `conversationStore` 的写入 |
| `frontend/src/pages/home/context/ScopeContext.tsx` | 全部（ScopePicker 数据源） |

---

## 4. Batch 完成状态

- [x] Batch 1：结构性修复（双卡片消除 + 用户气泡右对齐 + 宽度调整）— bg-blue-600 / max-w-4xl 预存，双卡片 guard 已在 page.tsx
- [x] Batch 2：AI 消息操作区（MessageActions 组件 + POST /api/feedback 对接）— hover 显隐由 Hermes 补完 2026-04-22
- [x] Batch 3：输入框打磨（外观 + 停止按钮 + abort 方法）— rounded-3xl / placeholder / stop button 预存
- [x] Batch 4：Loading 状态统一（删 spinner + 品牌标识）— 品牌标识由 Hermes 补完 2026-04-22，外部 spinner 已不存在
- [x] Feedback API：后端新建（feedback.py + migration + main.py 注册）— 预存，runtime 验收待人工执行

---

## 5. 验收口径（Tester 用）

### 5.1 铁律回归（每个 Batch 完成后必须跑）

| 测试项 | 操作 | 预期结果 |
|-------|------|---------|
| META 连通性 | 在首页输入"你有几个数据源" | 页面显示 AI 流式回答，内容包含数据源数量，不出现 SearchResult 卡片 |
| SSE 流式 | 提交任意数据问题 | 气泡内三点动画 → token 逐渐展示 → 动画消失，不出现双回复卡片 |
| 多轮追问 | 连续提问 2 次 | 两次消息均在同一消息流中展示，conversation_id 相同（可从 Network 请求验证） |
| 停止流式 | 流式中点击停止按钮 | SSE 连接中断，气泡显示已生成的部分内容，`isStreaming` 变为 false |

### 5.2 Batch 1 验收

| 测试项 | 操作 | 预期结果 |
|-------|------|---------|
| 无双卡片 | 提交问题，等待流式完成 | 页面中只有 streaming 消息区，不出现 SearchResult 组件的白色卡片 |
| 用户消息气泡 | 查看消息展示区 | 用户消息显示在右侧，背景为蓝色（`bg-blue-600`），白色文字，无 `ml-8` |
| 消息区宽度 | 在 1440px 宽屏下查看 | 消息展示区宽度为 `max-w-4xl`，输入框保持 `max-w-3xl` |

### 5.3 Batch 2 验收

| 测试项 | 操作 | 预期结果 |
|-------|------|---------|
| 操作栏出现 | 将鼠标悬停在完成的 AI 消息上 | 消息底部出现复制、👍、👎 按钮 |
| 操作栏隐藏 | 将鼠标移离消息 | 操作栏消失（invisible 状态） |
| 复制功能 | 点击复制按钮 | 浏览器剪贴板中包含消息文本内容 |
| 点赞反馈 | 点击 👍 | Network 出现 `POST /api/feedback`，响应为 `{"ok": true}`，按钮变为激活态 |
| 踩反馈 | 点击 👎 | 同上，rating 字段为 "down" |

### 5.4 Batch 3 验收

| 测试项 | 操作 | 预期结果 |
|-------|------|---------|
| 圆角变化 | 查看输入框 | 外层容器圆角为 `rounded-3xl` |
| 占位符 | 清空输入框 | 占位符文字为"向木兰提问…" |
| 停止按钮 | 流式进行中 | 发送按钮变为停止图标（`ri-stop-circle-line`），点击后 SSE 中断 |
| 停止后可继续 | 停止后再次输入提问 | 可正常发送新问题，流式正常工作 |

### 5.5 Batch 4 验收

| 测试项 | 操作 | 预期结果 |
|-------|------|---------|
| 无外部 spinner | 提交问题后，流式开始前 | 页面中心不出现旋转圆圈 spinner |
| 三点动画 | 流式消息出现但内容为空时 | AI 气泡内显示三点动画 |
| 品牌标识 | 查看每条 AI 消息 | 左上方有小圆 logo（`w-5 h-5`）和"木兰"文字（`text-xs text-slate-400`） |

### 5.6 Feedback API 验收

| 测试项 | 操作 | 预期结果 |
|-------|------|---------|
| 未登录拒绝 | 不携带 token 调用 `POST /api/feedback` | 返回 401 |
| 正常写入 | 登录后调用 `POST /api/feedback`，携带合法 body | 返回 `{"ok": true}`，`message_feedback` 表新增一条记录 |
| user_id 注入 | 检查数据库记录 | `user_id` 和 `username` 来自 JWT 解析，不是前端传入 |
| rating 校验 | 传入 `rating: "maybe"` | 返回 422 Unprocessable Entity |
