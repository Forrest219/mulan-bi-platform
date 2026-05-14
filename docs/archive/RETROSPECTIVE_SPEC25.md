# Spec 25 UI/UX 复盘报告

> 作者: PM Agent
> 日期: 2026-04-18
> 基于: Spec 25 v1.1（2026-04-18）、代码实际状态（commit 54191ec 前后）

---

## 执行摘要

Spec 25 聚焦于对输入栏、登录页、Sidebar 四态状态机、拖拽遮罩等局部组件的样式规范化，但它天然继承了 Spec 21（首页重构）已奠定的整体布局决策——包括"左侧 ConversationBar + 右侧主内容"的 HomeLayout 结构。当前首页的**整体布局框架已符合 Spec 21 的设计意图**，并非与 open-webui 毫无关联。然而，Spec 25 所要求的若干局部样式规范（毛玻璃 AskBar、Sidebar 4态状态机、附件气泡预览、拖拽遮罩）在当前代码中并未完全落地。核心原因有两条：第一，首页的 ConversationBar 并未采用 Spec 25 §7.2 所描述的 Sidebar 组件（4 态状态机），而是延续了 Spec 21 的自定义 `ConversationBar`；第二，AskBar 是为"BI 问数"场景高度定制的组件（无文件上传、使用 `bg-white` 而非毛玻璃），与 Spec 25 §7.3 描述的通用聊天 AskBar 存在设计目标差异，而这一差异在 Spec 25 中未被明确声明为"豁免场景"。

---

## Gap 逐项分析

### Gap-A  整体布局：ConversationBar 与 Spec 25 Sidebar 4 态状态机脱钩

**Spec 要求（§5.2）：**
Sidebar 应实现 4 态状态机（A: Desktop 展开 `w-60`、B: Desktop 折叠 `w-14`、C: Mobile 覆层 `translate-x-0 fixed z-30`、D: Mobile 隐藏 `-translate-x-full`），并配合 `transition-[width]` / `transition-transform` 动画。

**当前实现（HomeLayout.tsx + ConversationBar.tsx）：**
- HomeLayout 用 `style={{ width: collapsed ? 0 : 260 }}` 控制宽度，ConversationBar 本身不含折叠逻辑（`collapsed` prop 被接收但未使用，形参名前缀了 `_collapsed` 表明未实际使用）
- 无 Desktop 折叠态（w-14 图标模式）：只有"展开 260px"和"完全收起 0px"两种状态
- 无 Mobile 覆层态（fixed + overlay 遮罩）：移动端下 ConversationBar 直接消失（宽度变 0），不是 Spec 要求的滑入/滑出动画
- ConversationBar 背景为 `bg-slate-50`，而 Spec §7.2 要求 `bg-white`
- 汉堡菜单由 HomeLayout 全局键盘快捷键（`Escape` 键）控制，而非 Spec §5.2 要求的 `mobileOpen/setMobileOpen` 状态机

**差距描述：**
只实现了 A（展开）和"无 sidebar"两态，缺少 B（折叠态 w-14）、C（Mobile 覆层）、D（Mobile 隐藏滑出）三态。Desktop 折叠按钮在当前实现中也缺失（ConversationBar 顶部只有"新对话"按钮，无折叠切换入口）。

**根因：** [x] coder 未执行 [x] spec 未覆盖（Spec 25 的 Sidebar §7.2 是独立组件模板，未明确说明是否要替换 ConversationBar，两者在设计目标上存在混淆）

**严重程度：P1**

---

### Gap-B  AskBar：样式不符合毛玻璃规范，且缺少文件附件能力

**Spec 要求（§4.3、§7.3）：**
AskBar 主容器应为：`rounded-2xl border shadow-sm backdrop-blur-sm bg-white/80 border-slate-200/60 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20`。
应含 AttachmentBubble 预览行、Paperclip 附件按钮、发送按钮（激活条件：有文字 OR 有附件）。

**当前实现（`pages/home/components/AskBar.tsx` 第112行）：**
```
className="relative rounded-2xl border border-slate-200 bg-white shadow-sm px-3 py-3"
```
- 无 `backdrop-blur-sm`，无 `bg-white/80`（用 `bg-white` 实色替代）
- 无 `focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20`（无 focus 环动效）
- 无 AttachmentBubble 组件、无 Paperclip 附件按钮
- 发送按钮使用 `bg-slate-900 hover:bg-slate-800`，而 Spec 要求激活态 `bg-blue-700 hover:bg-blue-800`、禁用态 `bg-slate-100 text-slate-300`
- 额外增加了 BI 专用的连接选择器 `<select>`（Spec 未涉及，为 Spec 21/22 需求演进产物）
- 快捷键提示 `⌘K` 存在（合理扩展），但 Spec 未定义此 UI

**差距描述：**
毛玻璃效果（backdrop-blur-sm + bg-white/80）完全缺失；附件上传能力（Gap-02 AC）未实现；发送按钮品牌色不符（slate-900 vs blue-700）；focus 交互态缺失。

**根因：** [x] coder 未执行（AskBar 被较早交付，Spec 25 的样式规范晚于功能实现，新规范未回溯修改）[x] 设计决策矛盾（Spec 21/22 的 BI 专用 AskBar 与 Spec 25 的通用 AskBar 组件之间，spec 没有明确声明"哪个版本适用于首页"）

**严重程度：P1**

---

### Gap-C  Gap-02 附件气泡：AC 验收项未在首页实现

**Spec 要求（§8.2 Gap-02）：**
点击附件按钮后弹出文件选择对话框；图片显示 64x64 缩略图气泡；非图片显示文件名+大小；hover 显示 X 删除；仅有附件时发送按钮可点击。验收 AC-02-01 至 AC-02-09。

**当前实现：**
首页 `AskBar.tsx` 中不存在 `<input type="file" />`、不存在 AttachmentBubble、不存在 Paperclip 图标按钮。Spec 25 §7.3 的完整 AskBar + AttachmentBubble 代码块提供了参考实现，但未被执行。

**差距描述：**
Gap-02 所有 AC（AC-02-01 至 AC-02-09）均未实现，当前首页 AskBar 不具备任何文件上传能力。

**根因：** [x] coder 未执行（Spec 25 提供了完整实现代码，但首页 AskBar 沿用了更早的 Spec 21 版本，未被替换）

**严重程度：P1**

---

### Gap-D  Gap-03 拖拽遮罩：当前首页不存在 DragDropOverlay

**Spec 要求（§5.4、§7.4、§8.3）：**
`DragDropOverlay` 组件挂载于页面根容器，监听 window 级别 drag 事件；遮罩 `fixed inset-0 z-50`、`bg-slate-50/90 backdrop-blur-sm`；显示虚线框 + 上传图标 + 提示文字；drop 后触发 Gap-02 附件预览流程。

**当前实现：**
检索首页 `page.tsx` 及其 import 列表，无任何 `DragDropOverlay` 相关引用，也无 `dragenter/dragleave/drop` 的 window 事件监听。

**差距描述：**
Gap-03 所有 AC（AC-03-01 至 AC-03-06）均未实现。由于 Gap-02 未实现，Gap-03 的前置依赖也不满足。

**根因：** [x] coder 未执行 [x] 依赖缺失（Gap-02 未实现导致 Gap-03 无法完整交付）

**严重程度：P1**

---

### Gap-E  登录页：与 Spec 25 §7.1 基本对齐，但存在细微偏差

**Spec 要求（§7.1）：**
- Logo 区居中：`text-center mb-8`
- 标题：`text-2xl font-bold text-slate-900`
- 副标题：`text-sm text-slate-500`
- "忘记密码"使用 `onClick + navigate`（避免全页刷新，陷阱 3）

**当前实现（`pages/login/page.tsx`）：**
- Logo 区左对齐（`flex-col items-start mb-6`），而非 Spec 的 `text-center mb-8`
- 标题 `text-xl font-semibold`（Spec 要求 `text-2xl font-bold`）
- 副标题 `text-slate-600`（Spec 要求 `text-slate-500`）
- "忘记密码"使用 `<Link to="/forgot-password">`（React Router Link，无全页刷新问题，陷阱 3 已规避）
- 新增了"密码显示/隐藏"切换按钮（Spec 未定义，合理增强）
- 新增了"注册新账号"链接（Spec 未定义，可接受扩展）
- Gap-06 MFA 修复（`await checkAuth()` 先于 `navigate('/')`）已正确实现
- 核心颜色系统（`bg-slate-50 bg-white border-slate-200 shadow-sm blue-700`）与 Spec 完全一致

**差距描述：**
Logo 区布局（居中 vs 左对齐）和标题字号（2xl vs xl）与 Spec 有偏差，但颜色系统和交互逻辑已对齐。属于视觉细节差异。

**根因：** [x] coder 未执行（细节样式与 Spec 原文未严格对照）

**严重程度：P2**

---

### Gap-F  首页布局：HomeLayout 背景色不符合颜色 DNA

**Spec 要求（§3.1）：**
页面底色（Layer 0 canvas）应为 `bg-slate-50`。

**当前实现（HomeLayout.tsx 第71行）：**
```
className="flex min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50"
```
HomeLayout 使用渐变背景 `bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50`，而非 Spec 规定的纯色 `bg-slate-50`。

首页未登录态（`page.tsx` 第76行）同样使用了 `bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50`。

**差距描述：**
渐变背景与 Spec §3.1 的三层背景体系不兼容（三层体系基于纯色叠加，渐变会导致层级感模糊）。渐变背景是 Spec 21 时代的设计决策，Spec 25 明确规范了纯色 `bg-slate-50`，但未明确指示要废除现有渐变。

**根因：** [x] 设计决策矛盾（Spec 21 渐变背景 vs Spec 25 纯色 canvas，两个 spec 之间未对齐）[x] spec 未覆盖（Spec 25 未明确说明"HomeLayout 的 bg 需改为 bg-slate-50"）

**严重程度：P2**

---

### Gap-G  首页中央区域：SuggestionGrid 卡片与 Spec 颜色系统基本对齐，但有细节差距

**Spec 要求（§3.3 品牌强调色）：**
Hover 态应使用 `hover:bg-slate-50` 或品牌色 `hover:bg-blue-50`，聚焦态使用 `ring-blue-500`。

**当前实现（SuggestionGrid.tsx 第22行）：**
```
className="border border-slate-200 rounded-xl p-4 hover:border-blue-400 hover:bg-blue-50 cursor-pointer transition-all text-sm text-slate-600 text-left"
```
SuggestionGrid 的 hover 态（`hover:border-blue-400 hover:bg-blue-50`）与 Spec §3.3 的品牌强调色系基本对齐。

**差距描述：**
无 `focus:ring-2 focus:ring-blue-500/30`（键盘聚焦无视觉反馈），SuggestionGrid 卡片是 `<button>` 元素但缺少 focus 样式，有 a11y 隐患。卡片排版（5 个建议项放在 2 列 grid）导致最后一项单独占用半行，视觉不平衡。

**根因：** [x] spec 未覆盖（Spec 25 未专项描述 SuggestionGrid 的 focus 态和奇数卡片布局规则）

**严重程度：P2**

---

### Gap-H  Gap-01 忘记密码路由：路由存在，但后端端点状态待确认

**Spec 要求（§8.1）：**
`/forgot-password` 路由正常渲染页面（AC-01-01），`POST /api/auth/forgot-password` 对任意邮箱返回 200（AC-01-05）。

**当前实现：**
LoginPage 中"忘记密码"链接已正确使用 `<Link to="/forgot-password">`。但根据 git log 的最近 20 条提交，未见专门针对 `/forgot-password` 路由页面或后端端点的提交记录。该路由是否在前端路由配置中注册、后端是否有对应端点，无法从当前读取的文件中确认。

**差距描述：**
链接入口存在，但 `/forgot-password` 页面组件（`ForgotPasswordPage.tsx`）及后端端点的交付状态不明。

**根因：** [x] 待确认（需查阅路由配置文件和后端 auth.py）

**严重程度：P1（待确认）**

---

### Gap-I  Gap-04 Markdown 渲染 与 Gap-05 流式输出：部分实现，有结构性风险

**Spec 要求（§8.4、§8.5）：**
消息气泡渲染 Markdown（react-markdown + remark-gfm + 代码高亮）；SSE 流式输出，前端 token 实时追加，AskBar state 与 streaming state 完全隔离。

**当前实现（page.tsx 第44行、第177行）：**
- Gap-05 流式输出：`useStreamingChat` hook 已存在，streaming messages 区域已实现（消息气泡 + 打字光标动画），并且注释明确标注了"state 与 AskBar 完全隔离（§11 陷阱6）"，AskBar 也用 `memo` 包裹。结构上符合 Spec 要求。
- Gap-04 Markdown 渲染：当前流式消息使用 `<span className="whitespace-pre-wrap">`（第197行），即纯文本展示，未引入 `react-markdown`。`SearchResult` 组件的非流式路径是否支持 Markdown 渲染，需进一步确认。

**差距描述：**
Gap-05 框架已到位，但 Gap-04 Markdown 渲染（流式消息区）仍为纯文本。非流式的 SearchResult 路径的 Markdown 支持状态未知。

**根因：** [x] coder 未执行（Gap-04 Markdown 依赖未安装或未接入流式气泡）

**严重程度：P1**

---

### Gap-J  AppShellLayout（非首页）的 Sidebar：与 Spec 25 §7.2 对比

**Spec 要求（§7.2）：**
Sidebar 背景 `bg-white`，导航项 active 态 `bg-blue-50 text-blue-700`，折叠态 tooltip。

**当前实现（AppShellLayout.tsx）：**
AppShellLayout 使用 `AppSidebar` 组件（未在本次读取范围内），但 AppShellLayout 自身的 canvas 背景是 `bg-slate-50`（符合 Spec §3.1）。移动端 overlay 遮罩 `bg-black/30 z-20` 与 Spec §5.2 要求的 `bg-black/30 z-20` 一致。Desktop 折叠逻辑（`sidebarCollapsed` state）存在，但实际 Sidebar 样式取决于 `AppSidebar` 组件内部实现。

**差距描述：**
AppShellLayout 的状态机结构（isMobile + sidebarCollapsed + mobileOpen）与 Spec 25 §7.2 的 4 态模型基本一致。但移动端汉堡菜单实现为"悬浮圆形按钮（fixed bottom-4 right-4）"，而 Spec 假设汉堡按钮位于 Header 内。这是轻微结构偏差。

**根因：** [x] 设计决策矛盾（Spec 25 要求汉堡在 Header，当前实现在页面右下角浮动按钮）

**严重程度：P2**

---

## 根因总结

**根因一：Spec 25 与 Spec 21/22 存在设计决策衔接断裂，未明确指定"哪个 AskBar 适用于首页"。**
Spec 21 交付了功能优先的 BI 专用 AskBar（含连接选择器，不含文件附件），Spec 25 提供了一个全新的通用聊天 AskBar 实现模板（含文件附件，无连接选择器）。两个版本的功能定位不同，但 Spec 25 未声明"首页 AskBar 需整体替换"还是"仅需样式补丁"，导致 coder 在现有组件上做了有限修改（memo 隔离、发送按钮），未执行附件能力和毛玻璃样式。

**根因二：Gap-02（附件气泡）和 Gap-03（拖拽遮罩）两个 P1 特性在首页均未交付，Spec 25 的完整实现代码未被引入。**
从 git log 最近 20 条提交来看，没有对应首页 AskBar 附件能力的提交，coder 的交付重点集中在后端（NLQ、MCP、流式输出）和架构改造，前端 UI 细节特性（Gap-02/03）未被执行。这是典型的"后端功能优先、前端 UI 细节滞后"的交付优先级问题。

**根因三：Spec 25 部分条款与现有代码的对照检查机制缺失，没有可执行的 AC 对照单来驱动逐项验收。**
Spec 25 §8 列出了详细的 AC（验收标准），但在实际交付过程中没有对应的"AC 检查单"机制来驱动每项逐一核对，导致部分 Gap 的 AC 处于"已写入 spec、未执行验收、未在代码中实现"的悬空状态。

---

## 下一步建议

1. **（P0）补齐首页 AskBar 的毛玻璃样式和发送按钮品牌色**：将 `bg-white` 改为 `backdrop-blur-sm bg-white/80`，发送按钮激活态改为 `bg-blue-700`，可在不破坏 BI 专用连接选择器的前提下完成。

2. **（P1）实现 Gap-02 附件气泡能力**：明确首页 AskBar 是否需要文件上传（若 BI 问数场景不需要，应在 Spec 25 中正式声明豁免，否则按 §7.3 实现 AttachmentBubble）。

3. **（P1）在首页挂载 DragDropOverlay（Gap-03）**：Gap-02 完成后，`DragDropOverlay.tsx` 组件可按 §7.4 参考实现，挂载至 `page.tsx` 根容器，不破坏现有布局。

4. **（P1）为流式消息区接入 react-markdown（Gap-04）**：streaming messages 的气泡渲染从 `whitespace-pre-wrap` 升级为 `react-markdown + remark-gfm`，代码块添加复制按钮。

5. **（P2）在下一版 Spec 中明确 Spec 21 / Spec 25 边界**：在 Spec 25 v2 或独立的"首页 AskBar 样式修订 spec"中，显式声明首页 AskBar 与通用聊天 AskBar 的取舍决策，消除两个 spec 之间的设计决策矛盾，并将 AC 检查单纳入每个 coder 交付批次的验收流程。
