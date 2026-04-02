import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";
import NotFound from "../pages/NotFound";
import Home from "../pages/home/page";
import DDLValidatorPage from "../pages/ddl-validator/page";
import RuleConfigPage from "../pages/rule-config/page";
import LoginPage from "../pages/login/page";
import RegisterPage from "../pages/register/page";
import ProtectedRoute from "../components/auth/ProtectedRoute";
import MainLayout from "../components/MainLayout";
import AdminSidebarLayout from "../components/AdminSidebarLayout";
import UsersAdminPage from "../pages/admin/user-management/page";
import GroupsAdminPage from "../pages/admin/groups/page";
import PermissionsAdminPage from "../pages/admin/permissions/page";
import ActivityAdminPage from "../pages/admin/activity/page";
import AdminDatasourcesPage from "../pages/admin/datasources/page";
import AdminTasksPage from "../pages/admin/tasks/page";
import LLMAdminPage from "../pages/admin/llm/page";
import TableauConnectionsPage from "../pages/tableau/connections/page";
import TableauAssetBrowserPage from "../pages/tableau/assets/page";
import TableauAssetDetailPage from "../pages/tableau/asset-detail/page";
import SyncLogsPage from "../pages/tableau/sync-logs/page";
import TableauHealthPage from "../pages/tableau/health/page";
import SemanticDatasourceListPage from "../pages/semantic-maintenance/datasource-list/page";
import SemanticDatasourceDetailPage from "../pages/semantic-maintenance/datasource-detail/page";
import SemanticFieldListPage from "../pages/semantic-maintenance/field-list/page";
import KnowledgePage from "../pages/knowledge/page";
import DataHealthPage from "../pages/data-governance/health/page";
import DataQualityPage from "../pages/data-governance/quality/page";

const routes: RouteObject[] = [
  // =====================
  // 公开路由（无布局）
  // =====================
  {
    path: "/",
    element: <Home />,
  },
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/register",
    element: <RegisterPage />,
  },

  // =====================
  // MainLayout 路由组
  // =====================
  {
    path: "/ddl-validator",
    element: (
      <ProtectedRoute requiredPermission="ddl_check">
        <MainLayout><DDLValidatorPage /></MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/rule-config",
    element: (
      <ProtectedRoute requiredPermission="rule_config">
        <MainLayout><RuleConfigPage /></MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/data-governance/health",
    element: (
      <ProtectedRoute requiredPermission="database_monitor">
        <MainLayout><DataHealthPage /></MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/data-governance/quality",
    element: (
      <ProtectedRoute requiredPermission="database_monitor">
        <MainLayout><DataQualityPage /></MainLayout>
      </ProtectedRoute>
    ),
  },

  // 知识库（V1 占位）
  {
    path: "/knowledge/:sub",
    element: (
      <ProtectedRoute>
        <MainLayout><KnowledgePage /></MainLayout>
      </ProtectedRoute>
    ),
  },

  // Tableau 资产浏览
  {
    path: "/tableau/assets",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <MainLayout><TableauAssetBrowserPage /></MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/tableau/assets/:id",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <MainLayout><TableauAssetDetailPage /></MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/tableau/health",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <MainLayout><TableauHealthPage /></MainLayout>
      </ProtectedRoute>
    ),
  },

  // 语义维护
  {
    path: "/semantic-maintenance/datasources",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <MainLayout><SemanticDatasourceListPage /></MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/semantic-maintenance/datasources/:id",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <MainLayout><SemanticDatasourceDetailPage /></MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/semantic-maintenance/fields",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <MainLayout><SemanticFieldListPage /></MainLayout>
      </ProtectedRoute>
    ),
  },

  // =====================
  // AdminSidebarLayout 路由组
  // =====================
  {
    path: "/admin/users",
    element: (
      <ProtectedRoute adminOnly>
        <AdminSidebarLayout><UsersAdminPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/groups",
    element: (
      <ProtectedRoute adminOnly>
        <AdminSidebarLayout><GroupsAdminPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/permissions",
    element: (
      <ProtectedRoute adminOnly>
        <AdminSidebarLayout><PermissionsAdminPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/activity",
    element: (
      <ProtectedRoute adminOnly>
        <AdminSidebarLayout><ActivityAdminPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/llm",
    element: (
      <ProtectedRoute adminOnly>
        <AdminSidebarLayout><LLMAdminPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/datasources",
    element: (
      <ProtectedRoute adminOnly>
        <AdminSidebarLayout><AdminDatasourcesPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/tasks",
    element: (
      <ProtectedRoute adminOnly>
        <AdminSidebarLayout><AdminTasksPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  // Tableau 连接管理（新路径）
  {
    path: "/admin/tableau/connections",
    element: (
      <ProtectedRoute adminOnly>
        <AdminSidebarLayout><TableauConnectionsPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  // Tableau 连接（旧路径，兼容）
  {
    path: "/tableau/connections",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <AdminSidebarLayout><TableauConnectionsPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/tableau/connections/:connId/sync-logs",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <AdminSidebarLayout><SyncLogsPage /></AdminSidebarLayout>
      </ProtectedRoute>
    ),
  },

  // =====================
  // 404
  // =====================
  {
    path: "/database-monitor",
    element: <Navigate to="/data-governance/health" replace />,
  },
  {
    path: "*",
    element: <NotFound />,
  },
];

export default routes;
