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

> 共 **62 个** `.spec.ts` 文件，覆盖前端所有已开发页面。`npm run smoke` 运行全部。

#### 回归冒烟单元测试（Vitest）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `frontend/tests/unit/regression/ConversationBar.smoke.test.tsx` | 首页侧边栏对话列表 | 点击“新对话”不写库；`message_count=0` 或旧缓存无消息的“新对话”占位不展示；有消息/有标题的真实对话仍展示 |
| `frontend/tests/unit/regression/HomeLayout.smoke.test.tsx` | 首页快捷键 | `⌘N` / `Ctrl+N` 只导航到 `/`，不创建空对话 |

#### 认证模块（4 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `login.spec.ts` | 登录页 + 注册页 | 登录成功跳转、错误密码提示、loading 状态、键盘交互、注册页表单校验 |
| `logout.spec.ts` | 登出 | 登出后回到登录页 |
| `account-profile.spec.ts` | 个人中心 `/account/profile` — 表单渲染、姓名修改保存、刷新持久化 | 成功 toast 含"个人信息已保存"进入 DOM；reload 后 `input.value` 等于新姓名（验证后端真实落库） |
| `account-security.spec.ts` | 账户安全 `/account/security` — MFA 两步验证启用/关闭 | h1 包含"账户安全"；"启用两步验证"按钮或"已启用"标识至少一个可见；关闭 MFA 时弹出"当前密码"和"验证码"输入框 |

#### 首页模块（11 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `home-ask-question.spec.ts` | 首页问答 | SSE 回答渲染到 DOM、意图类型徽章、反馈功能 |
| `home-llm-integration.spec.ts` | 首页 LLM 集成 | LLM 响应渲染、置信度展示 |
| `home-sidebar.spec.ts` | 首页侧边栏 | 导航菜单可见、路由跳转 |
| `rbac-permission.spec.ts` | RBAC 权限隔离 | adminOnly 页面拒绝、database_monitor 权限正向、无权限路由拒绝 |
| `app-sidebar-collapse.spec.ts` | 全局侧边栏折叠/展开（回归防护）| 折叠后宽度 56px；展开按钮仍在视口内（boundingBox x/y ≥ 0）；展开后宽度恢复 |
| `home-explainability.spec.ts` | 首页 SSE 分析过程折叠展开 | 意图/计划/执行/后处理/降级五段内容正确渲染；fallback 时降级徽标可见；旧 SSE contract 无 explainability 时页面不报错 |
| `home-new-conversation.spec.ts` | 首页新建对话按钮行为 | 点击后 URL 匹配 `/$`；AskBar 可见且 enabled；无 JS 错误 |
| `homepage-agent-mode.spec.ts` | 首页 Agent 模式四态路由（legacy_only / agent_only / agent_with_fallback / dual_write）| 各模式下 mock answer 渲染到 DOM；trace_id 进入反馈请求体；fallback 时降级答案覆盖 |
| `homepage-conversation-flow.spec.ts` | 首页对话完整流程 | 新建对话后 AskBar 可输入；发送后输入框清空；连接选择器选项数 >1 |
| `ops-workbench.spec.ts` | 首页基础可用性 + 旧路由重定向 | body 文本长度 >10；`/ops/workbench` 重定向后 URL 不含该路径；无 TODO/Placeholder 文案残留 |
| `qa-e2e-realapi.spec.ts` | 首页 Q&A 端到端真实 API | 闲聊"你好"后"木兰"标签可见；数据查询"你有多少个数据源"后"木兰"标签可见 |

#### 系统管理 — 用户与权限（7 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `user-management.spec.ts` | 用户管理 | 用户列表、搜索、创建/编辑表单 |
| `activity-log.spec.ts` | 操作日志 | 日志列表、时间范围筛选 |
| `rbac-permission.spec.ts` | 用户组、权限总览、任务管理、查询告警、Agent 监控、平台设置 | adminOnly 权限校验、database_monitor 正向授权 |
| `user-group-management.spec.ts` | 用户组管理 `/system/groups` — 创建/删除/成员管理/权限暂存 | 创建后列表出现新组；权限切换显示"尚未保存"提示栏；"取消更改"后提示栏消失 |
| `user-management-create.spec.ts` | 用户创建表单校验与 happy path | 缺显示名提示"请输入显示名称"；密码 5 位提示"至少6位"；重复用户名 ≥400 且弹窗保留错误 |
| `user-management-permissions.spec.ts` | 用户权限配置（8 项 checkbox）| 弹窗显示 8 个 checkbox；analyst 默认 2 项勾选；admin 行点击提示"管理员拥有所有权限" |
| `user-management-role-switch.spec.ts` | 用户角色切换 | 切换至 analyst 后下拉值更新；切换至 data_admin 后值更新；admin 行角色下拉锁定为 admin |

#### 系统管理 — LLM 配置（5 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `llm-config-list.spec.ts` | LLM 配置列表 | 列表渲染、API Key 字段脱敏展示 |
| `llm-config-add.spec.ts` | LLM 配置新增（Mock） | 表单提交 + 列表刷新、错误处理 |
| `llm-config-add-real.spec.ts` | LLM 配置新增（真实 API） | 真实 API 调用验证 |
| `llm-config-edit.spec.ts` | LLM 配置编辑 | 编辑保存、字段回显 |
| `llm-config-validation.spec.ts` | LLM 配置表单校验 — Provider 切换/字段必填/格式 | Provider 切换时 base_url/model 自动填充；API Key 空时提示；Base URL 非 http 时提示；display_name 重复返回 409 |

#### 系统管理 — MCP 配置（6 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `mcp-config-list.spec.ts` | MCP 配置列表 | 列表渲染、状态徽章 |
| `mcp-config-add-tableau.spec.ts` | MCP Tableau 配置新增 | 表单字段验证、站点连接测试 |
| `mcp-config-add-tableau-real.spec.ts` | MCP Tableau 新增（真实连接） | 真实 Tableau 连接验证 |
| `mcp-config-add-starrocks.spec.ts` | MCP StarRocks 配置新增 | StarRocks 表单字段 |
| `mcp-config-toggle.spec.ts` | MCP 配置启停 | 状态切换、API 验证 |
| `mcp-debugger.spec.ts` | MCP 调试器 | 工具列表加载、执行调用、审计日志 |

#### 系统管理 — 其他（8 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `debug-mcp.spec.ts` | MCP 调试器（工具调试） | 工具执行、结果展示 |
| `datasource-to-mcp-debugger.spec.ts` | 数据源/视图/仪表板 → MCP 调试器 | 三种资产类型参数填充、概览渲染 |
| `permission-redirect.spec.ts` | 任务管理、查询告警、Agent 监控、平台设置 | adminOnly 权限校验 |
| `agent-monitor.spec.ts` | Agent 监控 `/system/agent-monitor` — 三 Tab 总览/工具列表/会话管理 | h1 含"Agent 监控"且无 404；三个 Tab 按钮可见；总览显示统计卡片或加载状态 |
| `platform-settings.spec.ts` | 平台设置 `/system/platform-settings` — 名称/副标题/Logo/权限控制 | 修改保存后 toast"保存成功"可见，刷新持久化；无效 Logo URL 实时报错；非 admin 跳转 /403 |
| `query-alerts.spec.ts` | 问数告警 `/system/query-alerts` — 列表/筛选/标记已解决 | h1 含"问数告警"；表格或空态"暂无告警"可见；"未解决"/"全部"切换高亮变化 |
| `query-logs.spec.ts` | 查数日志写入验证（首页发问→后端写 log→日志页可查）| 首页发送唯一测试问题后 GET /api/admin/query/logs 包含该问题；日志页表格行出现该问题文本 |
| `shared-permissions.spec.ts` | 共享权限巡检 `/system/shared-permissions` — 列表/筛选/批量撤销 | h1 含"共享权限巡检"且统计卡片可见；按用户筛选出现下拉；勾选后"批量撤销"按钮可见 |

#### 资产管理 — Tableau（9 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `tableau-asset-list.spec.ts` | Tableau 资产列表 | 资产卡片/表格、连接选择器、搜索框、列表视图表头（8 列） |
| `tableau-asset-detail.spec.ts` | Tableau 资产详情 | Tab 切换（基本信息/关联数据源/字段元数据/健康度/AI解读）、面包屑导航 |
| `tableau-connections.spec.ts` | Tableau 连接（只读状态看板） | MCP 配置提示横幅、无增删改按钮、同步/测试/日志操作 |
| `sync-logs.spec.ts` | 同步日志（单连接） | 日志列表、表头 12 列、分页、状态标签、错误详情展开 |
| `sync-logs-all.spec.ts` | 同步日志（全局） | 筛选器（连接/状态/时间）、表头 13 列、状态选项、分页格式 |
| `sync-logs-realtime.spec.ts` | 同步日志实时轮询（running→success/failed 自动刷新）| running 状态自动刷新为成功且 mock 调用次数 ≥3；刷新为失败时详情显示"连接超时"；无 running 记录时不轮询 |
| `tableau-assets.spec.ts` | Tableau 资产浏览 `/assets/tableau` — 连接选择/卡片/同步/空态 | h1 含"Tableau 资产浏览"且连接选择器可见；空态"同步资产"按钮可点击；同步失败时显示中文错误而非 [object Object] |
| `tableau-health.spec.ts` | Tableau 巡检 `/governance/tableau-audit` — 站点选择器/资产表格/时间格式 | 站点选择器可见；表头含"资产名称/评分/主要问题/检查时间/操作"；检查时间显示绝对时间格式非"刚刚/分钟前" |
| `uat-tableau-browse.spec.ts` | Tableau 资产浏览 UAT — 连接记忆/搜索筛选/详情钻取 | 首次访问自动选中连接且 localStorage 保存；刷新后仍选中（记忆保持）；点击卡片跳转 /assets/tableau/:id |

#### 资产管理 — 连接中心（2 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `connection-center.spec.ts` | 连接总览 | KPI 卡片（总计/正常/警告/失败）、Tab 切换（数据库/Tableau）、跳转链接 |
| `datasource-connections.spec.ts` | 数据源管理 | 新建数据源 Modal、连接中心跳转、无占位文案残留 |

#### 数据治理（11 个）
| 文件 | 覆盖链路 | 关键断言 |
|------|---------|---------|
| `governance-health-center.spec.ts` | 数仓巡检 | Tab 切换（Warehouse/Quality/Tableau）、Scan 按钮、数据源选择器 |
| `governance-quality.spec.ts` | 数据质量 | 质量规则内容、Tab 切换、无占位文案 |
| `governance-metrics.spec.ts` | Metrics 指标 | 指标类型筛选（原子/派生/比率）、列表/空状态 |
| `semantic-datasource-list.spec.ts` | 语义数据源 | 连接选择器、状态筛选、空状态 |
| `semantic-field-list.spec.ts` | 语义字段列表 | 字段同步、连接选择、表格表头 |
| `nl-query.spec.ts` | NL→SQL 查询 | AskBar 交互、SSE 流式响应、错误码处理（NLQ_012/SYS_001）、追问功能 |
| `knowledge-base.spec.ts` | 知识库 | 术语/文档 CRUD、向量检索、Schema 管理、RBAC 权限 |
| `governance-compliance.spec.ts` | 合规巡检 `/governance/compliance` — 规则列表/巡检结果 | 包含"合规规则"或 404 容忍；有规则时"发起巡检"按钮可见；巡检结果 Tab 出现"巡检概要"或"暂无记录" |
| `metric-detail.spec.ts` | 指标详情 `/governance/metrics/:id` — 四 Tab | 含"指标管理"或"基本信息"且无 404；四个 Tab 按钮可见；血缘 Tab 显示血缘或"暂无血缘记录" |
| `metrics-maintenance-window.spec.ts` | 指标维护窗口 `/governance/metrics/maintenance-windows` | 含"维护窗口"且无 404；"新建窗口"按钮可见且弹窗有"窗口名称"；全部/激活/未激活筛选按钮可见 |
| `publish-logs.spec.ts` | 语义发布记录 `/governance/semantic/publish-logs` | h1 含"语义发布记录"且无 404；显示发布列表或空状态或加载状态；无英文占位文案残留 |

#### 开发中/未覆盖模块
| 路由 | 状态 | 说明 |
|------|------|------|
| `/dev/ddl-validator` | 未覆盖 | 前端使用 Mock 数据，未对接真实 DDL 检查 API |

---

### 冒烟测试规范

#### 文件命名
- 冒烟测试：`frontend/tests/smoke/*.spec.ts`
- 单元测试：`frontend/tests/unit/**/*.test.{ts,tsx}`

#### 登录模式（统一）
```ts
test.beforeEach(async ({ page }) => {
  await page.goto('/login');
  await page.getByPlaceholder('用户名').fill(process.env.ADMIN_USERNAME ?? 'admin');
  await page.getByPlaceholder('密码').fill(process.env.ADMIN_PASSWORD ?? 'admin123');
  await page.getByRole('button', { name: '登录' }).click();
  await page.waitForURL('/', { timeout: 8000 });
});
```

#### 密码管理
- 禁止在测试文件中硬编码密码
- 使用环境变量：`process.env.SMOKE_ADMIN_USERNAME` / `SMOKE_ADMIN_PASSWORD`
- CI 中通过 secret 注入

#### 测试数据清理（globalTeardown）
- 配置入口：`frontend/playwright.config.ts` 的 `globalTeardown: './tests/global-teardown.ts'`
- 当前覆盖：LLM 配置（按 `display_name` 前缀匹配，见 `tests/global-teardown.ts` 的 `CLEANUP_PATTERN`）
- **新增冒烟用例若会写库，必须**：
  1) 用约定前缀命名测试数据（如 `删除测试-`、`编辑测试-`、`MiniMax-Test-`）
  2) 在 `CLEANUP_PATTERN` 追加该前缀
- teardown 失败不影响测试退出码，仅打印警告

#### 错误过滤（统一）
```ts
const realErrors = errors.filter(e =>
  !e.includes('401') &&
  !e.includes('403') &&
  !e.includes('fetch') &&
  !e.includes('favicon') &&
  !e.includes('net::ERR') &&
  !e.includes('Failed to load resource')
);
```

#### 冒烟测试最低断言要求
每个测试至少包含：
1. 页面/组件可访问（不报 404/500）
2. 核心内容可见（表格/表单/标题/按钮之一）
3. 无控制台 JS 错误

#### Mock 闭环要求
Playwright 测试若使用 `page.route()` / `route.fulfill()`，必须同时验证 mock 数据进入用户可见 DOM 或后续请求体。

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
