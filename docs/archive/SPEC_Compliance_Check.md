# SPEC Compliance Check — 首页 9 项改动

日期: 2026-04-19
审查者: 独立 reviewer（claude-sonnet-4-6）
对照文档: `docs/DESIGN_SPEC_HOMEPAGE_V2.md`

---

## 逐项 AC 覆盖状态

### 改动 1：删除 ConversationBar 折叠按钮

✅ **PASS**
`ri-sidebar-fold-line` 折叠按钮已完整删除。顶部区块不再含折叠 `<button>`，符合 Spec §改动1 要求。

### 改动 2：ConversationBar 头部加品牌区

✅ **PASS**
顶部容器 class：`flex items-center justify-between h-14 px-3 border-b border-slate-100 flex-shrink-0`，与 Spec §7.2 规范完全一致。
- logo `w-5 h-5`、`aria-hidden="true"`：符合规范
- 产品名 `text-sm font-semibold text-slate-800 truncate`：符合规范
- 新建按钮 icon `ri-edit-box-line`，`title="新对话  ⌘N"`：符合规范
- `LOGO_URL` 从 `config` import：符合规范
- `handleNew` 点击逻辑保持不变：符合规范

### 改动 3：idle 态隐藏 ScopePicker

✅ **PASS**
条件：`{homeState !== 'HOME_IDLE' && homeState !== 'HOME_OFFLINE' && (...)}` 完整实现。
包裹了 `border-b border-slate-100` 和 `max-w-3xl mx-auto`，符合 Spec §改动3。
`ScopePicker` import 及 `ScopeProvider` 均未删除，符合规范。

### 改动 4：idle 态隐藏 OpsSnapshotPanel

⚠️ **PASS（含 lint 警告风险）**
`OpsSnapshotPanel` 已从 JSX 移除，`SuggestionGrid` 单独条件渲染，符合 Spec §改动4 目标。
- `OpsSnapshotPanel` 组件文件未删除：符合规范
- `AssetInspectorDrawer` 保留：符合规范
- `openAsset` 解构保留（L41）：符合 Spec §4.1"保留 `openAsset` 解构"的明确要求

**但存在一个偏差**：`import { OpsSnapshotPanel } from './components/OpsSnapshotPanel'`（L19）未被删除。Spec §改动4"注意事项"明确写道"需同时删除未使用的 import"。该 import 在当前 JSX 中没有任何使用，会触发 `@typescript-eslint/no-unused-vars` lint 错误，在严格 CI 环境下可能阻断构建。

### 改动 5：WelcomeHero 重设计

✅ **PASS**
- `h1` class：`text-2xl font-semibold text-slate-800 tracking-tight`：与 Spec §改动5"新 className"精确吻合
- 副标题：`text-sm text-slate-500`（`text-slate-400` 已升级）：符合规范
- 去掉 `pt-16 pb-8`：符合规范（垂直位置由父容器控制）
- `greetingByHour()` 按时段返回中文问候，时段边界（0/6/12/14/18h）与 Spec §改动5 文案表完全吻合
- `useAuth()` 调用，`user?.display_name ?? user?.username ?? ''` 降级：符合规范
- logo 24px（`w-6 h-6`）、`aria-hidden="true"`、`opacity-80`：符合规范

### 改动 6：SuggestionGrid 重设计（4 张 2×2）

✅ **PASS**
- `SUGGESTIONS` 严格 4 条：符合规范
- `grid-cols-2 gap-2.5 w-full max-w-2xl mx-auto`：与 Spec §改动6 一致
- 卡片 hover：`hover:bg-slate-50 hover:border-slate-300`（去掉蓝色高亮）：符合规范
- `focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400`：键盘无障碍保留
- 4 条文案（含 `hint`）与 Spec §改动6 文案表逐字吻合

### 改动 7：idle 态主内容区垂直居中

✅ **PASS**
- 根容器：`relative flex flex-col min-h-screen bg-white`：符合规范
- `<main>` idle 态：`items-center justify-center`，有结果态去掉该组合：符合规范
- `pb-40` 预留底部空间：符合规范（Spec 分析 AskBar ≈132px + 28px 呼吸 = 160px）
- `WelcomeHero` 仅 idle 态渲染：符合规范
- `space-y-8`（idle）/ `pt-6 space-y-6`（有结果态）：符合规范

### 改动 8：AskBar 底部固定容器视觉优化

✅ **PASS**
- 外层：`fixed bottom-0 right-0 z-20 pointer-events-none`：符合规范
- 渐变条：`h-3 w-full bg-gradient-to-t from-white to-white/0 aria-hidden="true"`：符合规范
- AskBar 实际容器：`bg-white pt-2 pb-5 pointer-events-auto`：符合规范
- `--conv-bar-w` CSS 变量引用：符合规范
- AI 免责提示新增：`text-[11px] text-slate-400`：符合规范
- 去掉原 `border-t border-slate-200` 和 `backdrop-blur`：符合规范

### 改动 9：主内容区背景和整体间距统一

✅ **PASS**
- `HomeLayout.tsx` 根容器：`flex min-h-screen bg-white`（原 `bg-slate-50`）：符合规范
- `page.tsx` 根容器：`relative flex flex-col min-h-screen bg-white`：符合规范（已在改动7中体现）
- `--conv-bar-w` CSS 变量设置：`collapsed ? '0px' : '260px'`：保持不变，符合规范

---

## Spec 额外关键 class 逐项核查

| 检查项 | 期望值 | 实际值 | 状态 |
|--------|--------|--------|------|
| ConversationBar 顶部品牌区 | `h-14 px-3 border-b border-slate-100` | ✓ L123 | ✅ |
| WelcomeHero h1 | `text-2xl font-semibold text-slate-800 tracking-tight` | ✓ L31 | ✅ |
| SuggestionGrid 列数 | `grid-cols-2` 严格固定 | ✓ L25 | ✅ |
| SuggestionGrid 条数 | 4 条 | ✓ 4 条 | ✅ |
| SuggestionGrid hover | `hover:bg-slate-50` | ✓ L32 | ✅ |
| page.tsx idle `<main>` | `items-center justify-center` | ✓ L175 | ✅ |
| AskBar 外层容器 | `pointer-events-none` | ✓ L267 | ✅ |
| AskBar 内层容器 | `pointer-events-auto` | ✓ L273 | ✅ |
| HomeLayout 背景 | `bg-white`（非渐变，非 slate-50） | ✓ L71 | ✅ |

---

## 结论

**PASS（含 1 个 lint 告警）**

9 项改动的 Spec 符合度全部通过。唯一偏差：`OpsSnapshotPanel` import（L19 of page.tsx）未按 Spec §改动4 要求删除，在严格 lint / CI 环境下会触发 `no-unused-vars` 错误，需在合并前修复。
