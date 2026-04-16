# Spec 21: 首页重构 -- 对话式 AI 助手界面

> 状态: Draft  
> 作者: Forrest  
> 日期: 2026-04-16  
> 依赖: Spec 18 (菜单重构), Spec 14 (NL-to-Query Pipeline)

---

## 1. 体验目标

将首页从"搜索框 + 问候语 + 功能图标入口"重构为**对话式 AI 助手界面**，参考 Agents SRM 的布局范式，适配 Mulan BI 的数据建模与治理场景。

核心目标：
- 让用户一进入平台即可通过对话完成数据问答、DDL 检查、质量扫描等核心工作
- 保留历史对话，支持快速回溯和继续
- 通过建议问题降低首次使用门槛
- 不破坏现有 5 域导航体系（AppSidebar），首页采用专用布局

---

## 2. 页面结构

### 2.1 整体布局 (ASCII)

```
+------------------+----------------------------------------------+
|                  |                                              |
|  ConversationBar |              MainContent                     |
|  (260px)         |          (flex-1, 居中内容)                   |
|                  |                                              |
|  +------------+  |     +------------------------------+         |
|  | NewChat    |  |     |      [Logo]                  |         |
|  +------------+  |     |   Mulan Platform              |         |
|  | SearchBox  |  |     |   数据建模与治理平台           |         |
|  +------------+  |     +------------------------------+         |
|  |            |  |                                              |
|  | 对话历史    |  |     快速开始                                  |
|  | - 标题+时间 |  |     +-------------+  +-------------+        |
|  | - 标题+时间 |  |     | 建议问题 1   |  | 建议问题 2   |        |
|  | - 标题+时间 |  |     +-------------+  +-------------+        |
|  |            |  |     +-------------+  +-------------+        |
|  +------------+  |     | 建议问题 3   |  | 建议问题 4   |        |
|  |            |  |     +-------------+  +-------------+        |
|  | 底部导航    |  |                                              |
|  | - 数据治理  |  |     +------------------------------+         |
|  | - 资产浏览  |  |     | AskBar 输入框               |         |
|  | - 系统管理  |  |     +------------------------------+         |
|  +------------+  |                                              |
+------------------+----------------------------------------------+
```

### 2.2 路由与布局关系

当前 `path: '/'` 的 HomePage 是**独立渲染**的（不在 AppShellLayout 内）。重构后保持这一结构不变：

- **首页 `/`**: 使用**专用的 HomeLayout**，包含 ConversationBar + MainContent
- **其他页面 `/dev/*`, `/governance/*` 等**: 继续使用 AppShellLayout + AppSidebar
- **对话详情页 `/chat/:id`**: 新增路由，同样使用 HomeLayout，MainContent 替换为对话流

```
路由 /           -> HomeLayout > HomePage (欢迎 + 建议问题)
路由 /chat/:id   -> HomeLayout > ChatPage (对话详情)
路由 /dev/*      -> AppShellLayout > 各功能页
```

---

## 3. 组件拆分方案

### 3.1 新增组件

| 组件 | 路径 | 职责 |
|------|------|------|
| `HomeLayout` | `components/layout/HomeLayout.tsx` | 首页专用布局壳，包含 ConversationBar + 主内容插槽 |
| `ConversationBar` | `pages/home/components/ConversationBar.tsx` | 左侧对话历史栏 |
| `NewChatButton` | `pages/home/components/NewChatButton.tsx` | 新建对话按钮 |
| `ConversationSearch` | `pages/home/components/ConversationSearch.tsx` | 搜索历史对话 |
| `ConversationList` | `pages/home/components/ConversationList.tsx` | 对话历史列表 |
| `ConversationItem` | `pages/home/components/ConversationItem.tsx` | 单条对话记录 |
| `QuickNavLinks` | `pages/home/components/QuickNavLinks.tsx` | 底部快捷导航入口 |
| `WelcomeHero` | `pages/home/components/WelcomeHero.tsx` | 居中 Logo + 标题 + 副标题 |
| `SuggestionGrid` | `pages/home/components/SuggestionGrid.tsx` | 2x2 建议问题卡片网格 |

### 3.2 修改组件

| 组件 | 变更 |
|------|------|
| `ExamplePrompts.tsx` | **废弃**，由 SuggestionGrid 替代（从横向 pill 列表改为 2x2 卡片网格）|
| `AskBar.tsx` | **保留并改造**：调整视觉样式适配新布局，从 rounded-full 改为 rounded-xl；增加附件/语音按钮占位 |
| `page.tsx (HomePage)` | **重写**：移除问候语和功能图标入口，改为 WelcomeHero + SuggestionGrid + AskBar 的组合 |

### 3.3 不变组件

| 组件 | 说明 |
|------|------|
| `AppSidebar.tsx` | 不修改，继续服务于 AppShellLayout 下的功能页面 |
| `AppShellLayout.tsx` | 不修改 |
| `AppHeader.tsx` | 不修改（首页不使用 AppHeader，ConversationBar 顶部自带 Logo） |
| `SearchResult.tsx` | 保留，未来在对话详情页中复用 |

---

## 4. 布局尺寸与间距定义

### 4.1 ConversationBar (左侧栏)

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 宽度 (展开) | 260px | `w-[260px]` |
| 宽度 (折叠) | 0px (完全隐藏) | `w-0 overflow-hidden` |
| 背景色 | white | `bg-white` |
| 右边框 | 1px slate-200 | `border-r border-slate-200` |
| 内边距 (水平) | 12px | `px-3` |
| 内边距 (顶部) | 16px | `pt-4` |

**NewChatButton:**

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 高度 | 40px | `h-10` |
| 圆角 | 10px | `rounded-[10px]` |
| 背景色 | blue-600 (#2563EB) | `bg-blue-600` |
| hover 背景色 | blue-700 | `hover:bg-blue-700` |
| 文字色 | white | `text-white` |
| 文字大小 | 14px | `text-sm` |
| 图标 | `ri-add-line` | -- |
| 宽度 | 100% | `w-full` |

**ConversationSearch:**

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 上间距 | 12px | `mt-3` |
| 高度 | 36px | `h-9` |
| 背景色 | slate-50 | `bg-slate-50` |
| 边框 | 1px slate-200 | `border border-slate-200` |
| 圆角 | 8px | `rounded-lg` |
| Placeholder | "搜索历史对话" | -- |
| 图标 | `ri-search-line` (左侧内嵌) | -- |

**ConversationItem:**

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 内边距 | 8px 12px | `px-3 py-2` |
| 圆角 | 8px | `rounded-lg` |
| 标题字号 | 13px | `text-[13px]` |
| 标题颜色 | slate-700 | `text-slate-700` |
| 标题行数 | 单行截断 | `truncate` |
| 时间字号 | 11px | `text-[11px]` |
| 时间颜色 | slate-400 | `text-slate-400` |
| hover 背景 | slate-50 | `hover:bg-slate-50` |
| 选中态背景 | blue-50 | `bg-blue-50` |
| 选中态标题色 | blue-700 | `text-blue-700` |
| 左侧图标 | `ri-message-3-line` | -- |
| 上下文菜单 | hover 时右侧出现 `ri-more-2-fill`，点击弹出删除/重命名 | -- |

**QuickNavLinks (底部固定区):**

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 位置 | 底部固定 | `mt-auto` |
| 上边框 | 1px slate-100 | `border-t border-slate-100` |
| 内边距 | 8px 12px | `px-3 py-2` |
| 每项高度 | 36px | `h-9` |
| 图标大小 | 16px | `text-base` |
| 文字大小 | 13px | `text-[13px]` |
| 链接颜色 | slate-500 | `text-slate-500` |
| hover 颜色 | slate-700 | `hover:text-slate-700` |

导航入口列表:

| 图标 | 文字 | 路由 |
|------|------|------|
| `ri-shield-check-line` | 数据治理 | `/governance/health` |
| `ri-bar-chart-box-line` | 资产浏览 | `/assets/tableau` |
| `ri-settings-3-line` | 系统管理 | `/system/users` (仅 admin 可见) |

### 4.2 MainContent (主内容区)

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 背景 | 渐变 slate-50 -> blue-50 | `bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50` |
| 内容最大宽度 | 640px | `max-w-[640px]` |
| 水平居中 | 是 | `mx-auto` |
| 水平内边距 | 24px | `px-6` |
| 顶部间距 | 视口高度 20% | `pt-[20vh]`（空状态时垂直居中偏上）|

**WelcomeHero:**

| 元素 | 样式 |
|------|------|
| Logo 图片 | 56x56, `rounded-xl`, 居中, `mb-4` |
| 产品名 | `text-2xl font-bold text-slate-800`, `mb-1` |
| 副标题 | `text-sm text-slate-400`, `mb-10` |
| 副标题文案 | "通过对话完成数据查询、建模检查与治理工作" |

**SuggestionGrid:**

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 标签文字 | "快速开始" | `text-xs text-slate-400 mb-3` |
| 网格布局 | 2 列 | `grid grid-cols-2 gap-3` |
| 响应式 | < 640px 变 1 列 | `grid-cols-1 sm:grid-cols-2` |
| 下间距 | 32px | `mb-8` |

**SuggestionCard (单个):**

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 边框 | 1px slate-200 | `border border-slate-200` |
| 背景 | white | `bg-white` |
| 圆角 | 12px | `rounded-xl` |
| 内边距 | 16px | `p-4` |
| 文字大小 | 13px | `text-[13px]` |
| 文字颜色 | slate-600 | `text-slate-600` |
| hover 边框 | blue-300 | `hover:border-blue-300` |
| hover 背景 | blue-50/50 | `hover:bg-blue-50/50` |
| hover 文字 | slate-800 | `hover:text-slate-800` |
| 过渡 | 150ms | `transition-all duration-150` |
| 光标 | pointer | `cursor-pointer` |
| 左上角图标 | `ri-questionnaire-line` slate-300, hover 时 blue-400 | -- |

建议问题内容:

```
1. "Q1 各区域销售额对比是怎样的？"
2. "帮我检查 orders 表的 DDL 规范"
3. "最近一周数据质量扫描有异常吗？"
4. "Tableau 仪表盘中哪些字段缺少语义定义？"
```

**AskBar (底部输入区, 改造后):**

| 属性 | 值 | Tailwind |
|------|-----|----------|
| 位置 | 主内容区底部固定 | `fixed bottom-0` 或 `mt-auto` 视实现 |
| 最大宽度 | 640px, 居中 | `max-w-[640px] mx-auto` |
| 下间距 | 24px | `pb-6` |
| 输入框圆角 | 16px | `rounded-2xl` |
| 输入框背景 | white | `bg-white` |
| 输入框边框 | 1px slate-200 | `border border-slate-200` |
| focus 边框 | blue-400 | `focus:border-blue-400` |
| focus 阴影 | ring-2 blue-100 | `focus:ring-2 focus:ring-blue-100` |
| 发送按钮 | 圆形, bg-blue-600, 右侧内嵌 | -- |
| 底部提示 | "点击建议问题或直接输入，开始对话" | `text-xs text-slate-400 text-center mt-2` |

---

## 5. 交互行为定义

### 5.1 新建对话

| 触发 | 行为 |
|------|------|
| 点击 "新建对话" 按钮 | 清空主内容区，回到 WelcomeHero + SuggestionGrid 空状态，AskBar 获得焦点；URL 导航到 `/` |
| 快捷键 `Ctrl/Cmd + N` | 同上（P1，非首版必须） |

### 5.2 发起提问

| 触发 | 行为 |
|------|------|
| 在 AskBar 输入文字并按 Enter (非 Shift) | 创建新对话，URL 跳转 `/chat/:newId`；主内容区切换为对话流视图；左侧栏顶部插入新对话记录 |
| 点击建议问题卡片 | 同上，问题文本作为首条消息 |
| Shift + Enter | 输入框内换行，不提交 |

### 5.3 对话历史交互

| 触发 | 行为 |
|------|------|
| 点击对话记录 | URL 导航到 `/chat/:id`，主内容区加载该对话的消息流 |
| hover 对话记录 | 背景变为 slate-50，右侧出现 `...` 更多操作按钮 |
| 点击 `...` 更多按钮 | 弹出下拉菜单: "重命名" / "删除" |
| 删除对话 | 弹出确认弹窗 "确定删除这条对话吗？删除后无法恢复"，确认后从列表移除并跳回 `/` |
| 重命名对话 | 标题变为 inline 可编辑 input，Enter 确认，Esc 取消 |

### 5.4 搜索历史对话

| 触发 | 行为 |
|------|------|
| 在搜索框输入 | 300ms debounce 后过滤对话列表（前端本地过滤，按标题模糊匹配） |
| 搜索无结果 | 列表区显示 "没有找到相关对话" |
| 清空搜索框 | 恢复完整列表 |

### 5.5 左侧栏折叠

| 触发 | 行为 |
|------|------|
| 点击 ConversationBar 顶部折叠按钮 | 左侧栏宽度 260px -> 0px，带 200ms ease 过渡动画；主内容区自动占满全宽 |
| 折叠后展开 | 主内容区左上角出现 hamburger 按钮 `ri-menu-line`，点击展开 |
| < 768px (移动端) | 默认隐藏左侧栏；hamburger 按钮固定显示；点击后左侧栏以 overlay 方式滑出（带半透明遮罩） |
| 折叠状态持久化 | 使用 localStorage key `mulan-home-sidebar-collapsed` |

### 5.6 建议问题卡片

| 触发 | 行为 |
|------|------|
| hover | border 变 blue-300, 背景微蓝 |
| click | 等同于在 AskBar 提交该问题文本（见 5.2） |
| 对话中状态 | SuggestionGrid 不显示（仅空状态/欢迎页可见） |

---

## 6. 状态设计

### 6.1 未登录状态

与现有行为一致：显示登录引导卡片，不显示 ConversationBar。

### 6.2 已登录 -- 无对话历史 (首次使用)

- ConversationBar: 对话列表区为空，显示空状态插画 + 文案 "还没有对话记录"
- MainContent: WelcomeHero + SuggestionGrid + AskBar 完整显示
- 底部提示: "点击建议问题或直接输入，开始对话"

### 6.3 已登录 -- 有对话历史 (常规)

- ConversationBar: 按时间倒序展示对话列表，分组标签: "今天" / "昨天" / "过去 7 天" / "更早"
- MainContent: 同 6.2（欢迎页），或如果 URL 为 `/chat/:id` 则显示对话流

### 6.4 对话进行中

- MainContent: 消息流视图（用户消息靠右，AI 回复靠左）
- AI 回复加载中: 显示 typing indicator（三点跳动动画）+ 文字 "正在分析..."
- AskBar: 固定在底部，可继续输入追问
- WelcomeHero 和 SuggestionGrid: 隐藏
- 左侧栏当前对话高亮 (blue-50 背景)

### 6.5 对话加载失败

- 消息流中 AI 回复位置显示 ErrorCard（复用现有 SearchResult 的 ErrorCard 组件）
- 显示重试按钮
- AskBar 保持可用

### 6.6 对话历史加载失败

- ConversationBar 列表区显示: "加载失败" + 重试按钮
- 不影响主内容区，用户仍可发起新对话

### 6.7 网络断开

- AskBar 发送按钮 disabled
- AskBar 下方出现横幅: "网络连接已断开，请检查网络" (amber 色调)

---

## 7. 视觉方向

### 7.1 色彩体系

保持现有浅色主题，不引入深色 UI。色彩沿用 Tailwind 配置中已定义的语义色:

| 用途 | 色值 | Token |
|------|------|-------|
| 主色 (按钮/选中) | #2563EB | `blue-600` / `link-primary` |
| 主色 hover | #1D4ED8 | `blue-700` / `btn-primary-bg` |
| 文字主色 | #1A202C | `text-primary` |
| 文字次要 | #374151 | `text-secondary` |
| 文字占位/辅助 | #6B7280 | `text-placeholder` |
| 边框默认 | #E2E8F0 | `border-light` / `slate-200` |
| 背景主体 | 渐变 slate-50 to blue-50 | 现有首页背景 |
| 侧栏背景 | #FFFFFF | `white` |
| 卡片背景 | #FFFFFF | `white` |
| hover 背景 | #F8FAFC | `slate-50` |
| 选中背景 | #EFF6FF | `blue-50` |
| focus ring | #3B82F6 | `focus-ring` / `blue-500` |

### 7.2 字体规范

| 元素 | 大小 | 字重 | 行高 |
|------|------|------|------|
| 产品名 (WelcomeHero) | 24px (`text-2xl`) | bold (700) | 1.3 |
| 副标题 | 14px (`text-sm`) | normal (400) | 1.5 |
| SuggestionCard 文字 | 13px (`text-[13px]`) | medium (500) | 1.5 |
| "快速开始" 标签 | 12px (`text-xs`) | medium (500) | 1 |
| 对话标题 | 13px (`text-[13px]`) | medium (500) | 1.4 |
| 对话时间 | 11px (`text-[11px]`) | normal (400) | 1 |
| AskBar placeholder | 16px (`text-base`) | normal (400) | 1.5 |
| 底部提示文字 | 12px (`text-xs`) | normal (400) | 1 |

### 7.3 圆角体系

| 元素 | 圆角 |
|------|------|
| SuggestionCard | 12px (`rounded-xl`) |
| AskBar 输入框 | 16px (`rounded-2xl`) |
| NewChatButton | 10px (`rounded-[10px]`) |
| ConversationItem | 8px (`rounded-lg`) |
| 搜索框 | 8px (`rounded-lg`) |
| 发送按钮 | full (`rounded-full`) |

### 7.4 阴影

整体风格偏平坦，仅以下场景使用阴影:
- AskBar 输入框 focus 时: `ring-2 ring-blue-100`
- 移动端 ConversationBar overlay: `shadow-xl`
- ConversationItem 右键菜单下拉: `shadow-lg`

---

## 8. 界面文案

| 位置 | 文案 |
|------|------|
| WelcomeHero 产品名 | Mulan Platform |
| WelcomeHero 副标题 | 通过对话完成数据查询、建模检查与治理工作 |
| 快速开始标签 | 快速开始 |
| 建议问题 1 | Q1 各区域销售额对比是怎样的？ |
| 建议问题 2 | 帮我检查 orders 表的 DDL 规范 |
| 建议问题 3 | 最近一周数据质量扫描有异常吗？ |
| 建议问题 4 | Tableau 仪表盘中哪些字段缺少语义定义？ |
| AskBar placeholder | 输入你的数据问题 |
| 底部引导 | 点击建议问题或直接输入，开始对话 |
| NewChatButton | 新建对话 |
| 搜索框 placeholder | 搜索历史对话 |
| 空对话历史 | 还没有对话记录 |
| 搜索无结果 | 没有找到相关对话 |
| 删除确认标题 | 删除对话 |
| 删除确认正文 | 确定删除这条对话吗？删除后无法恢复。 |
| 加载中 | 正在分析... |
| 网络断开横幅 | 网络连接已断开，请检查网络 |
| 对话历史分组 | 今天 / 昨天 / 过去 7 天 / 更早 |

---

## 9. 响应式断点行为

| 断点 | ConversationBar | MainContent | AskBar |
|------|----------------|-------------|--------|
| >= 1280px | 展开 260px，可手动折叠 | max-w-[640px] 居中 | 640px 居中 |
| 768px ~ 1279px | 默认折叠，可手动展开 | max-w-[640px] 居中 | 640px 居中 |
| < 768px | 隐藏，overlay 模式 | 全宽 px-4 | 全宽 px-4, 固定底部 |

移动端 ConversationBar overlay 规则:
- 点击 hamburger 按钮后，ConversationBar 从左侧滑入
- 背景出现半透明遮罩 (`bg-black/30`)
- 点击遮罩或选择对话后自动关闭
- 滑入/滑出动画 200ms ease

---

## 10. 与现有 AppSidebar 的关系处理

### 方案: 独立布局，互不干扰

| 维度 | 首页 (/ 和 /chat/:id) | 功能页 (/dev/*, /governance/* 等) |
|------|----------------------|----------------------------------|
| 布局组件 | HomeLayout (新增) | AppShellLayout (不变) |
| 侧栏 | ConversationBar (对话历史) | AppSidebar (5 域导航) |
| 顶栏 | 无独立顶栏 (ConversationBar 顶部含 Logo) | AppHeader |
| 侧栏宽度 | 260px | 240px (展开) / 56px (折叠) |

路由配置变更 (`router/config.tsx`):

```
当前:
  { path: '/', element: <Home /> }

改为:
  {
    element: <HomeLayout />,
    children: [
      { path: '/',          element: <HomePage /> },
      { path: '/chat/:id',  element: <ChatPage /> },
    ],
  }
```

QuickNavLinks 底部导航提供从首页跳转到功能页的通道，点击后进入 AppShellLayout 体系，侧栏自动切换为 AppSidebar。这是两套独立的布局，用户心智模型清晰:

- 首页 = AI 助手对话空间
- 功能页 = 传统管理后台

---

## 11. 对话历史时间分组逻辑

前端根据对话的 `updated_at` 时间戳进行分组:

| 分组标签 | 规则 |
|---------|------|
| 今天 | 当日 00:00 至当前 |
| 昨天 | 前一日 00:00 ~ 23:59 |
| 过去 7 天 | 2~7 天前 |
| 更早 | 7 天以上，按月显示 (如 "3月", "2月") |

每条对话显示的时间格式:
- 今天: "14:30"
- 昨天: "昨天"
- 7 天内: "3天前"
- 更早: "4月8日"

---

## 12. 前端实现注意事项

### 12.1 数据层

- 对话历史需要后端 API 支持 (当前不存在)，前端先用 localStorage 做本地对话存储作为 fallback
- 对话 ID 生成: 前端使用 `crypto.randomUUID()` 生成，后端同步后以后端 ID 为准
- 对话列表 API 建议: `GET /api/conversations?page=1&limit=50`
- 对话详情 API 建议: `GET /api/conversations/:id/messages`
- 对话列表首屏加载最近 50 条，滚动到底部加载更多

### 12.2 状态管理

- ConversationBar 的折叠状态: localStorage `mulan-home-sidebar-collapsed`
- 对话列表数据: 建议使用 React Context 或轻量 store (如 zustand)，避免 prop drilling
- AskBar 的输入状态: 组件内部 useState，不上提

### 12.3 动画与过渡

- ConversationBar 折叠/展开: `transition-all duration-200 ease-in-out`
- SuggestionCard hover: `transition-all duration-150`
- 移动端 overlay 滑入: `transition-transform duration-200`
- 消息出现: 简单 fade-in `animate-fadeIn` (可选，非 P0)

### 12.4 无障碍

- NewChatButton: `aria-label="新建对话"`
- 搜索框: `role="search"`, `aria-label="搜索历史对话"`
- SuggestionCard: `role="button"`, `tabIndex={0}`, 支持 Enter 触发
- ConversationItem: `aria-current="true"` 标记当前选中对话
- 折叠按钮: `aria-expanded` 动态更新

### 12.5 性能

- 对话列表使用虚拟滚动 (当对话数 > 100 时)，推荐 `@tanstack/react-virtual`
- SuggestionGrid 的 4 个建议问题静态渲染，无性能顾虑
- 搜索 debounce 300ms，避免频繁过滤

### 12.6 文件结构预览

```
frontend/src/
  components/layout/
    HomeLayout.tsx          # 新增
    AppShellLayout.tsx      # 不变
    AppSidebar.tsx          # 不变
    AppHeader.tsx           # 不变
  pages/home/
    page.tsx                # 重写
    components/
      AskBar.tsx            # 改造
      ConversationBar.tsx   # 新增
      ConversationSearch.tsx# 新增
      ConversationList.tsx  # 新增
      ConversationItem.tsx  # 新增
      NewChatButton.tsx     # 新增
      QuickNavLinks.tsx     # 新增
      WelcomeHero.tsx       # 新增
      SuggestionGrid.tsx    # 新增
      SearchResult.tsx      # 保留
      ExamplePrompts.tsx    # 废弃 (保留文件，标注 @deprecated)
  pages/chat/
    page.tsx                # 新增 (P1，首版可只做占位)
  router/
    config.tsx              # 修改 (增加 HomeLayout wrapper 和 /chat/:id 路由)
```

---

## 13. 分期交付建议

### P0 (首版)

- HomeLayout + ConversationBar 基本结构
- WelcomeHero + SuggestionGrid + AskBar 改造
- 点击建议问题 -> 调用现有 askQuestion API -> 在主内容区显示结果 (复用 SearchResult)
- 对话历史存 localStorage (无后端)
- 左侧栏折叠/展开 + 移动端 overlay
- QuickNavLinks 底部导航

### P1 (二期)

- `/chat/:id` 对话详情页 (消息流视图)
- 后端对话历史 API 对接
- 对话重命名/删除
- 搜索历史对话
- 对话列表虚拟滚动

### P2 (三期)

- 多轮对话上下文
- 对话中嵌入图表/表格可视化
- 快捷键支持
- 对话导出

---

## 14. 设计共识记录（2026-04-16）

以下 7 点经 Human 确认，作为后续开发的准则，优先级高于原 Spec 描述。

### C1：P0 结果原地展示，不跳转

P0 阶段用户提交问题后，结果在 HomePage 原地展示（复用现有 `SearchResult.tsx`），URL 保持 `/`，**不跳转** `/chat/:id`。`/chat/:id` 路由及 ChatPage 推迟到 P1 实现。

### C2：localStorage Schema 与后端 API 结构对齐

P0 使用 localStorage 存储对话历史时，schema 必须与 P1 后端 API 响应结构一致：

```ts
interface Conversation {
  id: string;           // uuid
  title: string;        // 取首条消息前 20 字
  updated_at: string;   // ISO 8601 UTC
  messages: ConversationMessage[];
}

interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;   // ISO 8601 UTC
  query_context?: QueryContext; // P2 预留字段，P0/P1 写入 undefined
}
```

P1 只需将 ConversationStore 数据源从 localStorage 切换到后端 API，不改数据结构。

### C3：MCP Session 字典 P0 不限上限，P1 实现 LRU

P0 改造 `mcp_client.py` 时，`_get_or_create_session_state()` 预留 `_max_sites: int = 0`（0 表示不限制）。P1 实现 LRU 驱逐，上限默认 50。

### C4：P0 前端不传 connection_id，后端自动路由

P0 阶段 `AskBar` 提交时不传 `connection_id`，后端 `route_datasource()` 自动选第一个 active 连接。P1 才在前端增加连接选择器。

### C5：时间分组使用浏览器本地时区

ConversationList 对话分组（今天/昨天/过去 7 天/更早）一律使用浏览器本地时区计算，后端返回的 `updated_at` 为 UTC ISO 字符串，前端转换为本地时间后再做分组判断。

### C6：LLM 多配置管理为 admin-only，入口在现有系统管理页

LLM 配置 CRUD API 需要 admin 角色权限。前端管理页挂载在现有系统管理区域（`/system/llm-configs`），组件路径为 `frontend/src/pages/admin/llm-configs/page.tsx`，P1 实现。

### C7：conversation_messages 表 P1 建表时预留 query_context 字段

P1 创建 `conversation_messages` 表时，预留 `query_context JSONB` 列，结构如下：

```json
{
  "connection_id": 1,
  "datasource_luid": "xxxx",
  "field_names": ["销售额", "区域"],
  "vizql_json": {}
}
```

P1 不写入该字段（存 NULL），P2 追问功能直接读取，避免破坏性改表。
