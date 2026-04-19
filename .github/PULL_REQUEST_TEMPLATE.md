## Summary (required)

<!-- 简洁描述这个 PR 做了什么，为什么要做。1-3 句话。 -->


## Type

<!-- 选中本次 PR 的类型（单选），必需 -->
- [ ] `feat:` 新功能
- [ ] `fix:` 错误修复
- [ ] `refactor:` 重构（不涉及功能变更）
- [ ] `perf:` 性能优化
- [ ] `docs:` 文档更新
- [ ] `test:` 测试相关
- [ ] `chore:` 构建/维护任务

## Breaking Change

<!-- 如有 breaking change，填写下方并说明迁移方案 -->
- [ ] 本 PR **包含** breaking change（需填写下方）
- [ ] 无 breaking change

Breaking Change 说明（选填，如适用）：


## Linked Issue

<!-- 关联的 Issue 或 Discussion，必需 -->
- Closes: #<!-- number -->
- 或 Implements: #<!-- number -->
- 或 Refs: #<!-- number -->


## Test Plan

<!-- 如何验证这个 PR 的正确性？列出具体操作步骤，必填 -->

1.
2.
3.


## Smoke Test Result

<!-- 本次改动涉及核心功能（登录/首页/问答/MCP/LLM/用户/权限），请附上本地冒烟测试结果 -->
<!-- 如不确定是否涉及，直接填 "未知，由 CI 判断" -->

- [ ] 已本地运行 `npm run smoke`（或 `cd frontend && npx playwright test`），结果：
  ```
  <!-- 粘贴测试结果 -->
  ```
- [ ] 不涉及核心功能，跳过
- [ ] 未知，由 CI 判断


## Screenshots / Recording

<!-- UI 改动必须提供截图或录屏 -->
- [ ] 有 UI 改动（截图附在下方）
- [ ] 无 UI 改动

截图：


## Backwards Compatibility

<!-- 检查是否影响现有功能 -->
- [ ] 确认向后兼容
- [ ] 有兼容性问题（已在上方 Breaking Change 说明）


## Notes for Reviewers

<!-- 任何评审者需要知道的事项，如：配置变更、依赖更新、特殊测试环境等 -->
