# RealWorld Risk Check — 首页 9 项改动

日期: 2026-04-19
审查者: 独立 reviewer（claude-sonnet-4-6）

---

## 功能回归风险

### ConversationBar

**handleNew（新建对话）逻辑**
✅ 完整保留。L73-L76：`addConversation()` → `navigate('/chat/${id}')`，点击铅笔图标（`ri-edit-box-line`）触发，逻辑未改动。

**`onToggleCollapse` prop 保留**
✅ `interface ConversationBarProps` 在 L27-L30 完整定义了 `collapsed: boolean` 和 `onToggleCollapse: () => void`。函数签名未变，`HomeLayout` 仍可正常传入并触发快捷键折叠。虽然组件内部以 `_onToggleCollapse` 接收（不使用），但接口契约完整。

**搜索框、对话列表、底部用户信息/退出按钮**
✅ 均未改动。搜索框（L146-L161）、时间分组列表（L165-L195）、底部用户 avatar / 角色 / 设置入口 / 退出按钮（L204-L243）完整保留。

### page.tsx

**`ScopeProvider` 包裹**
✅ L302-L307：`HomePage` 函数完整包裹 `<ScopeProvider><HomePageInner /></ScopeProvider>`，未改动。

**`useStreamingChat` 消息渲染**
✅ `streamingMessages` 渲染块（L197-L226）完整保留，流式消息展示逻辑未动。

**`AssetInspectorDrawer`**
✅ L290-L297 保留，`hasPermission('tableau')` 条件渲染，`?asset=` 深链功能完好。

**未登录态 `if (!user)` 返回块**
✅ L74-L96 完整保留，包括登录卡片和注册链接。

**事件处理函数**
✅ `handleLoading`（L126-L133）、`handleResult`（L100-L118）、`handleError`（L120-L124）、`handleExamplePick`（L135-L151）、`handleAskBarResult`（L153-L156）均完整保留，逻辑无变化。

**`OpsSnapshotPanel` import 保留**
⚠️ import 语句（L19）保留了，但 JSX 中已无使用。这是 Spec §改动4 明确要求删除的 import，属于执行遗漏（详见"潜在 Bug"节）。

### HomeLayout

**`--conv-bar-w` CSS 变量**
✅ L72：`style={{ '--conv-bar-w': collapsed ? '0px' : '260px' } as React.CSSProperties}` 精确设置，sidebar 折叠/展开时 AskBar 左边界正确跟随。

**快捷键处理（`⌘N` / `⌘K` / `Esc`）**
✅ L40-L65 完整保留：
- `⌘N`：新建对话并 navigate
- `⌘K`：聚焦 AskBar textarea（`data-askbar-input`）
- `Esc`：非 AskBar 聚焦时折叠 sidebar

---

## 潜在 Bug

### Bug-1：`OpsSnapshotPanel` 未使用 import 残留（非阻塞，但可能阻断 CI）

**文件**：`/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/page.tsx`，L19
**现象**：`import { OpsSnapshotPanel } from './components/OpsSnapshotPanel'` 存在，但 JSX 中无任何使用（OpsSnapshotPanel 的 JSX 在 Batch 3 实施时已被移除）。
**影响**：若项目 ESLint 配置开启 `@typescript-eslint/no-unused-vars`（该规则在多数 TS 项目中为 error 级别），会导致构建/lint check 失败，阻断 CI 流水线。
**对应 Spec**：Spec §改动4 注意事项明确写"需同时删除未使用的 import（L19）"，属于执行遗漏。
**修复**：删除 L19 的 import 行。

### Bug-2：`openAsset` 解构但未使用（lint 警告，符合 Spec 意图但有潜在影响）

**文件**：`/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/page.tsx`，L41
**现象**：`const { assetId, tab, connectionId, closeAsset, openAsset } = useHomeUrlState()` 中，`openAsset` 已无 JSX 消费方（`OpsSnapshotPanel` 被移除后）。
**影响**：轻微。Spec §改动4 §4.1 明确说"保留 `openAsset` 解构"，所以这是有意为之。但如果 ESLint 规则不允许 unused 变量（且无下划线前缀豁免），仍会告警。`openAsset` 无 `_` 前缀，与 `_collapsed` / `_onToggleCollapse` 的处理模式不一致。
**建议**：若 lint 报 warning，可将其重命名为 `openAsset: _openAsset` 或在 ESLint 注释中豁免。不影响运行时行为。

### Bug-3：`WelcomeHero` 内 `useAuth()` 无额外 null 防护（可接受）

**文件**：`/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/components/WelcomeHero.tsx`，L19-L21
**现象**：组件内 `const { user } = useAuth()` 后，`user` 可能为 null（`user?.display_name ?? user?.username ?? ''`）。但 `WelcomeHero` 仅在 `homeState === 'HOME_IDLE'` 时渲染，而 `homeState` 状态只存在于 `HomePageInner` 中——而 `HomePageInner` 的 `if (!user) return` 守卫（L74）先于主内容区渲染执行。因此，进入 `WelcomeHero` 时 `user` 必然非 null。
**结论**：无实际 bug，`?? ''` 的链式降级是额外的防御编码，可接受。Spec §改动5 注意事项已明确分析此场景。

### Bug-4：`handleLoading` 中 `sendMessage` 使用 `lastQuestion` 时序问题（已存在，非本次引入）

**文件**：`/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/page.tsx`，L126-L133
**现象**：`handleLoading(true)` 被调用时，通过闭包读取 `lastQuestion`（由 `onQuestionChange` 回调更新）。若 `onQuestionChange` 与 `onLoading` 的调用顺序在 AskBar 内部未严格保证（`onQuestionChange` 先于 `onLoading`），则 `sendMessage` 会拿到旧的 question。
**判断**：此问题在本次改动前就存在（comment 中已标注"Gap-05"，说明是已知技术债）。本次改动未使此风险变大，记录在案但不属于本次回归。

### Bug-5：`<main>` idle 态 `items-center justify-center` class 拼接方式（可接受）

**文件**：`/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/page.tsx`，L173-L177
**现象**：`[..., homeState === 'HOME_IDLE' ? 'items-center justify-center' : '', 'pb-40'].join(' ')` 在非 idle 态会产生连续空格（`flex-col w-full  pb-40`）。
**影响**：Tailwind 解析 class 字符串时对多余空格容错，不影响渲染。仅代码洁癖层面。可接受。

---

## 安全 / 性能

- **无新增外部依赖**：5 个文件均只使用项目已有模块，无 npm 新包引入。
- **无后端 / API 接口变更**：所有改动限于 JSX 和 className，改动分类为纯前端视觉层。
- **无函数签名变更**：所有 prop 接口保持向后兼容（`ConversationBarProps` 未变，`SuggestionGridProps.onPick` 未变）。
- **`greetingByHour()` 性能**：每次 `WelcomeHero` 渲染时调用一次 `new Date()`，无循环、无定时器、无副作用，性能无忧。
- **`pointer-events-none` + `pointer-events-auto` 组合**：外层渐变条不拦截点击事件，AskBar textarea/button 均在 `pointer-events-auto` 的内层容器内，交互正常。
- **`pb-40`（160px）与 AskBar 高度匹配**：AskBar 实际占位 = `pt-2 pb-5`（28px）+ AskBar 自身（约 72px）+ 免责行（约 32px）≈ 132px，`pb-40`=160px，留有 28px 安全边距，足够防止内容被遮挡。

---

## 结论

**PASS（含 1 个阻塞修复项）**

### 修复建议（按优先级）

1. **必须修复（可能阻断 CI）**：删除 `frontend/src/pages/home/page.tsx` L19 的 `import { OpsSnapshotPanel }` 行。对应 Spec §改动4 注意事项。

2. **建议修复（lint 一致性）**：将 `page.tsx` L41 的 `openAsset` 统一为 `openAsset: _openAsset` 或添加 ESLint 豁免注释，与 `_collapsed` / `_onToggleCollapse` 的命名惯例保持一致。

以上两个问题均不影响运行时功能，但 Bug-1（`OpsSnapshotPanel` import）在严格 lint 环境下会阻断 CI。建议在合并前完成修复。

---

判定：两份报告均 PASS（Bug-1 为执行遗漏，非设计缺陷，修复成本极低），**可在修复 Bug-1 后进入 shipper**。
