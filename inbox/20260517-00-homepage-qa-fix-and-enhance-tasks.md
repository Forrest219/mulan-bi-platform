# 首页数据问答 — 修复 + 轻量增强任务书

> **角色分配**：本文档由 TL 交付 Coder 执行
> **优化范围**：首页问答链路（`/`）的会话管理、消息加载、审计日志
> **策略**：修复已知 bug + 小幅体验改善，不新增功能模块

---

## 背景

对首页问答链路进行了全面盘点，发现 6 项技术债 + 2 项体验粗糙点。以下 7 个 Task 按执行顺序排列，每个 Task 给出问题定位、改动指引和自检清单。

---

## T1: bi_agent_intent_log 迁移缺列 → 补迁移

**优先级**：P0（数据库先行）
**类型**：后端 / Alembic

### 问题

模型 `BiAgentIntentLog`（`services/data_agent/models.py:225-227`）定义了 `fallback_chain`（String(64)）和 `input_excerpt`（String(256)）两列，但迁移 `20260428_0002_add_bi_agent_intent_log.py` 未创建这两列。写入时若触及这两个字段会报 `UndefinedColumn` 错误。

### 改动

1. 生成新迁移：
   ```bash
   cd backend && alembic revision --autogenerate -m "add_fallback_chain_input_excerpt_to_intent_log"
   ```
2. 核查生成的迁移文件，确认只包含两列 ADD COLUMN，无其他意外变更
3. 两列均为 `nullable=True`，无 `server_default`

### 自检

- [ ] `cd backend && alembic upgrade head` 成功
- [ ] `cd backend && alembic downgrade -1 && alembic upgrade head` 回滚+重放成功
- [ ] 用 psql 确认 `SELECT column_name FROM information_schema.columns WHERE table_name='bi_agent_intent_log'` 包含 `fallback_chain` 和 `input_excerpt`
- [ ] 迁移文件中无多余表变更

---

## T2: addConversation() 调用旧 API → 清理残留

**优先级**：P0（消除写错表风险）
**类型**：纯前端

### 问题

`conversationStore.tsx:206` 的 `addConversation()` 调用了 `conversationsApi.create()`（旧 `/api/conversations` 端点），写入 `conversations` 表而非 `agent_conversations`。Agent 会话应由 `POST /api/agent/stream` 首条消息创建，`addConversation` 不应调任何后端。

### 改动文件

`frontend/src/store/conversationStore.tsx`

### 改动内容

1. `addConversation()` 函数（约 204-227 行）：移除 `try { await conversationsApi.create() }` 分支，只保留纯本地创建逻辑（generateId + dispatch）
2. 检查文件内 `conversationsApi` 是否还有其他引用；若无，移除 `import { conversationsApi } from '../api/conversations'`

### 自检

- [ ] `addConversation()` 函数体不再包含任何 `fetch` 或 API 调用
- [ ] 全局搜索 `conversationsApi` 确认无其他引用（若有则保留 import）
- [ ] `npm run type-check` 零错误
- [ ] 首页点击"新对话"→ URL 变为 `/`，AskBar 可输入，无控制台报错

---

## T3: nlq_query_logs 审计字段空置 → 补齐 intent + datasource_luid

**优先级**：P1
**类型**：纯后端

### 问题

`backend/app/api/agent.py` 中 6 处 `log_nlq_query()` 调用均未传入 `intent`、`datasource_luid`，导致审计表中这两个字段全部为 null。

### 改动文件

`backend/app/api/agent.py`

### 改动内容

逐一在 6 处调用点补齐参数（行号为当前版本近似值，以函数上下文定位）：

| 调用位置（上下文） | 补 `intent=` | 补 `datasource_luid=` |
|---|---|---|
| schema_inventory 工具禁用报错（~1165） | `"schema_inventory"` | `ds_info.get("luid")` 若作用域内可用，否则 `None` |
| schema_inventory 路由异常报错（~1231） | `"schema_inventory"` | 同上 |
| schema_inventory 成功（~1272） | `"schema_inventory"` | `ds_info.get("luid")` |
| fast MCP stream done（~726） | `"data_query"` | `ds_info.get("luid")` |
| ReAct agent done（~1381） | `intent_result.intent if intent_result else None` | `context.selected_datasource_luid if context else None` |
| ReAct agent error（~1436） | 同上 | 同上 |

> **不补 `vizql_json`**：Agent 路径无直接 VizQL 产物，强填无意义。

### 自检

- [ ] `cd backend && python3 -m py_compile app/api/agent.py` 成功
- [ ] `grep -n "log_nlq_query" backend/app/api/agent.py` 每处调用都包含 `intent=` 和 `datasource_luid=` 参数
- [ ] 在首页发一个查数问题，然后查库：
  ```sql
  SELECT intent, datasource_luid FROM nlq_query_logs ORDER BY id DESC LIMIT 1;
  ```
  确认两个字段非 null（查数场景）
- [ ] `cd backend && pytest tests/ -x -q` 全部通过

---

## T4: 对话删除静默失败 + 改名 window.alert → toast 提示

**优先级**：P1
**类型**：纯前端

### 问题

1. `deleteConversation()`（conversationStore.tsx:241-249）catch 块为空，后端失败仍从本地移除，前后端状态不一致
2. `updateConversationTitle()`（conversationStore.tsx:259）失败时用 `window.alert()`，阻塞浏览器

### 改动文件

`frontend/src/store/conversationStore.tsx`

### 改动内容

**删除**：将 dispatch 移到 try 块内（后端成功才移除本地状态），catch 内不 dispatch，改为通知调用方失败。

```typescript
// 改后伪码
const deleteConversation = useCallback(async (id: string): Promise<void> => {
  try {
    await agentConversationsApi.deleteConversation(id);
    dispatch({ type: 'DELETE_CONVERSATION', payload: id });
  } catch {
    throw new Error('删除失败，请稍后重试');
  }
}, []);
```

调用方 `ConversationBar.tsx`（约 108-120 行）在 catch 中展示内联 toast（项目无全局 toast 库，用 `useState + setTimeout` 自制，参考 `pages/account/profile/page.tsx:55` 的模式）。

**改名**：将 `window.alert(...)` 替换为同样的内联 toast 模式，保留乐观回滚逻辑不变。

### 自检

- [ ] 全局搜索 `window.alert` 确认 `conversationStore.tsx` 中无残留
- [ ] `npm run type-check` 零错误
- [ ] 模拟后端失败测试：在 DevTools Network 中 block `DELETE /api/agent/conversations/*`，点击删除→对话应仍留在列表 + 出现中文提示
- [ ] 模拟改名失败：block `PATCH /api/agent/conversations/*`，编辑标题→标题应回滚到旧值 + 出现中文提示
- [ ] 正常路径：删除成功对话消失，改名成功标题更新

---

## T5: 会话列表 limit=20 硬编码 → 支持分页参数

**优先级**：P1
**类型**：前后端联动

### 问题

`GET /api/agent/conversations` 硬编码 `limit=20`（agent.py:1466），超过 20 条对话不可见且无分页参数。

### 改动文件

- `backend/app/api/agent.py` — `list_conversations` 端点
- `frontend/src/store/conversationStore.tsx` — 初始化加载
- `frontend/src/api/agent.ts` — `agentConversationsApi.list()` 增加参数

### 改动内容

**后端**：`list_conversations` 端点签名增加两个 Query 参数：

```python
def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
```

透传给 `session_mgr.get_user_conversations(user_id=..., status="active", limit=limit, offset=offset)`。检查 `get_user_conversations` 方法是否已支持 `offset` 参数，若不支持则同步添加。

**前端 API 层**：`agentConversationsApi.list()` 增加可选参数 `{ limit?: number; offset?: number }`，拼入 URL query string。

**前端 Store**：初始化加载时传 `limit=50`（替代后端默认 20）。

### 自检

- [ ] `curl "http://localhost:8000/api/agent/conversations?limit=5" -b cookie` 只返回 5 条
- [ ] `curl "http://localhost:8000/api/agent/conversations?limit=50&offset=0" -b cookie` 正常返回
- [ ] 后端 `python3 -m py_compile app/api/agent.py` 成功
- [ ] 前端 `npm run type-check` 零错误
- [ ] 首页侧边栏加载对话列表无异常

---

## T6: 消息加载 limit=50 截断 → "加载更早的消息"

**优先级**：P2
**类型**：前后端联动

### 问题

`GET /api/agent/conversations/{id}/messages` 硬编码 `limit=50, offset=0`（agent.py:1606），超 50 条消息被截断且无分页 UI。

### 改动文件

- `backend/app/api/agent.py` — `get_conversation_messages` 端点
- `frontend/src/api/agent.ts` — `agentConversationsApi.getMessages()` 增加参数
- `frontend/src/pages/home/page.tsx` — `loadConvHistory()` 分页逻辑
- `frontend/src/pages/home/components/MessageList.tsx` — 顶部"加载更多"按钮

### 改动内容

**后端**：同 T5 模式，端点签名增加 `limit` 和 `offset` Query 参数。

**前端 API 层**：`getMessages(id, { limit?, offset? })` 增加可选参数。

**前端页面逻辑**（`page.tsx` 的 `loadConvHistory`）：
1. 首次加载 `limit=50, offset=0`
2. 若返回恰好 50 条，记录 `hasMoreMessages=true`
3. 点击"加载更早的消息"时，`offset += 50` 再次请求，将结果 prepend 到 `historyMessages` 前面

**MessageList 组件**：新增 `onLoadMore?: () => void` 和 `hasMore?: boolean` prop。当 `hasMore=true` 时在消息列表最顶部渲染按钮：

```
┌────────────────────────────┐
│  ↑ 加载更早的消息            │  ← 仅 hasMore 时显示
├────────────────────────────┤
│  [历史消息 1]               │
│  [历史消息 2]               │
│  ...                       │
│  [实时消息]                 │
└────────────────────────────┘
```

按钮样式：`text-sm text-blue-500 hover:underline`，加载中显示 spinner。

### 自检

- [ ] `curl "http://localhost:8000/api/agent/conversations/{id}/messages?limit=2&offset=0" -b cookie` 只返回 2 条
- [ ] 后端 `python3 -m py_compile app/api/agent.py` 成功
- [ ] 前端 `npm run type-check` 零错误
- [ ] 找一个消息数 < 50 的对话，切换进入→不应出现"加载更多"按钮
- [ ] 找一个消息数 ≥ 50 的对话（或临时改 limit=2 测试），切换进入→顶部出现按钮→点击加载→更早消息 prepend 到列表顶部

---

## T7: 冒烟测试回归

**优先级**：P2
**类型**：纯前端测试

### 说明

T1-T6 改动完成后，运行全部相关冒烟测试确保无回归。

### 执行

```bash
cd frontend
npx playwright test tests/smoke/home-new-conversation.spec.ts
npx playwright test tests/smoke/homepage-conversation-flow.spec.ts
npx playwright test tests/smoke/home-ask-question.spec.ts
npx playwright test tests/smoke/homepage-agent-mode.spec.ts
```

### 自检

- [ ] 4 个冒烟测试全部 PASS
- [ ] 若有失败，定位是本次改动引起还是已有问题，修复后重跑

---

## Out of Scope（明确不做）

| 项 | 原因 |
|---|---|
| 服务端会话搜索 API | 新功能 |
| 会话置顶 / 收藏 | 新功能 |
| 对话导出 | 新功能 |
| `nlq_query_logs.vizql_json` 补齐 | Agent 路径无 VizQL 产物 |
| 旧 `/api/conversations` 全套废弃 | 影响面大，需独立评估 |
| 无限滚动会话列表 | 属于新功能，本次只开放分页参数 |

---

## 关键文件速查

| 文件 | 涉及 Task |
|---|---|
| `backend/app/api/agent.py` | T3, T5, T6 |
| `backend/services/data_agent/models.py` | T1（参考模型定义） |
| `backend/alembic/versions/`（新文件） | T1 |
| `frontend/src/store/conversationStore.tsx` | T2, T4 |
| `frontend/src/api/agent.ts` | T5, T6 |
| `frontend/src/pages/home/page.tsx` | T6 |
| `frontend/src/pages/home/components/MessageList.tsx` | T6 |
| `frontend/src/pages/home/components/ConversationBar.tsx` | T4（toast 展示） |

---

## 通用验证命令

每个 Task 完成后必须执行：

```bash
# 后端（改了 .py 时）
cd backend && python3 -m py_compile $(git diff --name-only | grep '\.py$')
cd backend && pytest tests/ -x -q

# 前端（改了 .ts/.tsx 时）
cd frontend && npm run type-check
cd frontend && npm run lint
cd frontend && npm test -- --run
```
