import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

export type DrawerTab = 'info' | 'datasources' | 'children' | 'fields' | 'health' | 'ai';

const VALID_TABS = new Set<DrawerTab>(['info', 'datasources', 'children', 'fields', 'health', 'ai']);
const DEFAULT_TAB: DrawerTab = 'info';

function parseTab(raw: string | null): DrawerTab {
  if (raw && VALID_TABS.has(raw as DrawerTab)) return raw as DrawerTab;
  return DEFAULT_TAB;
}

export interface DrawerUrlState {
  assetId: string | null;
  tab: DrawerTab;
}

export interface DrawerUrlActions {
  openAsset: (id: string, tab?: DrawerTab) => void;
  closeAsset: () => void;
  setTab: (tab: DrawerTab) => void;
}

export function useDrawerUrlState(): DrawerUrlState & DrawerUrlActions {
  const [searchParams, setSearchParams] = useSearchParams();

  const assetId = searchParams.get('asset');
  const tab = parseTab(searchParams.get('tab'));

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

  const openAsset = useCallback(
    (id: string, newTab?: DrawerTab) => {
      const params = buildParams({ asset: id, tab: newTab ?? DEFAULT_TAB });
      setSearchParams(params, { replace: false }); // pushState for browser history
    },
    [buildParams, setSearchParams],
  );

  const closeAsset = useCallback(() => {
    const params = buildParams({ asset: null, tab: null });
    setSearchParams(params, { replace: true }); // replaceState - no extra history entry
  }, [buildParams, setSearchParams]);

  const setTab = useCallback(
    (newTab: DrawerTab) => {
      const params = buildParams({ tab: newTab });
      setSearchParams(params, { replace: true });
    },
    [buildParams, setSearchParams],
  );

  return { assetId, tab, openAsset, closeAsset, setTab };
}
