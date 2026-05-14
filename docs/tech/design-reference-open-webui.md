# 设计参考：Open WebUI 交互风格指南

> **用途**：本文档记录 Mulan Platform 在 UI/UX 迭代中参考 Open WebUI 的设计决策。
> 重点借鉴范围：**首页对话区**与**后台管理面板**。
>
> 原始项目：https://github.com/open-webui/open-webui（MIT License）

---

## 一、为什么参考 Open WebUI

Open WebUI 是目前开源社区中对话式 AI 界面的最佳实践之一。其设计特点：

- **信息密度克制**：侧边栏、内容区、输入区三段式分割清晰，不堆叠功能
- **折叠态设计成熟**：侧边栏两态（图标 icon-only / 展开全宽）过渡自然，有明确的交互反馈
- **用户账户区完整**：底部固定用户头像 + 状态指示，登录身份一目了然
- **输入框对齐严格**：聊天输入框随侧边栏宽度动态偏移，始终与内容区中轴对齐
- **管理后台结构化**：users / settings / analytics / functions 四段独立路由，层级清晰

---

## 二、侧边栏设计模式（参考 `Sidebar.svelte`）

### 2.1 两态结构对比

| 状态 | 宽度 | 展示内容 |
|------|------|---------|
| 折叠（icon-only） | ~56px | Logo、新建对话图标、搜索图标、底部用户头像 |
| 展开 | 220–480px（可拖拽调整） | Logo + 文字、新建 + 搜索（带标签）、对话列表（分组）、底部用户信息 |

**Mulan 现状对比：**
- 折叠态：`ConversationBar` 宽度归零隐藏，没有 icon-only 中间态 → 可参考增加
- 展开态宽度：固定 260px，不可拖拽 → 暂可保持，后期可引入

### 2.2 顶部操作区

Open WebUI 顶部区域只放两个按钮：**新建对话** + **搜索**，无多余折叠图标。

```
[ 新建对话 ]  [ 搜索 ]
─────────────────────
  对话列表...
```

> **Mulan 对应修复**：移除 `ConversationBar` 顶部的折叠按钮（Bug 1），与此设计对齐。

### 2.3 底部用户区

Open WebUI 底部固定区域包含：
1. **用户头像**（从 API 拉取，带绿色在线状态圆点）
2. **用户名** + **角色/邮箱**（截断显示）
3. 点击头像展开菜单：设置 / 退出登录 / 主题切换

CSS 关键模式：
```css
/* 底部固定，不随列表滚动 */
flex flex-col justify-between h-full

/* 用户头像区 */
px-[0.5625rem] py-2
size-6  /* 头像图片尺寸 */
```

> **Mulan 对应修复**：对齐 Bug 2，底部用户区头像尺寸、字重、设置入口均参考此规范。

### 2.4 颜色系统

| 层级 | Light | Dark |
|------|-------|------|
| 侧边栏背景 | `bg-gray-50` | `bg-gray-950` |
| hover 状态 | `hover:bg-gray-100` | `hover:bg-gray-850` |
| 激活项 | `bg-gray-200` | `bg-gray-700` |
| 主文字 | `text-gray-900` | `text-gray-200` |
| 次要文字 | `text-gray-500` | `text-gray-400` |

Mulan 当前使用 `slate-` 系色系，与 Open WebUI 的 `gray-` 系视觉接近，**无需强制替换**，保持项目自身色系一致性即可。

---

## 三、聊天输入框对齐方案（参考 `MessageInput.svelte`）

### 3.1 Open WebUI 的做法

输入框容器 `chat-input-container` 是**相对内容区定位**的，而非 `fixed` 到视口。父容器负责提供正确的左边距偏移（等于侧边栏宽度），输入框内部不感知侧边栏的存在。

核心思路：
```
Layout 层：管理 sidebar-width → 注入 CSS 变量或传 prop
Content 层：padding-left = sidebar-width
InputBar 层：width: 100%，不关心 sidebar
```

### 3.2 Mulan 的适配方案

**当前问题：** `AskBar` 使用 `fixed bottom-0 left-0 right-0`，以视口全宽居中，而内容区被 ConversationBar（260px）右移，导致中轴线错位。

**推荐修复方式（CSS 变量）：**

```tsx
// HomeLayout.tsx — 根容器注入变量
<div
  className="flex min-h-screen ..."
  style={{ '--conv-bar-w': collapsed ? '0px' : '260px' } as React.CSSProperties}
>

// page.tsx — AskBar 包裹层
<div
  className="fixed bottom-0 right-0 border-t ..."
  style={{ left: 'var(--conv-bar-w)', transition: 'left 200ms' }}
>
```

优势：动画与 ConversationBar 的 `transition-all duration-200` 保持同步。

---

## 四、后台管理面板结构（参考 `/admin` 路由树）

Open WebUI 管理后台的路由分区：

| 路由段 | 功能 |
|--------|------|
| `/admin` | 概览仪表板 |
| `/admin/users` | 用户列表、角色编辑、封禁管理 |
| `/admin/settings` | 全局配置（模型、认证、外观） |
| `/admin/functions` | 自定义 Function/Pipeline 管理 |
| `/admin/evaluations` | 模型评估与对比 |
| `/admin/analytics` | 使用量统计、活跃用户趋势 |

**Mulan 现状对比：**

| Mulan 路由 | 对应 Open WebUI |
|-----------|----------------|
| `/system/users` | `/admin/users` ✅ |
| `/system/llm` | `/admin/settings`（模型配置）✅ |
| `/system/permissions` | `/admin/settings`（权限）✅ |
| — | `/admin/analytics` ⬜ 待建（bi_ 表已有数据基础） |
| — | `/admin/evaluations` ⬜ 未规划 |

### 4.1 管理后台交互规范（可借鉴）

1. **顶部 Tab 导航**：admin 子页面通过水平 Tab 切换，不在侧边栏展开二级菜单
2. **列表页操作**：用户列表支持搜索过滤、角色批量编辑、状态 badge（active / banned）
3. **设置页分组**：每组设置有独立标题 + 描述文案，避免裸露的表单控件
4. **危险操作区**：`border-red-200 bg-red-50` 区块隔离危险操作（重置、删除），与普通设置物理分离

---

## 五、交互细节清单（可直接移植）

以下为 Open WebUI 中值得在 Mulan 直接参考实施的细节，按优先级排列：

### P0（与当前 Bug 修复直接相关）

- [ ] 折叠/展开按钮仅在 ConversationBar **外部**（如 Topbar）提供一处入口，内部不重复
- [ ] 底部用户区：头像 + 姓名 + 角色，视觉权重对等（不小于 `w-8 h-8`，`text-sm`）
- [ ] AskBar 的 `fixed` 定位左边界跟随侧边栏宽度动态偏移

### P1（下一轮迭代）

- [ ] 侧边栏宽度支持鼠标拖拽调整（220–480px），保存到 localStorage
- [ ] 对话列表支持 Shift + 点击多选，批量删除
- [ ] 移动端侧边栏改为从左侧滑入的 overlay（当前 HomeLayout 已部分支持）

### P2（后期规划）

- [ ] 用户头像支持上传（`/api/users/{id}/profile/image`）
- [ ] 底部用户菜单增加：主题切换（浅色/深色）入口
- [ ] 管理后台增加 `/admin/analytics` 使用量统计页

---

## 六、不建议直接照搬的部分

| Open WebUI 特性 | 原因 |
|----------------|------|
| Svelte 组件结构 | Mulan 使用 React，语法差异大，参考交互逻辑而非代码 |
| 多模型并行对话 | 超出 Mulan 当前 P0 范围 |
| 频道/群聊系统 | Mulan 是单用户 BI 问答，场景不匹配 |
| RAG 文件库 UI | Mulan 的知识库入口已有独立页面，无需合并 |
| LDAP/SCIM 认证 | Mulan 使用 Session + Cookie，架构差异大 |

---

*文档创建：2026-04-17 | 参考版本：open-webui main branch（~v0.6.x）*
