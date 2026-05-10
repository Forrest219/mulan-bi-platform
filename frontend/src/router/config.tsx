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
import { ConversationProvider } from '../store/conversationStore';

// ──────────────────────────────────────────────────────────────
// 代码分割：每个域独立 chunk（Spec 18 §4.3）
// ──────────────────────────────────────────────────────────────
const ChatPage            = lazy(() => import('../pages/chat/page'));
const LLMConfigsPage      = lazy(() => import('../pages/admin/llm-configs/page'));
const McpConfigsPage      = lazy(() => import('../pages/admin/mcp-configs/page'));
const McpDebuggerPage     = lazy(() => import('../pages/system/mcp-debugger/page'));
const DataConnectionsPage = lazy(() => import('../pages/system/data-connections/page'));
const ServiceConfigsPage  = lazy(() => import('../pages/system/service-configs/page'));
const DataHealthPage      = lazy(() => import('../pages/data-governance/health/page'));
const DwAuditPage         = lazy(() => import('../pages/data-governance/dw-audit/page'));
const TableauAssetBrowserPage = lazy(() => import('../pages/tableau/assets/page'));
const TableauAssetDetailPage  = lazy(() => import('../pages/tableau/asset-detail/page'));
const SyncLogsPage        = lazy(() => import('../pages/tableau/sync-logs/page'));
const SyncLogsAllPage     = lazy(() => import('../pages/tableau/sync-logs-all/page'));
const DatasourcesPage     = lazy(() => import('../pages/assets/datasources/page'));
const TableauConnectionsPage = lazy(() => import('../pages/tableau/connections/page'));
const SemanticDatasourceListPage  = lazy(() => import('../pages/semantic-maintenance/datasource-list/page'));
const SemanticDatasourceDetailPage = lazy(() => import('../pages/semantic-maintenance/datasource-detail/page'));
const SemanticFieldListPage = lazy(() => import('../pages/semantic-maintenance/field-list/page'));
const SemanticPublishLogsPage = lazy(() => import('../pages/semantic-maintenance/publish-logs/page'));
const MetricsPage = lazy(() => import('../pages/data-governance/metrics/page'));
const MetricDetailPage = lazy(() => import('../pages/data-governance/metrics/detail'));
const MaintenanceWindowsPage = lazy(() => import('../pages/data-governance/metrics/maintenance-windows/page'));
const KnowledgePage        = lazy(() => import('../pages/knowledge/page'));
const UsersAdminPage       = lazy(() => import('../pages/admin/user-management/page'));
const GroupsAdminPage      = lazy(() => import('../pages/admin/groups/page'));
const PermissionsAdminPage = lazy(() => import('../pages/admin/permissions/page'));
const SharedPermissionsAdminPage = lazy(() => import('../pages/admin/shared-permissions/page'));
const AdminTasksPage        = lazy(() => import('../pages/admin/tasks/page'));
const ActivityAdminPage     = lazy(() => import('../pages/admin/activity/page'));
const QueryAlertsPage       = lazy(() => import('../pages/admin/query-alerts/page'));
const PlatformSettingsPage  = lazy(() => import('../pages/admin/platform-settings/page'));
const ForgotPasswordPage    = lazy(() => import('../pages/forgot-password/page'));
const ResetPasswordPage    = lazy(() => import('../pages/reset-password/page'));
const EmptyStatePage        = lazy(() => import('../pages/empty/EmptyStatePage'));
const AgentMonitorPage      = lazy(() => import('../pages/admin/agent-monitor/page'));
const TokenStatsPage        = lazy(() => import('../pages/admin/token-stats/page'));
const QueryPage             = lazy(() => import('../pages/query/page'));
const AccountCenterPage     = lazy(() => import('../pages/account/center/page'));
import AccountProfileForm from '../pages/account/profile/page';
import AccountPasswordForm from '../pages/account/password/page';
import AccountSecurityForm from '../pages/account/security/page';
const NotificationsPage     = lazy(() => import('../pages/notifications/page'));

// DQC 模块
const DqcOverviewPage      = lazy(() => import('../pages/data-governance/dqc/overview/page'));
const DqcMonitorPage       = lazy(() => import('../pages/data-governance/dqc/monitor/page'));
const DqcAnalysesPage      = lazy(() => import('../pages/data-governance/dqc/analyses/page'));
const DqcAssetDetailPage   = lazy(() => import('../pages/data-governance/dqc/detail/page'));
const DqcTemplatesPage     = lazy(() => import('../pages/data-governance/dqc/templates/page'));
const DqcTemplateDetailPage = lazy(() => import('../pages/data-governance/dqc/templates/detail'));
const DqcAiCreateRulePage  = lazy(() => import('../pages/data-governance/dqc/templates/ai-create'));
const DqcCheckRecordsPage  = lazy(() => import('../pages/data-governance/dqc/check-records/page'));
const DqcDerivedRulesPage  = lazy(() => import('../pages/data-governance/dqc/derived-rules/page'));

// Agent 模块
const DataWorkbenchPage = lazy(() => import('../pages/agents/data-workbench/page'));
const DataWorkbenchHistoryPage = lazy(() => import('../pages/agents/data-workbench/history/page'));
const SqlAgentPage = lazy(() => import('../pages/agents/sql-agent/page'));
const MetricsAgentPage = lazy(() => import('../pages/agents/metrics-agent/page'));
const SkillsPage = lazy(() => import('../pages/agents/skills/page'));
const SkillDetailPage = lazy(() => import('../pages/agents/skills/detail'));

// Tableau 巡检
const TableauHealthPage = lazy(() => import('../pages/tableau/health/page'));

// 资产模块
const DwAssetsPage = lazy(() => import('../pages/assets/dw/page'));
const DwAssetDetailPage = lazy(() => import('../pages/assets/dw/detail'));
const DwTaxonomyPage = lazy(() => import('../pages/assets/dw/taxonomy/page'));
const StarRocksInspectionPage = lazy(() => import('../pages/assets/starrocks-inspection/page'));
const ConnectionCenterPage = lazy(() => import('../pages/assets/connection-center/page'));

// ──────────────────────────────────────────────────────────────
// 路由定义
// ──────────────────────────────────────────────────────────────
const routes: RouteObject[] = [

  // =====================
  // 公开路由（认证页面，无需登录）
  // =====================
  { path: '/login',          element: <LoginPage /> },
  { path: '/register',       element: <RegisterPage /> },
  { path: '/forgot-password', element: <ForgotPasswordPage /> },
  { path: '/reset-password', element: <ResetPasswordPage /> },

  // =====================
  // 问数模块（独立布局，Spec 38、Spec 14）
  // =====================
  {
    path: '/query',
    element: (
      <ProtectedRoute>
        <QueryPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/query/nl',
    element: (
      <ProtectedRoute requiredPermission="database_monitor">
        <EmptyStatePage />
      </ProtectedRoute>
    ),
  },

  // =====================
  // 统一侧边栏布局（7 域，Spec 18 v0.3 §4.2）
  // =====================
  {
    element: <AppShellLayout />,
    children: [

      // ── 首页 + 对话（无 ProtectedRoute，页面自身处理未登录状态）──
      {
        path: '/',
        element: (
          <ConversationProvider>
            <Home />
          </ConversationProvider>
        ),
      },
      {
        path: '/chat/:id',
        element: (
          <ConversationProvider>
            <ChatPage />
          </ConversationProvider>
        ),
      },

      // ── 域 1：数据开发 /dev ──
      {
        path: '/dev',
        children: [
          {
            path: 'ddl-generator',
            element: (
              <ProtectedRoute requiredPermission="ddl_generator">
                <div className="p-8 text-center text-slate-400">功能开发中</div>
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
            path: 'dw-audit',
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DwAuditPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'tableau-audit',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <TableauHealthPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'health',
            element: <Navigate to="/governance/dw-audit?tab=warehouse" replace />,
          },
          {
            path: 'semantic',
            element: <Navigate to="/governance/semantic/datasources" replace />,
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
            path: 'semantic-maintenance/datasources/:id',
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
              <ProtectedRoute requiredPermission="ddl_check">
                <MetricsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'metrics/:id',
            element: (
              <ProtectedRoute requiredPermission="ddl_check">
                <MetricDetailPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'metrics/maintenance-windows',
            element: (
              <ProtectedRoute requiredPermission="ddl_check">
                <MaintenanceWindowsPage />
              </ProtectedRoute>
            ),
          },
          // DQC 子路由（Spec 31）
          {
            path: 'dqc',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcOverviewPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dqc/monitor',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcMonitorPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dqc/signals',
            element: <Navigate to="/governance/dqc" replace />,
          },
          {
            path: 'dqc/analyses',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcAnalysesPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dqc/templates',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcTemplatesPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dqc/templates/ai-create',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcAiCreateRulePage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dqc/templates/:id',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcTemplateDetailPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dqc/check-records',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcCheckRecordsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dqc/derived-rules',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcDerivedRulesPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dqc/assets/:assetId',
            element: (
              <ProtectedRoute requiredPermission="rule_config">
                <DqcAssetDetailPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'knowledge',
            element: <Navigate to="/assets/knowledge" replace />,
          },
        ],
      },

      // ── 域：数据资产 /assets ──
      {
        path: '/assets',
        children: [
          {
            path: 'dw',
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DwAssetsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dw/taxonomy',
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DwTaxonomyPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dw/:tableId',
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DwAssetDetailPage />
              </ProtectedRoute>
            ),
          },
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
            element: <Navigate to="/governance/tableau-audit" replace />,
          },
          {
            path: 'sync-logs',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SyncLogsAllPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'tableau-connections',
            element: <Navigate to="/system/data-connections?tab=tableau" replace />,
          },
          {
            path: 'tableau-connections/:connId/sync-logs',
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SyncLogsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'connection-center',
            element: <Navigate to="/system/data-connections" replace />,
          },
          {
            path: 'starrocks-inspection',
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <StarRocksInspectionPage />
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
      {
        path: '/analytics',
        children: [
          {
            path: 'nl-query',
            element: <Navigate to="/query" replace />,
          },
          {
            path: 'knowledge',
            element: <Navigate to="/assets/knowledge" replace />,
          },
        ],
      },

      // ── 账户设置 /account ──
      {
        path: '/account',
        element: (
          <ProtectedRoute>
            <AccountCenterPage />
          </ProtectedRoute>
        ),
        children: [
          {
            index: true,
            element: <Navigate to="/account/profile" replace />,
          },
          {
            path: 'profile',
            element: <AccountProfileForm />,
          },
          {
            path: 'password',
            element: <AccountPasswordForm />,
          },
          {
            path: 'security',
            element: <AccountSecurityForm />,
          },
        ],
      },

      // ── 消息中心 ──
      {
        path: '/notifications',
        element: (
          <ProtectedRoute>
            <NotificationsPage />
          </ProtectedRoute>
        ),
      },

      // ── 域：智能体 /agents（Spec 28、29、30） ──
      {
        path: '/agents',
        children: [
          {
            path: 'data',
            element: (
              <ProtectedRoute>
                <DataWorkbenchPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'data/history',
            element: (
              <ProtectedRoute>
                <DataWorkbenchHistoryPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'sql',
            element: (
              <ProtectedRoute>
                <SqlAgentPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'metrics',
            element: (
              <ProtectedRoute>
                <MetricsAgentPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'agent-monitor',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <AgentMonitorPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'skills',
            element: (
              <ProtectedRoute>
                <SkillsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'skills/:skillId',
            element: (
              <ProtectedRoute>
                <SkillDetailPage />
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
              <ProtectedRoute requiredPermission="user_management">
                <UsersAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'users/groups',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <GroupsAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'permissions',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <PermissionsAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'permissions/shared',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <SharedPermissionsAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'usage-stats',
            element: <Navigate to="/system/usage-stats/tokens" replace />,
          },
          {
            path: 'usage-stats/tokens',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <TokenStatsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'usage-stats/query-logs',
            element: <Navigate to="/agents/agent-monitor" replace />,
          },
          {
            path: 'llm',
            element: <Navigate to="/system/llm-configs" replace />,
          },
          {
            path: 'tasks',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <AdminTasksPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'activity',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <ActivityAdminPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'llm-configs',
            element: <Navigate to="/system/service-configs" replace />,
          },
          {
            path: 'mcp-configs',
            element: <Navigate to="/system/service-configs?tab=mcp" replace />,
          },
          {
            path: 'datasources',
            element: <Navigate to="/system/data-connections" replace />,
          },
          {
            path: 'data-connections',
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DataConnectionsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'service-configs',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <ServiceConfigsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'mcp-debugger',
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <McpDebuggerPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'agent-monitor',
            element: <Navigate to="/agents/agent-monitor" replace />,
          },
          {
            path: 'platform-settings',
            element: (
              <ProtectedRoute requiredPermission="user_management">
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
  { path: '/data-governance/health',           element: <Navigate to="/governance/dw-audit?tab=warehouse" replace /> },
  { path: '/semantic-maintenance/datasources', element: <Navigate to="/governance/semantic/datasources" replace /> },
  { path: '/semantic-maintenance/datasources/:id', element: <Navigate to="/governance/semantic-maintenance/datasources/:id" replace /> },
  { path: '/semantic-maintenance/fields',       element: <Navigate to="/governance/semantic/fields" replace /> },
  { path: '/tableau/assets',                   element: <Navigate to="/assets/tableau" replace /> },
  { path: '/tableau/assets/:id',               element: <TableauAssetDetailPage /> },
  { path: '/tableau/health',                   element: <Navigate to="/governance/dw-audit?tab=tableau" replace /> },
  { path: '/admin/users',                      element: <Navigate to="/system/users" replace /> },
  { path: '/admin/groups',                     element: <Navigate to="/system/users/groups" replace /> },
  { path: '/admin/permissions',                element: <Navigate to="/system/permissions" replace /> },
  { path: '/system/groups',                    element: <Navigate to="/system/users/groups" replace /> },
  { path: '/system/shared-permissions',        element: <Navigate to="/system/permissions/shared" replace /> },
  { path: '/system/token-stats',               element: <Navigate to="/system/usage-stats/tokens" replace /> },
  { path: '/system/query-alerts',              element: <Navigate to="/agents/agent-monitor" replace /> },
  { path: '/admin/llm',                        element: <Navigate to="/system/service-configs" replace /> },
  { path: '/admin/llm-configs',                element: <Navigate to="/system/service-configs" replace /> },
  { path: '/system/llm',                       element: <Navigate to="/system/service-configs" replace /> },
  { path: '/system/llm-configs',               element: <Navigate to="/system/service-configs" replace /> },
  { path: '/system/mcp-configs',               element: <Navigate to="/system/service-configs?tab=mcp" replace /> },
  { path: '/admin/tasks',                      element: <Navigate to="/system/tasks" replace /> },
  { path: '/admin/activity',                    element: <Navigate to="/system/activity" replace /> },
  { path: '/admin/platform-settings',           element: <Navigate to="/system/platform-settings" replace /> },
  { path: '/admin/datasources',                element: <Navigate to="/system/data-connections" replace /> },
  { path: '/assets/datasources',               element: <Navigate to="/system/data-connections" replace /> },
  { path: '/system/datasources',               element: <Navigate to="/system/data-connections" replace /> },
  { path: '/admin/tableau/connections',         element: <Navigate to="/system/data-connections?tab=tableau" replace /> },
  { path: '/assets/tableau-connections',        element: <Navigate to="/system/data-connections?tab=tableau" replace /> },
  { path: '/knowledge/:sub',                   element: <Navigate to="/assets/knowledge" replace /> },
  { path: '/knowledge',                        element: <Navigate to="/assets/knowledge" replace /> },
  { path: '/analytics/knowledge',              element: <Navigate to="/assets/knowledge" replace /> },
  { path: '/governance/knowledge',             element: <Navigate to="/assets/knowledge" replace /> },

  // =====================
  // 遗留兼容（原有杂项 redirect）
  // =====================
  { path: '/database-monitor', element: <Navigate to="/governance/dw-audit?tab=warehouse" replace /> },
  { path: '/governance/health-center', element: <Navigate to="/governance/dw-audit" replace /> },

  // /ops/workbench → 首页（Spec 20: 原型路由已废弃，重定向到 /）
  { path: '/ops/workbench', element: <Navigate to="/" replace /> },

  // /ops → 首页（Spec 20: 工作台已合并到 /）
  { path: '/ops', element: <Navigate to="/" replace /> },

  // Gap-08: /system → / 重定向（无需 admin 权限，回归普通用户视图）
  { path: '/system', element: <Navigate to="/" replace /> },

  // =====================
  // 403 / 404
  // =====================
  { path: '/403', element: <ForbiddenPage /> },
  { path: '*', element: <NotFound /> },
];

export default routes;
