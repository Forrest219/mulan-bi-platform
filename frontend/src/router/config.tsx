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
    path: "*",
    element: <NotFound />,
  },
];

export default routes;
