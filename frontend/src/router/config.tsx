import type { RouteObject } from "react-router-dom";
import NotFound from "../pages/NotFound";
import Home from "../pages/home/page";
import DDLValidatorPage from "../pages/ddl-validator/page";
import DatabaseMonitorPage from "../pages/database-monitor/page";
import RuleConfigPage from "../pages/rule-config/page";
import LoginPage from "../pages/login/page";
import RegisterPage from "../pages/register/page";
import ProtectedRoute from "../components/auth/ProtectedRoute";
import AdminLayout from "../components/AdminLayout";
import UsersAdminPage from "../pages/admin/user-management/page";
import GroupsAdminPage from "../pages/admin/groups/page";
import PermissionsAdminPage from "../pages/admin/permissions/page";
import ActivityAdminPage from "../pages/admin/activity/page";
import LLMAdminPage from "../pages/admin/llm/page";
import TableauConnectionsPage from "../pages/tableau/connections/page";
import TableauAssetBrowserPage from "../pages/tableau/assets/page";
import TableauAssetDetailPage from "../pages/tableau/asset-detail/page";
import SyncLogsPage from "../pages/tableau/sync-logs/page";

const routes: RouteObject[] = [
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
  {
    path: "/ddl-validator",
    element: (
      <ProtectedRoute requiredPermission="ddl_check">
        <DDLValidatorPage />
      </ProtectedRoute>
    ),
  },
  {
    path: "/database-monitor",
    element: (
      <ProtectedRoute requiredPermission="database_monitor">
        <DatabaseMonitorPage />
      </ProtectedRoute>
    ),
  },
  {
    path: "/rule-config",
    element: (
      <ProtectedRoute requiredPermission="rule_config">
        <RuleConfigPage />
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/users",
    element: (
      <ProtectedRoute adminOnly>
        <AdminLayout><UsersAdminPage /></AdminLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/groups",
    element: (
      <ProtectedRoute adminOnly>
        <AdminLayout><GroupsAdminPage /></AdminLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/permissions",
    element: (
      <ProtectedRoute adminOnly>
        <AdminLayout><PermissionsAdminPage /></AdminLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/activity",
    element: (
      <ProtectedRoute adminOnly>
        <AdminLayout><ActivityAdminPage /></AdminLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/admin/llm",
    element: (
      <ProtectedRoute adminOnly>
        <AdminLayout><LLMAdminPage /></AdminLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/tableau/connections",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <AdminLayout><TableauConnectionsPage /></AdminLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "/tableau/assets",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <TableauAssetBrowserPage />
      </ProtectedRoute>
    ),
  },
  {
    path: "/tableau/assets/:id",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <TableauAssetDetailPage />
      </ProtectedRoute>
    ),
  },
  {
    path: "/tableau/connections/:connId/sync-logs",
    element: (
      <ProtectedRoute requiredPermission="tableau">
        <AdminLayout><SyncLogsPage /></AdminLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: "*",
    element: <NotFound />,
  },
];

export default routes;
