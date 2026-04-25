# 测试规范

> 适用于 Mulan BI Platform 所有功能提交。CI 分两层执行，覆盖率门槛仅在 merge-to-main 阶段强制。

---

## CI 分层

| CI 阶段 | 触发时机 | 内容 |
|---------|---------|------|
| PR 级 | coder PR 提交 | smoke test + lint + type-check |
| merge-to-main | fixer 完成后合并 | 全量测试 + 覆盖率门槛 ≥ 50% |

- coder PR 不要求立即满足覆盖率门槛
- fixer 负责补边界用例、错误路径，使覆盖率达到门槛后方可合并

---

## 后端测试

- **框架**：pytest + pytest-cov（已在 `backend/requirements.txt`）
- **覆盖率门槛**：merge-to-main 时 `services/` ≥ 50%，`app/` ≥ 50%
- **断言**：必须使用硬断言 `assert resp.status_code == 200`，禁止 `if resp.status_code == 200` 静默通过
- **测试文件**：`backend/tests/test_*.py`
- **运行命令**：

```bash
cd backend && pytest tests/ --cov=services --cov=app --cov-fail-under=50
```

- **必须覆盖的场景**：auth（密码哈希/JWT）、health scoring（7 因子算法）、encryption（Fernet）

---

## 前端测试

- **框架**：Vitest + React Testing Library（已在 `frontend/package.json`）
- **测试文件**：`frontend/tests/unit/*.test.{ts,tsx}`
- **运行命令**：

```bash
cd frontend && npm test
```

- **覆盖率**：merge-to-main 时达到 50%+

### E2E / Smoke Mock 闭环要求

Playwright 测试若使用 `page.route()` / `route.fulfill()` / mock SSE / mock fetch，必须同时验证 mock 数据进入用户可见 DOM 或进入后续请求体。禁止只断言请求发出、URL 命中、HTTP 状态码或“页面未报错”。

示例：
```ts
await page.route('**/api/chat/stream**', route => route.fulfill({
  status: 200,
  body: 'data: {"done":true,"answer":"答案是 42","trace_id":"t1"}\n\n',
}));
await page.locator('textarea[data-askbar-input]').fill('问题');
await page.keyboard.press('Enter');

// 必须断言 mock answer 渲染到 DOM
await expect(page.locator('text=答案是 42')).toBeVisible();
```

对于 metadata、列表、详情、权限、反馈等 mock 响应，断言必须覆盖至少一个来自 mock payload 的唯一字段值。例如 `trace_id` 进入反馈请求体、`top_sources` 进入来源徽章、列表项名称进入表格行。

### 冒烟测试用例索引

| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `login.spec.ts` | 登录页 | 登录成功跳转 |
| `logout.spec.ts` | 登出 | 登出后回到登录页 |
| `home-ask-question.spec.ts` | 首页问答 | SSE 回答渲染到 DOM |
| `home-llm-integration.spec.ts` | 首页 LLM 集成 | LLM 响应渲染 |
| `home-sidebar.spec.ts` | 首页侧边栏 | 导航菜单可见 |
| `llm-config-add.spec.ts` | LLM 配置新增 | 表单提交 + 列表刷新 |
| `llm-config-edit.spec.ts` | LLM 配置编辑 | 编辑保存 |
| `llm-config-list.spec.ts` | LLM 配置列表 | 列表渲染 |
| `mcp-config-add-tableau.spec.ts` | MCP Tableau 配置新增 | 表单提交 |
| `mcp-config-list.spec.ts` | MCP 配置列表 | 列表渲染 |
| `mcp-config-toggle.spec.ts` | MCP 配置启停 | 状态切换 |
| `mcp-debugger.spec.ts` | MCP 调试器 | 工具列表 + 执行 + 审计日志 |
| `tableau-assets.spec.ts` | Tableau 资产浏览 | 卡片渲染 + 同步按钮 + 错误提示 |
| `datasource-to-mcp-debugger.spec.ts` | 数据源/视图/仪表板 → MCP 调试器 | 三种资产类型：参数填充 + 执行 + 概览渲染 + LUID 传参校验 |
| `permission-redirect.spec.ts` | 权限重定向 | 无权限跳转 |
| `user-management.spec.ts` | 用户管理 | 用户列表 |
| `activity-log.spec.ts` | 活动日志 | 日志列表 |
| `datasource-connections.spec.ts` | 数据源连接 | 连接列表 |
| `connection-center.spec.ts` | 连接中心 | 连接管理 |
| `rbac-permission.spec.ts` | RBAC 权限 | 角色权限控制 |

运行全部冒烟测试：

```bash
cd frontend && npm run smoke
```

---

## CI 配置

- `.github/workflows/ci.yml` 中两个 job 均运行测试
- PostgreSQL service container 供后端集成测试使用
- 不跑的测试 = 不存在的测试

---

## tester 检查清单（阶段二验收）

每次 coder 完成实现后，tester 执行以下核查，通过后方可进入阶段三（fixer）：

| 检查项 | 标准 |
|--------|------|
| 核心 happy path | 主流程可跑通，无 500 / 报错 |
| 关键异常场景 | 至少 1 个错误输入有正确的错误响应 |
| SPEC 验收标准覆盖 | SPEC.md 中每条 AC 都有对应测试断言 |
| mock 闭环 | E2E 中所有 `page.route`/`route.fulfill` 的 mock 数据均有 DOM 或后续请求体断言 |
| IDOR 负例 | 属主资源写入/删除/动作接口覆盖跨用户资源 403/404 场景 |
| 类型检查 | `npm run type-check` 零错误 |
| lint | `eslint` / `flake8` 无新增警告 |
| 无遗留 EMERGENCY 注释 | 未经 ADR 登记的临时代码不得进入 PR |
