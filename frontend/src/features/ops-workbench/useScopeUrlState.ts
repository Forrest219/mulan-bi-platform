import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

export interface ScopeUrlState {
  connectionId: string | null;
  scopeProject: string | null;
}

export interface ScopeUrlActions {
  setConnection: (id: string | null) => void;
  setScopeProject: (id: string | null) => void;
}

export function useScopeUrlState(): ScopeUrlState & ScopeUrlActions {
  const [searchParams, setSearchParams] = useSearchParams();

  const connectionId = searchParams.get('connection');
  const scopeProject = searchParams.get('scope_project');

  const buildParams = useCallback(
    (updates: Record<string, string | null>): URLSearchParams => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(updates)) {
        if (value === null) next.delete(key);
        else next.set(key, value);
      }
      return next;
    },
    [searchParams],
  );

  const setConnection = useCallback(
    (id: string | null) => {
      setSearchParams(buildParams({ connection: id }), { replace: true });
    },
    [buildParams, setSearchParams],
  );

  const setScopeProject = useCallback(
    (id: string | null) => {
      setSearchParams(buildParams({ scope_project: id }), { replace: true });
    },
    [buildParams, setSearchParams],
  );

  return { connectionId, scopeProject, setConnection, setScopeProject };
}
