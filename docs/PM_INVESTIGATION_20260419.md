# PM 调查报告：首页风格复盘

日期: 2026-04-19
作者: PM Agent (Mulan BI Platform)
范围: http://localhost:3001 首页，仅分析、不改代码

---

## 一、收起按钮来源调查

### 1.1 按钮的准确位置

**文件**: `frontend/src/pages/home/components/ConversationBar.tsx`
**行号**: 122 - 130
**图标类名**: `ri-sidebar-fold-line`（Remix Icon，侧栏折叠样式；用户截图看到的"grid-like icon"实际是这个图标在当前样式/尺寸下的视觉观感）
**完整 className**: `flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors`
**aria-label**: `折叠侧边栏`
**回调**: `onToggleCollapse` → `HomeLayout.tsx` 的 `handleToggleCollapse`，最终写入 `localStorage.mulan-home-sidebar-collapsed`。

### 1.2 历史轨迹（git log）

`ConversationBar.tsx` 仅出现在最近 3 个提交中：

| 提交 | 状态 |
| --- | --- |
| `6d098a6` 首页问数重构 + 对话历史（P0–P2） | 首次引入该文件，已包含折叠按钮 |
| `8e2f910` Spec24 B/C UI rollout and backend-admin cleanup | 保留折叠按钮（图标为 `ri-layout-left-line`） |
| `a943844` META 查询实现 + 多项修复（当前 HEAD） | **删除**了折叠按钮（见下方 diff） |
| 工作区未提交改动（本次会话）| **又把折叠按钮加回来**，并将图标改成 `ri-sidebar-fold-line`、样式改为 `w-7 h-7 rounded-lg` |

`git diff HEAD~3..HEAD` 中相关片段明确显示 HEAD 相对于三提交前删除了折叠按钮：

```diff
-      {/* 顶部：折叠 + 新建 */}
+      {/* 顶部：新建 */}
       <div className="flex items-center gap-2 px-3 pt-4 pb-2">
-        <button
-          onClick={onToggleCollapse}
-          className="w-7 h-7 ... text-slate-500"
-          aria-label="折叠对话历史"
-        >
-          <i className="ri-layout-left-line text-base" />
-        </button>
         <button
           onClick={handleNew}
-          className="flex-1 flex items-center gap-1.5 px-3 py-1.5 ..."
+          className="w-full flex items-center gap-1.5 px-3 py-1.5 ..."
```

`git status` 显示 `frontend/src/pages/home/components/ConversationBar.tsx` 为未暂存修改（modified，未提交）。这证明用户"上一个版本是删除了的"说法准确：HEAD 已经是无按钮版本，按钮是**本次会话的 coder agent 重新加回来的**，属于**回归 regression**。

### 1.3 处理建议

- **操作**: 将 `ConversationBar.tsx` 第 122-130 行的 `<button>` 整块删除，同时把紧邻的"新对话"按钮 className 由 `flex-1` 改回 `w-full`（与 HEAD 一致）。
- **附带清理**:
  - `HomeLayout.tsx` 第 67 行 `handleToggleCollapse` 不再有调用者，可同步删除；Props `collapsed/onToggleCollapse` 也可以一起删（当前 `ConversationBar` 内部已将 `collapsed` 命名为 `_collapsed`，表明其实本就没在视觉上使用）。
  - `HomeLayout.tsx` 第 53-60 行 `Escape` 键的 `setCollapsed(true)` 分支需要同步处理，避免悬空逻辑。
  - `localStorage` 键 `mulan-home-sidebar-collapsed` 可保留迁移兼容逻辑，但不再读写。
- **验证**: 截图红框区域消失；新对话按钮占满顶部宽度。
- **根因提示给 coder**: 本次会话应把 HEAD 作为基线，避免基于更早的分支状态直接开改；建议在交付前 `git diff HEAD` 自查，确认没有把"已移除的 UI 元素"再次引入。

---

## 二、首页风格差距分析

### 2.1 整体结构对照表

| 维度 | Open-WebUI 期望（参考 `docs/design-reference-open-webui.md` 典型风格） | Mulan 当前实现 | 结论 |
| --- | --- | --- | --- |
| 背景 | 纯白 `bg-white` 或极浅灰 `bg-gray-50`，无装饰 | `HomeLayout` 用 `bg-slate-50`，基本符合 | 符合 |
| 顶部工具栏 | **无**（开箱即用的问答界面，顶部空白） | 顶部有 `ScopePicker`（连接/项目选择器），占 `px-6 pt-4 pb-2` 高度 | **差距大** |
| 主内容垂直居中 | Logo + 产品名 + 欢迎语**垂直居中**于主内容区（`flex items-center justify-center min-h-screen`） | `WelcomeHero` 使用 `pt-16 pb-8`，顶部对齐，不是居中 | **差距大** |
| Logo / 欢迎语 | 居中、极简，通常只有 logo + 一行副标题 | Logo + "Mulan Platform" + "数据建模与治理平台 — 用自然语言探索你的数据"，副标题较长 | 部分符合 |
| 示例问题卡片 | 通常 4 张（2x2 或 1x4），无边框或极轻灰边框，文案简短 | 5 条数据（渲染为 2 列，最后一条孤行），带 `border-slate-200 rounded-xl` 边框 | 部分符合 |
| 输入框位置 | **固定在底部**，页面居中时也在视觉中线附近；风格 `rounded-2xl / rounded-3xl`，白色背景 + 细阴影 | AskBar 已 `fixed bottom-0` + `bg-white/95 backdrop-blur` | 符合 |
| 输入框 placeholder | 简短一句，如 "Send a message…" | 需实查 `AskBar.tsx`，但整体位置正确 | 基本符合 |
| 侧边栏 | 对话历史列表，默认展开或 hover 展开；**无显式收起按钮**（或仅在折叠态显示展开按钮） | 左侧 `ConversationBar` 260px 固定展开，顶部塞了一个折叠按钮（见 Part 1） | **差距大** |
| Idle 态额外信息 | **空**，只有 Logo + 欢迎语 + 建议卡片 + 输入框 | 除了建议卡片，还叠了 `OpsSnapshotPanel`（健康分、资产分布、待关注资产列表） | **差距大** |
| 错误态展示 | 内联到消息流中，风格统一；空状态下不展示错误卡片 | 截图显示"参数缺失：请指定数据源后重试"错误卡片出现在 idle 态首页中间 | **差距大** |
| 装饰元素 | 基本没有装饰边框、阴影，留白为主 | `OpsSnapshotPanel` 与 `ScopePicker` 都带 `rounded-xl border border-slate-200`，视觉噪音明显 | **差距大** |

### 2.2 逐组件的关键问题

**`ScopePicker.tsx`（差距的主要来源之一）**
- 顶部全宽条带，带边框和内边距，等于**把"选择数据源"前置到了入口**。
- Open-WebUI 的对等物应该是"模型选择器"，它通常放在 AskBar 内的左下角或单独的 header 图标，**不会作为一级可见控件占用首页顶部空间**。
- 另外，在没有连接时显示"暂无连接 + 筛选项目…"的空选择器，既没有引导价值，又会让 AskBar 回调触发"参数缺失"错误，直接污染首屏。

**`WelcomeHero.tsx`**
- `pt-16 pb-8` 导致欢迎区靠上而非居中；对 idle 态来说不够"空"。
- 副标题偏长（"数据建模与治理平台 — 用自然语言探索你的数据"），Open-WebUI 风格应更简短，比如直接 "How can I help you today?" 这种一行提问引导。

**`SuggestionGrid.tsx`**
- 5 条数据填 2 列，最后一条独占一行视觉不对齐；应回到 4 条。
- 带描边卡片相对 Open-WebUI 风格偏"强"，可改为 hover 才显示浅灰背景的无边框按钮。
- 文案均为 BI 业务场景（"订单金额""退款率"），但当**没有连接时**点击必然报"参数缺失"，产品逻辑自相矛盾。

**`OpsSnapshotPanel.tsx`**
- 这是一个**运维/治理看板组件**，在 idle 首页展示，直接破坏 Open-WebUI 那种"空白 + 对话"的氛围。
- 定位更像"控制台/仪表盘"子页面，不应放在 AI 问答入口首屏。

**`HomeLayout.tsx`**
- 左侧固定 260px、主体 `max-w-3xl mx-auto`，整体宽度结构 OK。
- 折叠逻辑（Escape 键 + 按钮 + localStorage）是功能过度，Open-WebUI 其实没这层能力。

**`page.tsx`**
- idle 态渲染顺序: `ScopePicker` → `WelcomeHero` → `SuggestionGrid` → `OpsSnapshotPanel`。这个纵向叠加让首屏信息密度远超 Open-WebUI。
- 错误态 `SearchResult` 直接塞进 WelcomeHero 下方的主列，导致截图看到的"参数缺失"错误卡片出现在"正常首页文案"中间。

---

## 三、根因总结

1. **信息密度过高**：首页承担了"AI 问数 + 作用域选择 + 运维看板 + 错误反馈"四种职责，违背 Open-WebUI 那种"单一入口 + 极简首屏"的核心美学。
2. **首屏控件选错了**：`ScopePicker` 作为顶部一级控件、`OpsSnapshotPanel` 作为 idle 填充，都是 Open-WebUI 体系不存在的"BI/运维专属"组件——样式无论怎么调，只要这两个出现在首屏，就永远不可能"像 Open-WebUI"。
3. **本次会话出现回归**：coder 在未经 PRD 授权的情况下，把已经在 `a943844` 中删除的"侧栏折叠按钮"重新加入，形成回归；需要建立"HEAD 基线自查"的协作纪律。

---

## 四、优先级建议

> 目标不是"把 Open-WebUI 照搬"，而是去掉首屏与它最明显的三处差异。保持克制，MVP 不要扩张。

| 优先级 | 改动 | 预期效果 |
| --- | --- | --- |
| **P0** | 删除 `ConversationBar.tsx` 第 122-130 行的折叠按钮，恢复"新对话"按钮 `w-full`，清理 `HomeLayout` 里相关的折叠 state/localStorage/Escape 逻辑 | 修掉用户明确反馈的回归，侧栏顶部只剩"新对话" |
| **P0** | 在首页 `page.tsx` 的 idle 态**隐藏** `ScopePicker`；如果业务必须要"选择连接"，把它折进 `AskBar` 的左下角小按钮（或单连接时自动选中、无需 UI） | 顶部空出来，首屏接近 Open-WebUI 的"干净留白" |
| **P0** | 在 idle 态**移除** `OpsSnapshotPanel`。如确有运维看板需求，迁移到独立路由（例如 `/ops` 或通过对话历史栏底部的"运维快照"入口进入） | 首屏结构降为 Logo + 欢迎语 + 4 张建议卡 + 底部 AskBar |
| **P1** | `WelcomeHero` 改为主内容区垂直居中（`min-h-[calc(100vh-120px)] flex flex-col items-center justify-center`），副标题改为一行短引导（如"用自然语言问你的数据"） | 视觉重心居中，符合 Open-WebUI 首屏感 |
| **P1** | `SuggestionGrid` 裁到 4 条（去掉重复场景），卡片改为无边框 / hover 才显示浅灰背景；当没有连接时**隐藏或禁用**建议卡并给出"先连接数据源"的轻引导，而不是点了再抛错 | 删除"点了报错"的矛盾体验；卡片与 Open-WebUI 风格对齐 |
| **P2** | `AskBar` 校验：无连接时禁用 submit，placeholder 提示"请先在设置中连接数据源"，避免错误卡出现在首屏；错误态卡片仅在 `HOME_ERROR` 下显示，并清理 idle 跳转回错误态时的残留 | 首屏不再出现"参数缺失"红框，状态机清晰 |

---

## 附录：参考文件路径（绝对路径）

- `/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/components/ConversationBar.tsx`
- `/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/page.tsx`
- `/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/components/WelcomeHero.tsx`
- `/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/components/SuggestionGrid.tsx`
- `/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/components/ScopePicker.tsx`
- `/Users/forrest/Projects/mulan-bi-platform/frontend/src/pages/home/components/OpsSnapshotPanel.tsx`
- `/Users/forrest/Projects/mulan-bi-platform/frontend/src/components/layout/HomeLayout.tsx`
- `/Users/forrest/Projects/mulan-bi-platform/docs/design-reference-open-webui.md`
