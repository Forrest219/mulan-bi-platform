# SPEC：首页 UI Bug 修复（3 处）

- **状态**：待实施
- **创建**：2026-04-17
- **执行者**：coder
- **设计参考**：`docs/design-reference-open-webui.md`

---

## 改动文件清单

| 文件 | Bug | 改动性质 |
|------|-----|----------|
| `frontend/src/pages/home/components/ConversationBar.tsx` | Bug 1、Bug 2 | 删除节点 + className 替换 + 条件渲染 |
| `frontend/src/components/layout/HomeLayout.tsx` | Bug 3 | 根容器加 style 属性 |
| `frontend/src/pages/home/page.tsx` | Bug 3 | fixed 容器 className + style |

---

## Bug 1：移除顶部冗余折叠按钮

**文件：** `ConversationBar.tsx` L122–139

### 改动 1-A：删除折叠按钮节点

删除以下整个 `<button>` 节点（L123–129）：

```tsx
// 删除这段
<button
  onClick={onToggleCollapse}
  className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-slate-200 transition-colors text-slate-500"
  aria-label="折叠对话历史"
>
  <i className="ri-layout-left-line text-base" />
</button>
```

### 改动 1-B：新对话按钮 className

```diff
- className="flex-1 flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-600 border border-slate-200 rounded-lg hover:bg-white hover:shadow-sm transition-all"
+ className="w-full flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-600 border border-slate-200 rounded-lg hover:bg-white hover:shadow-sm transition-all"
```

### 改动 1-C：保留 prop 接口（不改 interface）

`ConversationBarProps` 中的 `onToggleCollapse` **保留不删**，HomeLayout 仍传入该 prop（折叠逻辑由外部控制，组件内部不再渲染该按钮）。

---

## Bug 2：底部用户区视觉强化 + 设置入口路由修正

**文件：** `ConversationBar.tsx` L199–225

### 改动 2-A：用户信息行 className 升级

```diff
- <div className="flex items-center gap-2 px-2 py-1.5">
+ <div className="flex items-center gap-2.5 px-2 py-2">

- <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
+ <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center shrink-0">

- <span className="text-[11px] text-blue-600 font-semibold">
+ <span className="text-xs text-blue-600 font-bold">

- <div className="text-[13px] text-slate-700 font-medium truncate">
+ <div className="text-sm text-slate-800 font-semibold truncate">

- <div className="text-[11px] text-slate-400">{user?.role ?? 'user'}</div>
+ <div className="text-xs text-slate-400">{user?.role ?? 'user'}</div>
```

### 改动 2-B：设置入口改为 admin 限定条件渲染

将现有 `<a href="/system/users">` 用条件渲染包裹：

```tsx
// 改动前
<a
  href="/system/users"
  className="flex items-center gap-2 px-2 py-1.5 text-sm text-slate-500
             rounded-lg hover:bg-slate-100 hover:text-slate-700 transition-colors"
>
  <i className="ri-settings-3-line text-base" />
  设置
</a>

// 改动后
{user?.role === 'admin' && (
  <a
    href="/system/users"
    className="flex items-center gap-2 px-2 py-1.5 text-sm text-slate-500
               rounded-lg hover:bg-slate-100 hover:text-slate-700 transition-colors"
  >
    <i className="ri-settings-3-line text-base" />
    设置
  </a>
)}
```

**选择方案 C（保持现有路由，限定 admin 可见）**，理由：最小改动，不引入新路由，普通用户不再看到无权访问的入口。

---

## Bug 3：AskBar 对齐修正（两文件同步）

> ⚠️ 两处改动必须同时提交，单独改其中一处会加剧错位。

### 改动 3-A：HomeLayout.tsx 根容器注入 CSS 变量

**文件：** `frontend/src/components/layout/HomeLayout.tsx` L70

```diff
- <div className="flex min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50">
+ <div
+   className="flex min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50"
+   style={{ '--conv-bar-w': collapsed ? '0px' : '260px' } as React.CSSProperties}
+ >
```

### 改动 3-B：page.tsx AskBar 容器定位修正

**文件：** `frontend/src/pages/home/page.tsx` L195

```diff
- <div className="fixed bottom-0 left-0 right-0 border-t border-slate-200 bg-white/95 backdrop-blur z-20">
+ <div
+   className="fixed bottom-0 right-0 border-t border-slate-200 bg-white/95 backdrop-blur z-20"
+   style={{ left: 'var(--conv-bar-w)', transition: 'left 200ms' }}
+ >
```

---

## 验收标准（coder 自检清单）

### Bug 1
- [ ] ConversationBar 顶部不再渲染 `ri-layout-left-line` 图标
- [ ] 新对话按钮宽度撑满侧边栏，无多余留白
- [ ] `ConversationBarProps` 接口无 TypeScript 报错

### Bug 2
- [ ] `admin` 角色登录：底部显示"设置"入口，点击跳转 `/system/users` 正常
- [ ] `analyst` / `user` / `data_admin` 角色登录：底部不显示"设置"入口
- [ ] 头像尺寸视觉上明显大于改动前（32px vs 24px）
- [ ] 无 TypeScript 报错

### Bug 3
- [ ] 侧边栏展开状态：AskBar `left` 值为 `260px`，与内容区左边对齐
- [ ] 折叠侧边栏：AskBar 向左平滑移动（200ms），最终 `left` = `0px`
- [ ] 展开侧边栏：AskBar 向右平滑移动（200ms），最终 `left` = `260px`
- [ ] DevTools 确认根容器 style 存在 `--conv-bar-w` 变量
- [ ] TypeScript 编译无报错（`as React.CSSProperties` 已加）

---

## 约束（禁止触碰）

- Logo、WelcomeHero、SuggestionGrid、推荐卡片样式 — **不改**
- 侧边栏背景色 `bg-slate-50` — **不改**
- `ConversationBar` 其他任何逻辑（对话列表、搜索、重命名、删除）— **不改**
- AppShellLayout / AppSidebar（其他页面的侧边栏）— **不涉及**
