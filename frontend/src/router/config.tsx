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
import { type RouteObject, Navigate, useLocation } from 'react-router-dom';
import NotFound from '../pages/NotFound';
import Home from '../pages/home/page';
import LoginPage from '../pages/login/page';
import RegisterPage from '../pages/register/page';
import ForbiddenPage from '../pages/ForbiddenPage';
import ProtectedRoute from '../components/auth/ProtectedRoute';
import AppShellLayout from '../components/layout/AppShellLayout';
import { ConversationProvider } from '../store/conversationStore';
import { useAuth } from '../context/AuthContext';
import type { HelpPageProfile } from '../pages/agents/help-agent/helpAgentContext';

interface HelpRouteHandle {
  helpProfile?: HelpPageProfile;
}

const helpProfile = (profile: HelpPageProfile): HelpRouteHandle => ({
  helpProfile: profile,
});

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
const HelpAgentPage = lazy(() => import('../pages/agents/help-agent/page'));
const SkillsPage = lazy(() => import('../pages/agents/skills/page'));
const SkillCreatePage = lazy(() => import('../pages/agents/skills/create'));
const SkillDetailPage = lazy(() => import('../pages/agents/skills/detail'));

// Tableau 巡检
const TableauHealthPage = lazy(() => import('../pages/tableau/health/page'));

// 资产模块
const DataExplorerPage = lazy(() => import('../pages/assets/data-explorer/page'));
const DwAssetsPage = lazy(() => import('../pages/assets/dw/page'));
const DwAssetDetailPage = lazy(() => import('../pages/assets/dw/detail'));
const DwTaxonomyPage = lazy(() => import('../pages/assets/dw/taxonomy/page'));
const StarRocksInspectionPage = lazy(() => import('../pages/assets/starrocks-inspection/page'));
const ConnectionCenterPage = lazy(() => import('../pages/assets/connection-center/page'));

// eslint-disable-next-line react-refresh/only-export-components
function SkillsRouteGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-slate-500">加载中...</div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (user.role !== 'admin' && user.role !== 'data_admin') {
    return <Navigate to="/403" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}

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
            handle: helpProfile({
              page_key: 'dw-audit',
              page_title: '数仓巡检',
              page_domain: 'governance',
              default_questions: [
                '最近有哪些数仓巡检失败？',
                '哪些巡检规则风险最高？',
                '这些风险项应该怎么处理？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DwAuditPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'tableau-audit',
            handle: helpProfile({
              page_key: 'tableau-audit',
              page_title: 'Tableau 巡检',
              page_domain: 'governance',
              default_questions: [
                'Tableau 连接现在是否正常？',
                '哪些 Tableau 资产健康度异常？',
                'MCP 状态异常应该怎么排查？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'semantic',
              page_title: '语义治理',
              page_domain: 'governance',
              default_questions: [
                '字段语义有哪些待维护项？',
                '指标定义是否存在冲突？',
                '语义发布失败应该怎么排查？',
              ],
            }),
            element: <Navigate to="/governance/semantic/datasources" replace />,
          },
          {
            path: 'semantic/datasources',
            handle: helpProfile({
              page_key: 'semantic',
              page_title: '语义治理',
              page_domain: 'governance',
              default_questions: [
                '字段语义有哪些待维护项？',
                '指标定义是否存在冲突？',
                '语义发布失败应该怎么排查？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'semantic',
              page_title: '语义治理',
              page_domain: 'governance',
              default_questions: [
                '字段语义有哪些待维护项？',
                '指标定义是否存在冲突？',
                '语义发布失败应该怎么排查？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SemanticFieldListPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'semantic/publish-logs',
            handle: helpProfile({
              page_key: 'semantic',
              page_title: '语义治理',
              page_domain: 'governance',
              default_questions: [
                '字段语义有哪些待维护项？',
                '指标定义是否存在冲突？',
                '语义发布失败应该怎么排查？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <SemanticPublishLogsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'metrics',
            handle: helpProfile({
              page_key: 'metrics',
              page_title: '指标治理',
              page_domain: 'governance',
              default_questions: [
                '这些指标口径是否一致？',
                '指标依赖关系有哪些风险？',
                '指标发布状态异常怎么处理？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="ddl_check">
                <MetricsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'metrics/:id',
            handle: helpProfile({
              page_key: 'metric-detail',
              page_title: '指标详情',
              page_domain: 'governance',
              default_questions: [
                '这个指标的口径和依赖是否一致？',
                '这个指标关联了哪些字段和上游表？',
                '这个指标发布失败应该怎么排查？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'dqc',
              page_title: '数据质量监控',
              page_domain: 'governance',
              default_questions: [
                '最近哪些质量规则失败？',
                '哪些执行任务有告警？',
                '数据质量异常应该怎么排查？',
              ],
            }),
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
            path: 'explorer',
            handle: helpProfile({
              page_key: 'data-explorer',
              page_title: 'Data Explorer',
              page_domain: 'assets',
              default_questions: [
                '这个连接的 Schema 如何查看？',
                '为什么表预览加载失败？',
                '当前数据权限应该怎么确认？',
              ],
            }),
            element: (
              <ProtectedRoute>
                <DataExplorerPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'dw',
            handle: helpProfile({
              page_key: 'dw-assets',
              page_title: '数仓资产',
              page_domain: 'assets',
              default_questions: [
                '这张表的字段含义是什么？',
                '如何查看表血缘和影响范围？',
                '资产同步或预览失败怎么排查？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'tableau-assets',
              page_title: 'Tableau 资产',
              page_domain: 'assets',
              default_questions: [
                '这个 Tableau 数据源关联哪些字段？',
                '哪些 Tableau 资产健康度异常？',
                'Tableau 同步失败应该怎么排查？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="tableau">
                <TableauAssetBrowserPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'tableau/:id',
            handle: helpProfile({
              page_key: 'tableau-asset-detail',
              page_title: 'Tableau 资产详情',
              page_domain: 'assets',
              default_questions: [
                '这个资产的字段元数据是否完整？',
                '这个资产的 MCP 调用是否正常？',
                '这个资产健康度异常怎么排查？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'knowledge',
              page_title: '知识库',
              page_domain: 'assets',
              default_questions: [
                '如何搜索相关术语和文档？',
                '这个术语关联了哪些指标？',
                '为什么知识库结果不准确？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'account-profile',
              page_title: '个人中心',
              page_domain: 'account',
              default_questions: [
                '如何修改头像和个人信息？',
                '修改密码失败应该怎么处理？',
                '账号安全设置在哪里查看？',
              ],
            }),
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
        handle: helpProfile({
          page_key: 'notifications',
          page_title: '消息通知',
          page_domain: 'admin',
          default_questions: [
            '有哪些未读告警需要处理？',
            '这些通知来自哪些任务或资产？',
            '为什么没有收到预期通知？',
          ],
        }),
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
            handle: helpProfile({
              page_key: 'data-agent',
              page_title: 'Data Agent',
              page_domain: 'agents',
              default_questions: [
                '为什么这次问答失败？',
                '当前问题使用了哪些数据源？',
                '工具链调用异常怎么排查？',
              ],
            }),
            element: (
              <ProtectedRoute>
                <DataWorkbenchPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'data/history',
            handle: helpProfile({
              page_key: 'data-agent',
              page_title: 'Data Agent',
              page_domain: 'agents',
              default_questions: [
                '为什么这次问答失败？',
                '当前问题使用了哪些数据源？',
                '工具链调用异常怎么排查？',
              ],
            }),
            element: (
              <ProtectedRoute>
                <DataWorkbenchHistoryPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'sql',
            handle: helpProfile({
              page_key: 'sql-agent',
              page_title: 'SQL Agent',
              page_domain: 'agents',
              default_questions: [
                '这段 SQL 为什么生成失败？',
                'SQL 执行权限不足怎么处理？',
                '执行错误应该先看哪些信息？',
              ],
            }),
            element: (
              <ProtectedRoute>
                <SqlAgentPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'metrics',
            handle: helpProfile({
              page_key: 'metrics-agent',
              page_title: 'Metrics Agent',
              page_domain: 'agents',
              default_questions: [
                '指标生成失败应该怎么排查？',
                '如何确认指标口径是否正确？',
                '生成结果依赖了哪些字段？',
              ],
            }),
            element: (
              <ProtectedRoute>
                <MetricsAgentPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'help',
            handle: helpProfile({
              page_key: 'help-agent',
              page_title: 'Help Agent',
              page_domain: 'agents',
              default_questions: [
                'Help Agent 可以帮我诊断什么？',
                '如何让回答带上当前页面上下文？',
                '诊断结果不准确应该怎么反馈？',
              ],
            }),
            element: (
              <ProtectedRoute>
                <HelpAgentPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'agent-monitor',
            handle: helpProfile({
              page_key: 'agent-monitor',
              page_title: 'Agent 监控',
              page_domain: 'agents',
              default_questions: [
                '最近有哪些失败的 Agent run？',
                '哪个 step 耗时最长？',
                '失败原因应该怎么定位？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <AgentMonitorPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'skills',
            handle: helpProfile({
              page_key: 'skills',
              page_title: '技能中心',
              page_domain: 'agents',
              default_questions: [
                '哪些 skill 当前已启用？',
                'skill 版本变更如何生效？',
                'schema 校验失败应该怎么修？',
              ],
            }),
            element: (
              <SkillsRouteGuard>
                <SkillsPage />
              </SkillsRouteGuard>
            ),
          },
          {
            path: 'skills/create',
            element: (
              <SkillsRouteGuard>
                <SkillCreatePage />
              </SkillsRouteGuard>
            ),
          },
          {
            path: 'skills/:skillId',
            handle: helpProfile({
              page_key: 'skill-detail',
              page_title: '技能详情',
              page_domain: 'agents',
              default_questions: [
                '当前技能版本是否已生效？',
                '这个技能的 schema 是否正确？',
                '技能启用失败应该怎么排查？',
              ],
            }),
            element: (
              <SkillsRouteGuard>
                <SkillDetailPage />
              </SkillsRouteGuard>
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
            handle: helpProfile({
              page_key: 'users',
              page_title: '用户管理',
              page_domain: 'admin',
              default_questions: [
                '如何排查用户登录问题？',
                '用户角色应该如何分配？',
                '账号状态异常怎么处理？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'permissions',
              page_title: '权限配置',
              page_domain: 'admin',
              default_questions: [
                '如何检查资源权限配置？',
                '角色策略冲突怎么处理？',
                '用户为什么看不到某个功能？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'token-stats',
              page_title: 'Token 统计',
              page_domain: 'admin',
              default_questions: [
                '最近 token 消耗为什么升高？',
                '哪些模型调用成本最高？',
                '如何定位异常 token 使用？',
              ],
            }),
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
            path: 'tasks/*',
            handle: helpProfile({
              page_key: 'tasks',
              page_title: '任务管理',
              page_domain: 'config',
              default_questions: [
                '最近哪些调度任务失败？',
                '任务没有按时运行怎么排查？',
                '如何查看任务最近运行记录？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <AdminTasksPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'activity',
            handle: helpProfile({
              page_key: 'activity',
              page_title: '操作日志',
              page_domain: 'admin',
              default_questions: [
                '如何追踪某个用户的操作？',
                '哪些操作可能存在异常？',
                '日志筛选结果应该怎么解读？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'data-connections',
              page_title: '数据连接',
              page_domain: 'config',
              default_questions: [
                '连接测试失败应该怎么排查？',
                '凭据配置是否需要更新？',
                '数据连接同步异常怎么处理？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="database_monitor">
                <DataConnectionsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'service-configs',
            handle: helpProfile({
              page_key: 'service-configs',
              page_title: '服务配置',
              page_domain: 'config',
              default_questions: [
                'LLM 配置是否可用？',
                'MCP 配置异常怎么排查？',
                '密钥状态应该如何检查？',
              ],
            }),
            element: (
              <ProtectedRoute requiredPermission="user_management">
                <ServiceConfigsPage />
              </ProtectedRoute>
            ),
          },
          {
            path: 'mcp-debugger',
            handle: helpProfile({
              page_key: 'mcp-debugger',
              page_title: 'MCP 调试器',
              page_domain: 'config',
              default_questions: [
                '这个 MCP 工具调用为什么失败？',
                '工具参数应该如何填写？',
                '错误日志里应该重点看什么？',
              ],
            }),
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
            handle: helpProfile({
              page_key: 'platform-settings',
              page_title: '平台设置',
              page_domain: 'admin',
              default_questions: [
                '如何修改平台 Logo 和首页配置？',
                '系统配置保存失败怎么排查？',
                '哪些设置会影响所有用户？',
              ],
            }),
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
