# Tasks

- [x] CCH-01: 后端新增 `DELETE /api/agent/conversations` 批量删除 endpoint
- [ ] CCH-02: 前端 conversationStore 新增 `clearAllConversations` action
- [ ] CCH-03: 侧边栏底部新增"清空全部"按钮
- [ ] CCH-04: 实现确认 Modal 组件（二次确认防误操作）
- [ ] CCH-05: 清空成功后侧边栏显示空态引导文案
- [ ] CCH-06: 新增清空功能的冒烟测试用例

## Dependencies

- CCH-01 须在 CCH-02 之前完成（前端依赖后端 API）
- CCH-03 须在 CCH-04 之前完成（先有按钮再加 Modal）

## Gate

- 后端批量删除 API 须返回成功状态后，前端才清空本地 state