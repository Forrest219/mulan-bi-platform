# 后台管理菜单重构 - 技术设计方案

> 文档版本：v1.0
> 日期：2026-04-01
> 状态：草案
> 适用范围：PRD 菜单结构与现有代码的映射对齐

---

## 一、现状分析

### 1.1 现有顶部导航（Navbar）

```
Navbar（顶部导航）
├── 数据库监控     → /database-monitor
├── 规则配置       → /rule-config
├── Tableau        → /tableau/assets
├── 语义维护       → /semantic-maintenance/datasources
├── DDL 预览       → /ddl-validator
└── 后台管理       → /admin/users  （仅 Admin 可见）
```

### 1.2 现有 AdminLayout 侧边栏

```
AdminLayout（后台管理侧边栏）
├── 用户管理       → /admin/users
├── 用户组管理     → /admin/groups
├── 权限配置       → /admin/permissions
├── 访问日志       → /admin/activity
├── LLM 配置       → /admin/llm
├── Tableau 连接   → /tableau/connections       ⚠️ 实际是功能页，不是管理页
└── 语义维护       → /semantic-maintenance/datasources  ⚠️ 同上
```

### 1.3 核心问题

| 问题 | 说明 |
|------|------|
| **Navbar 不符合 PRD** | PRD 一级菜单是「首页/数据治理/BI语义/知识库/后台管理」，现有 Navbar 是散的 |
| **Tableau 连接放错位置** | `/tableau/connections` 在 AdminLayout 侧边栏，但按 PRD 属于「后台管理 → Tableau连接管理」 |
| **语义维护放错位置** | `/semantic-maintenance/*` 在 AdminLayout，但按 PRD 属于「BI语义 → 语义维护」 |
| **知识库无入口** | PRD 有知识库，现有代码完全无实现 |
| **数据仓库体检/质量监控无独立路由** | `/database-monitor` 混杂两者，需拆分 |
| **日志与任务不完整** | 只有访问日志（activity），无任务管理 |

---

## 二、PRD 目标菜单结构

```
首页
    └── 全局智能搜索入口

数据治理
    ├── 数据仓库体检       → /data-governance/health
    ├── 数据质量监控       → /data-governance/quality
    └── 规则配置           → /rule-config
          ├── 表名规则配置
          └── 字段规则配置

BI语义
    ├── 资产浏览           → /tableau/assets
    ├── 语义维护           → /semantic-maintenance/datasources
    └── 语义发布记录       → /semantic-maintenance/publish-logs

知识库
    ├── 指标字典           → /knowledge/metrics
    ├── 品控手册           → /knowledge/handbook
    └── 业务系统信息       → /knowledge/systems
    ※ V1 仅预留菜单，不开发

后台管理
    ├── 用户与权限管理     → /admin/users（合并用户/用户组/权限）
    ├── 数据源管理         → /admin/datasources（新建）
    ├── Tableau连接管理    → /admin/tableau/connections
    ├── 系统配置           → /admin/llm
    └── 日志与任务         → /admin/activity（已有）+ /admin/tasks（新建）
```

---

## 三、导航架构重构

### 3.1 新的导航体系

将现有 **Navbar（一级导航）** 和 **AdminLayout（后台管理侧边栏）** 合并为一个统一的侧边栏，按 PRD 五域展开。

**统一侧边栏结构**：

```
侧边栏（五域导航）
├── 首页
├── 数据治理
│     ├── 数据仓库体检
│     ├── 数据质量监控
│     └── 规则配置
├── BI语义
│     ├── 资产浏览
│     ├── 语义维护
│     └── 发布记录
├── 知识库（V1 仅占位）
│     ├── 指标字典
│     ├── 品控手册
│     └── 业务系统信息
└── 后台管理
      ├── 用户与权限
      ├── 数据源管理
      ├── Tableau连接管理
      ├── 系统配置
      └── 日志与任务
```

### 3.2 Layout 组件拆分

| Layout | 用途 | 路由前缀 |
|--------|------|---------|
| `MainLayout` | 首页 + 数据治理 + BI语义（统一侧边栏） | `/` |
| `AdminSidebarLayout` | 后台管理（专用侧边栏） | `/admin` |
| `BlankLayout` | 无侧边栏页面（如登录） | `/login` |

---

## 四、具体改动清单

### 4.1 路由重组

| 现有路由 | 改动 | 目标路由 |
|---------|------|---------|
| `/database-monitor` | 废弃，数据迁至 `/data-governance/*` | 拆分至 `/data-governance/health` + `/data-governance/quality` |
| `/rule-config` | 路径不变，作为数据治理子路由 | `/data-governance/rules` |
| `/ddl-validator` | 路径不变，属于数据治理 | `/ddl-validator` |
| `/tableau/assets` | 路径不变，属 BI语义 | `/tableau/assets` |
| `/semantic-maintenance/*` | 语义维护路径不变；新增 `/publish-logs` | `/semantic-maintenance/*` |
| `/admin/users` | 合并用户+用户组+权限到一个管理页 | 重构为 `/admin/users` |
| `/admin/groups` | 合并入 `/admin/users` | 废弃 |
| `/admin/permissions` | 合并入 `/admin/users` | 废弃 |
| `/admin/activity` | 路径不变，属后台管理 | `/admin/activity` |
| `/admin/llm` | 路径不变，属后台管理 | `/admin/llm` |
| `/tableau/connections` | 移入 Admin 侧边栏 | `/admin/tableau/connections` |

### 4.2 AdminLayout → AdminSidebarLayout

将现有的 `AdminLayout` 重构为 `AdminSidebarLayout`，作为后台管理专用布局，不再包裹 Tableau 和语义维护页面。

**改动**：
1. `AdminLayout.tsx` → 重命名为 `AdminSidebarLayout.tsx`
2. 移除 `Tableau 连接` 和 `语义维护` 两个菜单项（它们属于 BI语义域）
3. 后台管理菜单项精简为：

```tsx
const adminMenuItems = [
  { path: '/admin/users', label: '用户与权限', icon: 'ri-user-settings-line' },
  { path: '/admin/datasources', label: '数据源管理', icon: 'ri-database-2-line' },
  { path: '/admin/tableau/connections', label: 'Tableau 连接管理', icon: 'ri-bar-chart-box-line' },
  { path: '/admin/llm', label: '系统配置', icon: 'ri-robot-line' },
  { path: '/admin/activity', label: '日志与任务', icon: 'ri-history-line' },
];
```

### 4.3 新增 MainLayout（统一侧边栏）

新建 `frontend/src/components/MainLayout.tsx`：

```tsx
const mainMenuItems = [
  { section: '数据治理', items: [
    { path: '/data-governance/health', label: '数据仓库体检', icon: 'ri-heart-pulse-line' },
    { path: '/data-governance/quality', label: '数据质量监控', icon: 'ri-shield-check-line' },
    { path: '/rule-config', label: '规则配置', icon: 'ri-file-settings-line' },
  ]},
  { section: 'BI语义', items: [
    { path: '/tableau/assets', label: '资产浏览', icon: 'ri-bar-chart-box-line' },
    { path: '/semantic-maintenance/datasources', label: '语义维护', icon: 'ri-ai-generate' },
    { path: '/semantic-maintenance/publish-logs', label: '发布记录', icon: 'ri-file-history-line' },
  ]},
  { section: '知识库', items: [
    { path: '/knowledge/metrics', label: '指标字典', icon: 'ri-book-2-line' },
    { path: '/knowledge/handbook', label: '品控手册', icon: 'ri-book-open-line' },
    { path: '/knowledge/systems', label: '业务系统信息', icon: 'ri-computer-line' },
  ]},
];
```

> 注：知识库三项 V1 仅占位（路由指向"功能开发中"提示页），不开发。

### 4.4 路由配置更新

`frontend/src/router/config.tsx`：

```tsx
// 新增布局
import MainLayout from '../components/MainLayout';
import AdminSidebarLayout from '../components/AdminSidebarLayout';

// MainLayout 路由组
{
  path: '/',
  element: <MainLayout><HomePage /></MainLayout>,
  children: [
    { path: '/', element: <Home /> },
    { path: '/data-governance/health', element: <DataHealthPage /> },
    { path: '/data-governance/quality', element: <DataQualityPage /> },
    { path: '/rule-config', element: <RuleConfigPage /> },
    { path: '/ddl-validator', element: <DDLValidatorPage /> },
    { path: '/tableau/assets', element: <TableauAssetBrowserPage /> },
    { path: '/tableau/assets/:id', element: <TableauAssetDetailPage /> },
    { path: '/semantic-maintenance/datasources', element: <SemanticDatasourceListPage /> },
    { path: '/semantic-maintenance/datasources/:id', element: <SemanticDatasourceDetailPage /> },
    { path: '/semantic-maintenance/fields', element: <SemanticFieldListPage /> },
    { path: '/semantic-maintenance/publish-logs', element: <SemanticPublishLogsPage /> },
    // 知识库占位路由（V1）
    { path: '/knowledge/:sub', element: <KnowledgePlaceholderPage /> },
  ]
}

// AdminSidebarLayout 路由组
{
  path: '/admin',
  element: <AdminSidebarLayout><AdminHomePage /></AdminSidebarLayout>,
  children: [
    { path: '/admin/users', element: <UsersAdminPage /> },
    { path: '/admin/datasources', element: <DataSourcesAdminPage /> },
    { path: '/admin/tableau/connections', element: <TableauConnectionsPage /> },
    { path: '/admin/llm', element: <LLMAdminPage /> },
    { path: '/admin/activity', element: <ActivityAdminPage /> },
  ]
}
```

### 4.5 首页调整

- `HomePage` 保持不变（已经是首页）
- `MainLayout` 包裹时，首页不显示侧边栏菜单（仅 Logo + 搜索入口），与 PRD 「首页轻入口」一致

```tsx
// MainLayout.tsx
const showSidebar = location.pathname !== '/';  // 首页不显示侧边栏
```

---

## 五、实施建议

### V1 重构优先级

| 优先级 | 改动 | 工作量 |
|--------|------|--------|
| P0 | 新建 `MainLayout`，将数据治理+BI语义域迁移进来 | 高 |
| P0 | 将 `AdminLayout` 重构为 `AdminSidebarLayout`，移出 Tableau/语义维护菜单 | 高 |
| P0 | 将 `/tableau/connections` 路由移至 `/admin/tableau/connections` | 中 |
| P1 | 拆分 `/database-monitor` → `/data-governance/health` + `/data-governance/quality` | 中 |
| P1 | `/admin/users` 合并用户+用户组+权限为统一管理页 | 中 |
| P2 | 新增 `/admin/datasources` 数据源管理页（数据治理用的数据库连接） | 低 |
| P2 | 新增知识库占位路由 | 低 |
| P2 | 新增 `/admin/tasks` 任务管理页 | 低 |

### V1 保留事项

- `/admin/groups` 和 `/admin/permissions` 路由可保留为 `*` 兼容跳转至 `/admin/users`，不做强跳转
- `/database-monitor` 路由保留做兼容，301 跳转到 `/data-governance/health`

---

## 六、文件改动清单

```
frontend/src/
├── components/
│     ├── MainLayout.tsx          [新建]
│     ├── AdminLayout.tsx         [重构 → AdminSidebarLayout]
│     └── Navbar.tsx              [废弃]
├── router/
│     └── config.tsx              [重构路由配置]
└── pages/
      ├── home/page.tsx           [保持]
      ├── data-governance/         [新建目录]
      │     ├── health/page.tsx    [由 database-monitor 改写]
      │     └── quality/page.tsx   [由 database-monitor 改写]
      ├── admin/
      │     ├── users/page.tsx     [合并用户+用户组+权限]
      │     └── datasources/page.tsx [新建]
      └── knowledge/               [V1 占位页]
            └── placeholder/page.tsx
```
