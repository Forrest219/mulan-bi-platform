# Clear Conversation History

> Status: proposed

## Why

当前侧边栏仅支持单条删除对话（hover → 点击删除图标），没有批量清空功能。用户清理历史时需要逐条操作，体验差、效率低。

## What Changes

- 首页侧边栏"对话历史"区域新增"清空全部"按钮
- 点击后需用户确认（Modal 二次确认防止误操作）
- 确认后调用后端批量删除 API，逐条删除后清空本地 state 和 localStorage
- 清空完成后侧边栏显示空态

## User Interaction Flow

1. 用户在侧边栏底部点击"清空全部"按钮
2. Modal 弹出："确定清空所有历史对话？此操作不可恢复"
3. 用户点击"确认" → 调用 `DELETE /api/agent/conversations`（批量）
4. 清空完成 → 侧边栏回到空态，显示引导文案"开始一个新对话吧"

## Non-Goals

- 不做选择性批量删除（单选/多选）
- 不做回收站/恢复功能
- 不清空后端数据库，仅删除当前用户的对话记录

## Impact

- 前端：侧边栏 UI 改动、conversationStore 新增 `clearAllConversations` action
- 后端：新增批量删除 endpoint `DELETE /api/agent/conversations`
- 测试：新增清空功能的冒烟用例

## Success Metrics

- 用户可一键清空侧边栏所有对话
- 清空后刷新页面不出现历史记录
- 确认 Modal 可正确取消操作