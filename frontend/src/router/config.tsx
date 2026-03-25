import type { RouteObject } from "react-router-dom";
import NotFound from "../pages/NotFound";
import Home from "../pages/home/page";
import DDLValidatorPage from "../pages/ddl-validator/page";
import DatabaseMonitorPage from "../pages/database-monitor/page";
import RuleConfigPage from "../pages/rule-config/page";

const routes: RouteObject[] = [
  {
    path: "/",
    element: <Home />,
  },
  {
    path: "/ddl-validator",
    element: <DDLValidatorPage />,
  },
  {
    path: "/database-monitor",
    element: <DatabaseMonitorPage />,
  },
  {
    path: "/rule-config",
    element: <RuleConfigPage />,
  },
  {
    path: "*",
    element: <NotFound />,
  },
];

export default routes;
