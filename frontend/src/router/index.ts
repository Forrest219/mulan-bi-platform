import { useNavigate, type NavigateFunction } from "react-router-dom";
import { matchRoutes, useLocation, useRoutes } from "react-router-dom";
import { createElement, useEffect, useMemo } from "react";
import { HelpAgentContextProvider, type HelpPageProfile } from "../pages/agents/help-agent/helpAgentContext";
import routes from "./config";

let navigateResolver: (navigate: ReturnType<typeof useNavigate>) => void;

declare global {
  interface Window {
    REACT_APP_NAVIGATE: ReturnType<typeof useNavigate>;
  }
}

export const navigatePromise = new Promise<NavigateFunction>((resolve) => {
  navigateResolver = resolve;
});

export function AppRoutes() {
  const element = useRoutes(routes);
  const location = useLocation();
  const navigate = useNavigate();
  const helpProfile = useMemo(() => {
    const matches = matchRoutes(routes, location);
    const matchedRoute = matches
      ?.slice()
      .reverse()
      .find((match) => (match.route.handle as { helpProfile?: HelpPageProfile } | undefined)?.helpProfile);
    return (matchedRoute?.route.handle as { helpProfile?: HelpPageProfile } | undefined)?.helpProfile;
  }, [location]);

  useEffect(() => {
    window.REACT_APP_NAVIGATE = navigate;
    navigateResolver(window.REACT_APP_NAVIGATE);
  }, [navigate]);
  return createElement(HelpAgentContextProvider, { profile: helpProfile }, element);
}
