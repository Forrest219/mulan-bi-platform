# Help Agent 页面上下文 SSOT 方案

> 版本：v0.2 | 状态：Ready for Review | 日期：2026-05-14 | 范围：Help Agent 前端默认问题与页面上下文

---

## 1. 背景

当前 Help Agent Drawer 的默认内容没有和所有页面保持联动。例如打开：

```text
http://localhost:3000/governance/metrics
```

Help Agent 仍可能展示偏 Agent run 的默认问题，例如“为什么刚才问答失败？”、“最近有没有失败的 Agent run？”。这会让用户感觉 Help Agent 不是当前页面的上下文助手。

现有实现问题：

- `HelpAgentDrawer.tsx` 内部维护 `pageLabel()` 和 `defaultQuestions()`。
- `pageContext.ts` 内部维护另一套 `pageMeta()`。
- 两处 if/else 容易重复、遗漏和漂移。
- 当前只覆盖了少数页面，没有覆盖全部菜单二级页面。

v0.1 曾建议新增独立 `pageHelpRegistry.ts`。该方案能解决 Drawer 与 PageContext 的双写，但仍会引入新的路由元数据双写：页面在 route/menu 中注册一次，还要在 Help Agent registry 中注册一次。v0.2 放弃独立集中式 registry，改为路由/页面声明式上下文，让路由树与页面组件成为 Help Agent 上下文的单一数据源。

---

## 2. 目标

P0 目标：

- 覆盖当前菜单中的全部二级页面。
- Help Agent 打开时显示正确页面名称。
- 默认问题与当前页面业务场景相关。
- `page_context` 带上稳定页面语义：
  - `page_key`
  - `page_title`
  - `page_domain`
- 动态详情页能上报当前业务实体：
  - `/governance/metrics/:id`
  - `/agents/skills/:id`
  - `/assets/tableau/:id`
- Drawer 与请求上下文共用同一份 Help Agent Context。
- 新增页面时在 Route `handle.helpProfile` 声明静态 profile，不修改 Help Agent 基础模块的业务枚举。

非目标：

- 不改 Help Agent 后端诊断工具。
- 不新增 RAG 或页面文档知识库。
- 不读取真实 DOM。
- 不让 Help Agent 模块解析业务 URL 参数。
- 不为每个页面写长篇静态帮助文档。

---

## 3. 架构原则

### 3.1 路由/页面是 SSOT

静态页面信息必须附着在 Route Config 上，不新增与 route 平行的业务页面 registry。Menu 只是 Route 的导航视图投影，不作为 Help Agent 页面元数据的来源。

推荐实现：

1. 在 React Router route object 的 `handle.helpProfile` 上声明静态 profile。
2. 在 AppShell/Layout 中使用 `useMatches()` 读取当前叶子 route 的 `handle.helpProfile`。
3. 由顶层 `HelpAgentContextProvider` 注入静态 profile。
4. 页面组件只通过 Hook 补充动态 selection，不重复声明静态 profile。

禁止模式：

```text
route.tsx 注册页面
menu.ts 再注册页面元数据
pageHelpRegistry.ts 再注册 path/title/defaultQuestions
DetailPage 为了注入 ID 又复制 page_key/page_title/defaultQuestions
```

允许的过渡模式：

- 可以新增 Help Agent 基础类型、Context、Provider、selection patch hook。
- 可以新增从现有 route handle 读取 helpProfile 的适配器。
- 不允许维护一份集中硬编码所有业务 path 的 Help Agent registry 作为长期方案。
- 不允许把 Menu 作为页面级 Help profile 的 SSOT。

### 3.2 Help Agent 基础模块不感知业务域细节

Help Agent 只定义契约并消费上下文：

- `HelpPageProfile`
- `HelpContextEntity`
- `HelpAgentContextProvider`
- `useHelpAgentContext`
- `useHelpAgentSelection`
- `buildHelpPageContext`

资产、治理、智能体、配置、管理等业务域负责在自己的 route handle 中声明默认问题，在详情页组件中 patch 动态实体上下文。

### 3.3 动态实体由页面主动上报

Help Agent 不解析：

```text
/assets/tableau/:id
/governance/metrics/:id
/agents/skills/:id
```

详情页组件通过 React Router `useParams()` 获取参数后，使用 `useHelpAgentSelection()` 主动上报当前实体。这样 URL 结构变化时，只需要修改业务页面自己的路由与参数读取逻辑。

### 3.4 Context 更新必须支持 Patch/Merge

静态 profile 与动态 selection 是两个不同来源：

- Route handle 提供静态 profile。
- Page component 提供动态 selection。

Context Provider 不应该要求页面传入完整 `{ profile, selection }` 后全量覆盖。否则动态详情页为了上报 ID 会重复声明 `page_key/page_title/default_questions`，重新制造双写。

要求：

- `HelpAgentContextProvider` 接收稳定的 route profile 作为基础值。
- `useHelpAgentSelection(selection)` 只 patch selection。
- selection patch 在组件卸载时自动清理，避免从详情页返回列表页后残留实体 ID。
- 合并规则为 `route profile + page selection patch + fallback`。

### 3.5 Context Value 引用稳定性

Provider 的 `value` 必须通过 `useMemo()` 或等价机制保持引用稳定，避免每次页面渲染都触发所有 `useHelpAgentContext()` 消费方重渲染。

禁止示例：

```tsx
<HelpAgentContextProvider value={{ profile, selection }}>
  <AppShell />
</HelpAgentContextProvider>
```

推荐示例：

```tsx
const helpContextValue = useMemo(
  () => ({ profile, selection }),
  [profile, selection]
);

return (
  <HelpAgentContextProvider value={helpContextValue}>
    <AppShell />
  </HelpAgentContextProvider>
);
```

---

## 4. 核心契约

### 4.1 Help Profile

```ts
export type HelpPageDomain =
  | 'assets'
  | 'governance'
  | 'agents'
  | 'config'
  | 'admin'
  | 'account'
  | 'home'
  | 'unknown';

export interface HelpPageProfile {
  page_key: string;
  page_title: string;
  page_domain: HelpPageDomain;
  default_questions: string[];
}
```

约束：

- `page_key` 稳定、可埋点、可被后端后续消费。
- `page_title` 用于 Drawer header 与请求上下文。
- `page_domain` 用于后续按域路由诊断工具。
- `default_questions` 每页固定 3 条短问题，避免 Drawer 首屏拥挤。

### 4.2 Generic Selection

不要在契约中不断追加 `metric_id`、`skill_id`、`dataset_id`、`workflow_id` 等字段。P0 使用泛型实体选择模型：

```ts
export interface HelpContextEntity {
  type: string;
  id: string;
  label?: string;
  source?: 'route' | 'query' | 'selection' | 'page-state';
}

export interface HelpPageSelection {
  primary_entity?: HelpContextEntity;
  entities?: HelpContextEntity[];
  query_refs?: Record<string, string>;
}
```

示例：

```ts
{
  primary_entity: {
    type: 'metric',
    id: '123',
    source: 'route'
  }
}
```

兼容策略：

- `run_id`、`task_run_id`、`connection_id`、`skill_key` 等现有 query 选择项先放入 `query_refs`。
- 后端如仍需要旧字段，可在请求发送前做临时 adapter，但新契约不再继续扩展一组平铺 `xxx_id` 字段。
- `metric_id`、`skill_id`、`asset_id` 只作为验收时的业务语义，不作为长期接口字段名。

### 4.3 Page Context

修改：

```text
frontend/src/api/helpAgent.ts
```

目标结构：

```ts
export interface HelpPageContext {
  path?: string;
  title?: string;
  page_key?: string;
  page_title?: string;
  page_domain?: HelpPageDomain;
  selection?: HelpPageSelection;
}
```

请求示例：

```ts
{
  path: '/governance/metrics/123',
  title: '指标详情',
  page_key: 'metric-detail',
  page_title: '指标详情',
  page_domain: 'governance',
  selection: {
    primary_entity: {
      type: 'metric',
      id: '123',
      source: 'route'
    }
  }
}
```

---

## 5. 页面覆盖清单

P0 覆盖当前菜单可到达的全部二级页面。下表是验收清单，不代表要在 Help Agent 模块或 Menu 配置中集中硬编码；最终实现应在对应 Route `handle.helpProfile` 上声明。

### 5.1 资产域

| path | page_key | title | 默认问题方向 |
|---|---|---|---|
| `/assets/explorer` | `data-explorer` | Data Explorer | 连接、Schema、Preview、权限 |
| `/assets/dw` | `dw-assets` | 数仓资产 | 表/字段、血缘、Preview、同步 |
| `/assets/tableau` | `tableau-assets` | Tableau 资产 | 数据源、字段、健康度、同步 |
| `/assets/tableau/:id` | `tableau-asset-detail` | Tableau 资产详情 | 字段元数据、MCP、健康度 |
| `/assets/knowledge` | `knowledge` | 知识库 | 术语、指标关联、搜索结果 |

### 5.2 治理域

| path | page_key | title | 默认问题方向 |
|---|---|---|---|
| `/governance/dw-audit` | `dw-audit` | 数仓巡检 | 巡检失败、规则、风险项 |
| `/governance/tableau-audit` | `tableau-audit` | Tableau 巡检 | 连接、资产健康、MCP 状态 |
| `/governance/dqc` | `dqc` | 数据质量监控 | 规则、执行、告警 |
| `/governance/semantic` | `semantic` | 语义治理 | 字段语义、指标定义、发布 |
| `/governance/metrics` | `metrics` | 指标治理 | 指标口径、依赖、发布状态 |
| `/governance/metrics/:id` | `metric-detail` | 指标详情 | 血缘、字段映射、依赖指标 |

### 5.3 智能体域

| path | page_key | title | 默认问题方向 |
|---|---|---|---|
| `/agents/data` | `data-agent` | Data Agent | 问答失败、数据源、工具链 |
| `/agents/sql` | `sql-agent` | SQL Agent | SQL 生成、权限、执行错误 |
| `/agents/metrics` | `metrics-agent` | Metrics Agent | 指标生成、口径、依赖 |
| `/agents/help` | `help-agent` | Help Agent | 使用帮助、诊断能力 |
| `/agents/agent-monitor` | `agent-monitor` | Agent 监控 | run、step、耗时、失败原因 |
| `/agents/skills` | `skills` | 技能中心 | skill 生效、版本、schema |
| `/agents/skills/:id` | `skill-detail` | 技能详情 | 当前技能版本、schema、启用状态 |

### 5.4 配置域

| path | page_key | title | 默认问题方向 |
|---|---|---|---|
| `/system/data-connections` | `data-connections` | 数据连接 | 连接测试、凭据、同步 |
| `/system/service-configs` | `service-configs` | 服务配置 | LLM/MCP 配置、密钥状态 |
| `/system/mcp-debugger` | `mcp-debugger` | MCP 调试器 | 工具调用、参数、错误日志 |
| `/system/tasks` | `tasks` | 任务管理 | 调度、失败、最近运行 |

### 5.5 管理域

| path | page_key | title | 默认问题方向 |
|---|---|---|---|
| `/system/users` | `users` | 用户管理 | 账号、角色、登录问题 |
| `/system/permissions` | `permissions` | 权限配置 | 资源权限、角色策略 |
| `/system/activity` | `activity` | 操作日志 | 操作追踪、异常行为 |
| `/system/usage-stats/tokens` | `token-stats` | Token 统计 | token 消耗、模型调用 |
| `/system/platform-settings` | `platform-settings` | 平台设置 | Logo、首页、系统配置 |
| `/notifications` | `notifications` | 消息通知 | 告警、未读、通知来源 |
| `/account/profile` | `account-profile` | 个人中心 | 头像、密码、个人信息 |

---

## 6. 运行时数据流

### 6.1 静态二级页面

```text
route handle.helpProfile
  -> AppShell/Layout 通过 useMatches() 读取当前 matched route
  -> HelpAgentContextProvider 注入 profile
  -> HelpAgentDrawer 展示 header 与 default questions
  -> buildHelpPageContext 生成 page_context
```

### 6.2 动态详情页

```text
DetailPage useParams()
  -> 构造 primary_entity
  -> useHelpAgentSelection() patch selection
  -> 与 route handle.helpProfile merge
  -> HelpAgentDrawer 与 buildHelpPageContext 消费同一份上下文
```

示例：

```tsx
function MetricDetailPage() {
  const { id } = useParams();

  const selection = useMemo(
    () => ({
      primary_entity: {
        type: 'metric',
        id: String(id),
        source: 'route' as const
      }
    }),
    [id]
  );

  useHelpAgentSelection(selection);

  return <MetricDetailContent />;
}
```

对应静态 profile 只在 route 中声明一次：

```tsx
{
  path: '/governance/metrics/:id',
  element: <MetricDetailPage />,
  handle: {
    helpProfile: {
      page_key: 'metric-detail',
      page_title: '指标详情',
      page_domain: 'governance',
      default_questions: [
        '这个指标的口径和依赖是否一致？',
        '这个指标关联了哪些字段和上游表？',
        '这个指标发布失败应该怎么排查？'
      ]
    }
  }
}
```

---

## 7. Plan

### Plan 1：定义 Help Agent Context 契约

目标：把 Help Agent 的静态 profile 与动态 selection 收敛为基础契约，而不是集中业务 registry。

任务：

1. 在 Help Agent 模块内定义 `HelpPageProfile`、`HelpContextEntity`、`HelpPageSelection`。
2. 提供 `HelpAgentContextProvider`、`useHelpAgentContext`、`useHelpAgentSelection`。
3. Provider 内部支持 route profile 与 page selection patch 合并。
4. selection patch 在组件卸载时自动清理。
5. Provider value 与对外 context value 使用 `useMemo()` 保持引用稳定。
6. 定义 fallback profile，仅用于未声明页面。
7. fallback 不包含业务默认问题，只提供通用排查问题。

验收：

- Drawer 与 `buildHelpPageContext` 能从同一个 Context 读取页面信息。
- 未声明页面仍能使用 fallback，不报错。
- 动态详情页只 patch selection，不重复声明 profile。
- Context value 不因父组件普通重渲染产生无意义引用变化。

### Plan 2：将静态 profile 挂到 Route SSOT

目标：全部页面的静态帮助信息由 Route `handle.helpProfile` 声明，不由 Help Agent 或 Menu 集中硬编码。

任务：

1. 扩展现有 route handle 类型，增加 `helpProfile?: HelpPageProfile`。
2. 为全部当前菜单二级页面对应 route 补齐 `handle.helpProfile`。
3. 为三个动态详情页 route 补齐 `handle.helpProfile`。
4. 在 AppShell/Layout 中通过 `useMatches()` 从当前叶子 route 读取 `helpProfile`。
5. 通过 `HelpAgentContextProvider` 注入当前页面 profile。

验收：

- 所有菜单二级页面对应 route 都有非 fallback profile。
- 三个动态详情页 route 都有非 fallback profile。
- 新增普通页面时，只需要在 route 声明处补 `handle.helpProfile`。
- Help Agent 模块不出现资产、治理、智能体、配置、管理的集中 path 表。
- Menu 配置不承担 Help Agent 页面元数据职责。

### Plan 3：重构 HelpAgentDrawer

目标：Drawer 默认文案只从 Help Agent Context 获取。

任务：

1. 删除 `HelpAgentDrawer.tsx` 内的 `pageLabel()`。
2. 删除 `HelpAgentDrawer.tsx` 内的 `defaultQuestions()`。
3. 使用 `useHelpAgentContext()` 获取 `profile`。
4. Header 显示：

```ts
context.profile.page_title
```

5. 默认问题使用：

```ts
context.profile.default_questions
```

验收：

- `/governance/metrics` 打开 Help Agent 显示指标治理相关默认问题。
- `/system/mcp-debugger` 打开 Help Agent 显示 MCP 调试相关默认问题。
- `/system/users` 打开 Help Agent 显示用户管理相关默认问题。
- Drawer 不再维护页面 if/else。

### Plan 4：重构 buildHelpPageContext 与动态详情页

目标：请求上下文与 Drawer 使用同一份 Context，详情页主动上报实体。

任务：

1. 删除 `pageContext.ts` 内的 `pageMeta()`。
2. `buildHelpPageContext` 从 `useHelpAgentContext()` 或传入的 current context 生成请求 payload。
3. 保留 query 脱敏逻辑。
4. 将现有 query 选择项放入 `selection.query_refs`。
5. 在 `/governance/metrics/:id` 页面内通过 `useParams()` 上报：

```ts
useHelpAgentSelection({
  primary_entity: { type: 'metric', id: String(id), source: 'route' }
})
```

6. 在 `/agents/skills/:id` 页面内通过 `useParams()` 上报：

```ts
useHelpAgentSelection({
  primary_entity: { type: 'skill', id: String(id), source: 'route' }
})
```

7. 在 `/assets/tableau/:id` 页面内通过 `useParams()` 上报：

```ts
useHelpAgentSelection({
  primary_entity: { type: 'tableau_asset', id: String(id), source: 'route' }
})
```

验收：

- 请求 `/api/help-agent/stream` 时，`page_context` 包含正确 `page_key/page_title/page_domain`。
- 指标详情页带 `selection.primary_entity.type='metric'` 与当前 ID。
- 技能详情页带 `selection.primary_entity.type='skill'` 与当前 ID。
- Tableau 资产详情页带 `selection.primary_entity.type='tableau_asset'` 与当前 ID。
- Help Agent 模块不解析业务 path。
- 详情页组件不重复声明 `page_key/page_title/default_questions`。

### Plan 5：测试与验收

目标：确保全部二级页面都有上下文默认内容，动态页面实体上下文正确。

任务：

1. 跑 `npm run type-check`。
2. 跑 `npm run lint`。
3. 跑 `npm test -- --run`。
4. 跑 `git diff --check`。
5. 增加最小单测：
   - 当前菜单可到达页面对应 route 均存在 `handle.helpProfile`。
   - Drawer 使用 Context 默认问题。
   - `buildHelpPageContext` 输出 `page_key/page_title/page_domain/selection`。
   - `useHelpAgentSelection` 能 patch selection，并在卸载后清理。
6. 手工验证代表页面。

验收：

- 类型检查通过。
- lint 通过。
- 相关测试通过。
- 代表页面默认问题正确。
- 新增页面时不需要修改 Help Agent 基础模块。

---

## 8. Coder Tasks

1. 新增或调整 Help Agent Context 基础模块：

```text
frontend/src/pages/agents/help-agent/helpAgentContext.tsx
```

2. 在基础模块内定义：

```ts
HelpPageProfile
HelpContextEntity
HelpPageSelection
HelpAgentContextProvider
useHelpAgentContext
useHelpAgentSelection
```

3. 修改 route handle 类型，增加：

```ts
helpProfile?: HelpPageProfile;
```

4. 在 router config 的现有页面声明处补齐全部二级页面与详情页 `handle.helpProfile`。
5. 修改 AppShell/Layout，使用 `useMatches()` 获取当前叶子 route 的 `handle.helpProfile`，并注入 `HelpAgentContextProvider`。
6. Provider 内部用 `useMemo()` 稳定 context value。
7. 修改：

```text
frontend/src/pages/agents/help-agent/HelpAgentDrawer.tsx
```

移除本地页面标题/默认问题 if/else，改用 `useHelpAgentContext()`。

8. 修改：

```text
frontend/src/pages/agents/help-agent/pageContext.ts
```

移除本地 `pageMeta()` if/else，改用统一 Context 生成 `page_context`。

9. 修改：

```text
frontend/src/api/helpAgent.ts
```

增加 `page_key/page_title/page_domain` 与泛型 `selection` 类型。

10. 修改三个详情页，让页面通过 `useParams()` 主动上报实体：

```text
frontend/src/pages/data-governance/metrics/detail.tsx
frontend/src/pages/agents/skills/detail.tsx
frontend/src/features/tableau-inspector/AssetInspector.tsx
```

详情页只调用 `useHelpAgentSelection()`，不得重复声明 route 已有的 `page_key/page_title/default_questions`。

11. 运行：

```bash
cd frontend && npm run type-check
cd frontend && npm run lint
cd frontend && npm test -- --run
git diff --check frontend/src/api/helpAgent.ts frontend/src/pages/agents/help-agent frontend/src/router
```

---

## 9. Tester Tasks

手工打开以下页面，逐个点击顶栏 Help Agent：

| path | 预期 |
|---|---|
| `/assets/explorer` | 默认问题与 Data Explorer / Schema / Preview 相关 |
| `/assets/dw` | 默认问题与数仓资产、字段、血缘相关 |
| `/assets/tableau` | 默认问题与 Tableau 资产、健康度、同步相关 |
| `/governance/metrics` | 默认问题与指标治理相关 |
| `/governance/dqc` | 默认问题与质量规则和告警相关 |
| `/agents/agent-monitor` | 默认问题与 run、step、耗时相关 |
| `/agents/skills` | 默认问题与技能版本和 schema 相关 |
| `/system/data-connections` | 默认问题与连接测试和同步相关 |
| `/system/mcp-debugger` | 默认问题与 MCP 工具调用和错误日志相关 |
| `/system/users` | 默认问题与用户、角色、登录相关 |
| `/notifications` | 默认问题与告警、未读、通知来源相关 |

详情页验证：

| path | 预期 |
|---|---|
| `/governance/metrics/123` | `page_key=metric-detail`，`selection.primary_entity={ type: 'metric', id: '123' }` |
| `/agents/skills/abc` | `page_key=skill-detail`，`selection.primary_entity={ type: 'skill', id: 'abc' }` |
| `/assets/tableau/456` | `page_key=tableau-asset-detail`，`selection.primary_entity={ type: 'tableau_asset', id: '456' }` |

接口验证：

- 发送 Help Agent 消息时，`/api/help-agent/stream` payload 中包含 `page_context.page_key`。
- 动态详情页 payload 中包含 `page_context.selection.primary_entity`。
- URL path 改动不影响 Help Agent 基础模块，只影响对应业务页面自己的 route 声明与参数读取逻辑。

---

## 10. 验收标准

- [ ] 所有菜单二级页面都有专属 Help Agent 默认问题。
- [ ] Drawer header 显示正确当前页面名。
- [ ] `page_context` 包含 `page_key/page_title/page_domain`。
- [ ] 指标详情页可带 `primary_entity.type='metric'` 与当前 ID。
- [ ] 技能详情页可带 `primary_entity.type='skill'` 与当前 ID。
- [ ] Tableau 资产详情页可带 `primary_entity.type='tableau_asset'` 与当前 ID。
- [ ] `HelpAgentDrawer.tsx` 不再维护页面 if/else。
- [ ] `pageContext.ts` 不再维护页面 if/else。
- [ ] Help Agent 基础模块不维护全部业务 path/profile 列表。
- [ ] 新增普通页面时只需要在 route `handle.helpProfile` 声明处补配置。
- [ ] 新增详情页时由详情页主动上报 `primary_entity`，Help Agent 不解析业务 URL。
- [ ] 详情页不重复声明静态 profile，只 patch selection。
- [ ] Help Agent Context value 引用稳定，避免无意义重渲染。
- [ ] `npm run type-check`、`npm run lint`、`npm test -- --run` 通过。

---

## 11. 风险与边界

| 风险 | 影响 | 处理 |
|---|---|---|
| 当前 route config 类型不支持 handle 扩展 | 需要补类型或适配器 | P0 先扩展 route handle 类型，不改 Menu 元数据 |
| 部分页面没有菜单项 | 不影响 Help profile 获取 | 只要页面有 route，就在 route handle 声明 profile |
| 详情页为了上报实体重复声明 profile | 重新引入双写 | 只允许调用 `useHelpAgentSelection()` patch selection |
| 详情页忘记上报 primary_entity | Help Agent 只能知道页面，无法知道当前对象 | 给详情页增加单测或开发检查清单 |
| 后端暂未消费 generic selection | 前端上下文已准备好，后端增强可能滞后 | 保留临时 adapter，但禁止继续扩展平铺 `xxx_id` 字段 |
| 默认问题过长 | Drawer 首屏拥挤 | 每页固定 3 条短问题 |
| Context value 内联对象导致重渲染 | Drawer、Header 等消费方无意义刷新 | Provider 和 selection patch value 使用 `useMemo()` |
| 业务域默认问题变更需要改基础模块 | 违反开闭原则 | 默认问题必须放在业务 route handle 声明处，不放在 Help Agent 基础模块 |

---

## 12. 对 v0.1 的结论

可以保留的部分：

- Drawer 与 PageContext 必须消除两套 if/else。
- 需要覆盖全部当前菜单二级页面。
- 需要覆盖三个动态详情页。
- `page_context` 需要增加 `page_key/page_title/page_domain`。

需要调整的部分：

- 不新增独立集中式 `pageHelpRegistry.ts` 作为业务 profile 来源。
- 不让 Help Agent 通过最长前缀匹配解析业务页面。
- 不让 Help Agent 解析详情页 URL ID。
- 不继续向 `selection` 增加平铺业务字段，改用 generic entity selection。
