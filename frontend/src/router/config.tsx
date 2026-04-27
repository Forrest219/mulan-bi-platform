/**
 * 路由配置（Spec 18 §4）
 *
 * 核心变更：
 * - 统一使用 AppShellLayout（替换 MainLayout + AdminSidebarLayout）
 * - React.lazy + Suspense 按 5 域代码分割
 * - 旧路由 → 新路由 301 重定向（兼容期后移除）
 *
 * ⚠️ 强制约束：src/api/ 目录下的后端 API 请求路径（如 /api/admin/datasources）
 * 绝对禁止修改！本次重构仅限于前端视图路由（React Router 路径）。
 */
import { lazy } from 'react';
import { type RouteObject, Navigate } from 'react-router-dom';
import NotFound from '../pages/NotFound';
import Home from '../pages/home/page';
import LoginPage from '../pages/login/page';
import RegisterPage from '../pages/register/page';
import ForbiddenPage from '../pages/ForbiddenPage';
import ProtectedRoute from '../components/auth/ProtectedRoute';
import AppShellLayout from '../components/layout/AppShellLayout';
import HomeLayout from '../components/layout/HomeLayout';
import { ConversationProvider } from '../store/conversationStore';

// ──────────────────────────────────────────────────────────────
// 代码分割：每个域独立 chunk（Spec 18 §4.3）
// ──────────────────────────────────────────────────────────────
const ChatPage            = lazy(() => import('../pages/chat/page'));
const LLMConfigsPage      = lazy(() => import('../pages/admin/llm-configs/page'));
const McpConfigsPage      = lazy(() => import('../pages/admin/mcp-configs/page'));
const McpDebuggerPage     = lazy(() => import('../pages/system/mcp-debugger/page'));
const DDLValidatorPage    = lazy(() => import('../pages/ddl-validator/page'));
const RuleConfigPage      = lazy(() => import('../pages/rule-config/page'));
const DataHealthPage      = lazy(() => import('../pages/data-governance/health/page'));
const HealthCenterPage    = lazy(() => import('../pages/data-governance/health-center/page'));
const TableauAssetBrowserPage = lazy(() => import('../pages/tableau/assets/page'));
const TableauAssetDetailPage  = lazy(() => import('../pages/tableau/asset-detail/page'));
const ConnectionCenterPage = lazy(() => import('../pages/assets/connection-center/page'));
const SyncLogsPage        = lazy(() => import('../pages/tableau/sync-logs/page'));
const DatasourcesPage     = lazy(() => import('../pages/assets/datasources/page'));
const TableauConnectionsPage = lazy(() => import('../pages/tableau/connections/page'));
const SemanticDatasourceListPage  = lazy(() => import('../pages/semantic-maintenance/datasource-list/page'));
const SemanticDatasourceDetailPage = lazy(() => import('../pages/semantic-maintenance/datasource-detail/page'));
const SemanticFieldListPage = lazy(() => import('../pages/semantic-maintenance/field-list/page'));
const SemanticPublishLogsPage = lazy(() => import('../pages/semantic-maintenance/publish-logs/page'));
const MetricsPage = lazy(() => import('../pages/data-governance/metrics/page'));
const MetricDetailPage = lazy(() => import('../pages/data-governance/metrics/detail'));
const KnowledgePage        = lazy(() => import('../pages/knowledge/page'));
const UsersAdminPage       = lazy(() => import('../pages/admin/user-management/page'));
const GroupsAdminPage      = lazy(() => import('../pages/admin/groups/page'));
const PermissionsAdminPage = lazy(() => import('../pages/admin/permissions/page'));
const AdminTasksPage        = lazy(() => import('../pages/admin/tasks/page'));
const ActivityAdminPage     = lazy(() => import('../pages/admin/activity/page'));
const QueryAlertsPage       = lazy(() => import('../pages/admin/query-alerts/page'));
const PlatformSettingsPage  = lazy(() => import('../pages/admin/platform-settings/page'));
const ForgotPasswordPage    = lazy(() => import('../pages/forgot-password/page'));
const EmptyStatePage        = lazy(() => import('../pages/empty/EmptyStatePage'));
const AgentMonitorPage      = lazy(() => import('../pages/admin/agent-monitor/page'));
const QueryPage             = lazy(() => import('../pages/query/page'));
const OpsWorkbenchPage      = lazy(() => import('../pages/ops/workbench/page'));
const AccountSecurityPage   = lazy(() => import('../pages/account/security/page'));

// ──────────────────────────────────────────────────────────────
// 路由定义
// ──────────────────────────────────────────────────────────────
const routes: RouteObject[] = [

  // =====================
  // 公开路由（HomeLayout + ConversationProvider）
  // =====================
  {
    element: (
      <ConversationProvider>
        <HomeLayout />
      </ConversationProvider>
    ),
    children: [
      { path: '/', element: <Home /> },
      { path: '/chat/:id', element: <ChatPage /> },
    ],
  },
  { path: '/login',          element: <LoginPage /> },
  { path: '/register',       element: <RegisterPage /> },
  { path: '/forgot-password', element: <ForgotPasswordPage /> },

  // =====================
  // 问数模块（独立布局，与运维路由完全隔离）
  // =====================
  {
    path: '/query',
    element: (
      <ProtectedRoute>
        <QueryPage />
      </ProtectedRoute>
    ),
  },

  // =====================
  // 运维工作台（独立布局，Split-Pane，Spec 20）
  // =====================
  {
    path: '/ops/workbench',
    element: (
      <ProtectedRoute>
        <OpsWorkbenchPage />
      </ProtectedRoute>
    ),
  },

  // =====================
  // 统一侧边栏布局（5 域，Spec 18 §4.2）
  // =====================
  {
    element: <AppShellLayout />,
    children: [

      // ── 域 1：数据开发 /dev ──
      {
        path: '/dev',
        children: [
          {
            path: 'ddl-validator',
            element: (
              <ProtectedRoute requiredPermission="ddl_check">
                <DDLValidatorPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'ddl-generator',
            // disabled: true，路由保留但菜单不可点击（Spec 18 §5.2）
            element: (
              <ProtectedRoute requiredPermission="ddl_generator">
                <DDLValidatorPage /> {/* 临时复用 DDL 检查页占位，待功能开发后替换 */}
              </ProtectedRoute>
            ),
          },
          {
            path: 'rule-config',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <RuleConfigPage />
              </ProtectedRoute>
            ),
          },
        ],
      },

      // ── 域 2：数据治理 /governance ──
      {
        path: '/governance',
        children: [
          {
            path: 'health-center',
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <HealthCenterPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'health',
            element: <Navigate to="/governance/health-center?tab=warehouse" replace />,
          },
          {
            path: 'quality',
            element: <Navigate to="/governance/health-center?tab=quality" replace />,
          },
          {
            path: 'semantic/datasources',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SemanticDatasourceListPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'semantic/datasources/:id',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SemanticDatasourceDetailPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'semantic/fields',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SemanticFieldListPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'semantic/publish-logs',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SemanticPublishLogsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'metrics',
            element: (
              <ProtectedRoute>
                <MetricsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'metrics/:id',
            element: (
              <ProtectedRoute>
                <MetricDetailPage />
              </ProtectedRoute>
            ),
          },
        ],
      },

      // ── 域 3：数据资产 /assets ──
      {
        path: '/assets',
        children: [
          {
            path: 'tableau',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <TableauAssetBrowserPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'tableau/:id',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <TableauAssetDetailPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'tableau-health',
            element: <Navigate to="/governance/health-center?tab=tableau" replace />,
          },
          {
            path: 'connections',
            element: (
              <ProtectedRoute>
                <ConnectionCenterPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'connection-center',
            element: <Navigate to="/assets/connections" replace />,
          },
          {
            path: 'datasources',
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DatasourcesPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'tableau-connections',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <TableauConnectionsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'tableau-connections/:connId/sync-logs',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SyncLogsPage />
              </ProtectedRoute>
            ),
          },
        ],
      },

      // ── 域 4：智能分析 /analytics ──
      {
        path: '/analytics',
        children: [
          {
            path: 'nl-query',
            // disabled: true，路由保留但菜单不可点击（Spec 18 §5.2）
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DataHealthPage /> {/* 临时复用占位，待功能开发后替换 */}
              </ProtectedRoute>
            ),
          },
          {
            path: 'knowledge',
            element: (
              <ProtectedRoute>
                <KnowledgePage />
              </ProtectedRoute>
            ),
          },
        ],
      },

      // ── 账户设置 /account ──
      {
        path: '/account',
        children: [
          {
            path: 'security',
            element: (
              <ProtectedRoute>
                <AccountSecurityPage />
              </ProtectedRoute>
            ),
          },
        ],
      },

      // ── 空状态占位页 /empty/:feature ──
      {
        path: 'empty/:feature',
        element: <EmptyStatePage />,
      },

      // ── 域 5：系统管理 /system ──
      {
        path: '/system',
        children: [
          { index: true, element: <Navigate to="/system/users" replace /> },
          {
            path: 'users',
            element: (
              <ProtectedRoute adminOnly>
                <UsersAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'groups',
            element: (
              <ProtectedRoute adminOnly>
                <GroupsAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'permissions',
            element: (
              <ProtectedRoute adminOnly>
                <PermissionsAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'llm',
            element: <Navigate to="/system/llm-configs" replace />,
          },
          {
            path: 'tasks',
            element: (
              <ProtectedRoute adminOnly>
                <AdminTasksPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'activity',
            element: (
              <ProtectedRoute adminOnly>
                <ActivityAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'llm-configs',
            element: (
              <ProtectedRoute adminOnly>
                <LLMConfigsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'mcp-configs',
            element: (
              <ProtectedRoute adminOnly>
                <McpConfigsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'mcp-debugger',
            element: (
              <ProtectedRoute adminOnly>
                <McpDebuggerPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'query-alerts',
            element: (
              <ProtectedRoute adminOnly>
                <QueryAlertsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'agent-monitor',
            element: (
              <ProtectedRoute adminOnly>
                <AgentMonitorPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'platform-settings',
            element: (
              <ProtectedRoute adminOnly>
                <PlatformSettingsPage />
              </ProtectedRoute>
            ),
          },
        ],
      },

    ],
  },

  // =====================
  // 旧路由 301 重定向（Spec 18 §4.1，兼容期 3 个月）
  // ⚠️ 前端视图路由迁移专用，src/api/ 下的后端 API 路径不在此列
  // =====================
  { path: '/ddl-validator',                    element: <Navigate to="/dev/ddl-validator" replace /> },
  { path: '/rule-config',                      element: <Navigate to="/dev/rule-config" replace /> },
  { path: '/data-governance/health',           element: <Navigate to="/governance/health-center?tab=warehouse" replace /> },
  { path: '/data-governance/quality',           element: <Navigate to="/governance/health-center?tab=quality" replace /> },
  { path: '/semantic-maintenance/datasources', element: <Navigate to="/governance/semantic/datasources" replace /> },
  { path: '/semantic-maintenance/datasources/:id', element: <Navigate to="/governance/semantic/datasources/:id" replace /> },
  { path: '/semantic-maintenance/fields',       element: <Navigate to="/governance/semantic/fields" replace /> },
  { path: '/tableau/assets',                   element: <Navigate to="/assets/tableau" replace /> },
  { path: '/tableau/assets/:id',               element: <Navigate to="/assets/tableau/:id" replace /> },
  { path: '/tableau/health',                   element: <Navigate to="/governance/health-center?tab=tableau" replace /> },
  { path: '/admin/users',                      element: <Navigate to="/system/users" replace /> },
  { path: '/admin/groups',                     element: <Navigate to="/system/groups" replace /> },
  { path: '/admin/permissions',                element: <Navigate to="/system/permissions" replace /> },
  { path: '/admin/llm',                        element: <Navigate to="/system/llm-configs" replace /> },
  { path: '/admin/llm-configs',                element: <Navigate to="/system/llm-configs" replace /> },
  { path: '/system/llm',                       element: <Navigate to="/system/llm-configs" replace /> },
  { path: '/admin/tasks',                      element: <Navigate to="/system/tasks" replace /> },
  { path: '/admin/activity',                    element: <Navigate to="/system/activity" replace /> },
  { path: '/admin/platform-settings',           element: <Navigate to="/system/platform-settings" replace /> },
  { path: '/admin/datasources',                element: <Navigate to="/assets/datasources" replace /> },
  { path: '/admin/tableau/connections',         element: <Navigate to="/assets/tableau-connections" replace /> },
  { path: '/knowledge/:sub',                   element: <Navigate to="/analytics/knowledge" replace /> },
  { path: '/knowledge',                        element: <Navigate to="/analytics/knowledge" replace /> },

  // =====================
  // 遗留兼容（原有杂项 redirect）
  // =====================
  { path: '/database-monitor', element: <Navigate to="/governance/health-center?tab=warehouse" replace /> },

  // /ops → 运维工作台首页（别名）
  { path: '/ops', element: <Navigate to="/ops/workbench" replace /> },

  // =====================
  // 403 / 404
  // =====================
  { path: '/403', element: <ForbiddenPage /> },
  { path: '*', element: <NotFound /> },
];

export default routes;
