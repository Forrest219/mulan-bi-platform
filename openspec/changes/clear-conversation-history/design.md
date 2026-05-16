# Design

## Backend

### API Endpoint

**`DELETE /api/agent/conversations`**

- Request body: 无
- Response: `{ "deleted_count": <number> }`
- 权限：仅删除当前登录用户的对话（user_id 从 session 获取）
- 实现：调用意图按 ID 逐条删除（复用 `agent_conversations` 表 delete logic）

### Database

无新增表。复用现有 `agent_conversations` 表，delete by `user_id`。

---

## Frontend

### conversationStore

```ts
// 新增 action
clearAllConversations: () => Promise<void>

// 实现逻辑：
// 1. GET /api/agent/conversations 获取当前用户所有对话 ID
// 2. 逐条调用 DELETE /api/agent/conversations/{id}
// 3. 清空 localStorage['mulan_conversations']
// 4. dispatch({ type: 'CLEAR_ALL' })
```

### Sidebar Component

- 按钮位置：侧边栏底部，在对话列表下方
- 按钮样式：文字按钮，颜色 `#ef4444`（红色警示）
- 点击触发 Modal 确认

### Confirm Modal

- 标题：清空历史对话
- 内容：确定清空所有历史对话？此操作不可恢复。
- 操作按钮：取消（默认） + 确认（红色）
- 确认后执行 clearAllConversations

### Empty State

清空完成后，侧边栏对话列表显示：

```
开始一个新对话吧
```

---

## Error Handling

- 批量删除中途失败：已删除的不回滚，显示 toast "清空失败，请重试"
- 网络错误：toast 提示"网络错误，清空失败"