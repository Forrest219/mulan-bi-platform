/**
 * useHomeUrlState
 *
 * 把首页工作台所需的 URL query 参数与 React state 双向同步。
 *
 * URL 参数定义：
 *   ?asset=<id>          — 打开的资产 ID
 *   ?tab=info|datasources|children|fields|health|ai  — 抽屉 Tab
 *   ?connection=<id>     — 当前选中连接 ID
 *   ?scope_project=<id>  — 项目筛选
 */
import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

export type AssetTab = 'info' | 'datasources' | 'children' | 'fields' | 'health' | 'ai';

const VALID_TABS = new Set<AssetTab>(['info', 'datasources', 'children', 'fields', 'health', 'ai']);

const DEFAULT_TAB: AssetTab = 'info';

export interface HomeUrlState {
  assetId: string | null;
  tab: AssetTab;
  connectionId: string | null;
  scopeProject: string | null;
  selectedConvId: string | null;
}

export interface HomeUrlActions {
  /** 打开资产抽屉，产生新历史记录，使浏览器后退可关闭抽屉 */
  openAsset: (id: string, tab?: AssetTab) => void;
  /** 关闭资产抽屉，replaceState 不产生多余历史记录 */
  closeAsset: () => void;
  /** 切换抽屉 Tab，replaceState */
  setTab: (tab: AssetTab) => void;
  /** 设置选中连接，replaceState */
  setConnection: (id: string | null) => void;
  /** 设置项目筛选，replaceState */
  setScopeProject: (id: string | null) => void;
}

function parseTab(raw: string | null): AssetTab {
  if (raw && VALID_TABS.has(raw as AssetTab)) {
    return raw as AssetTab;
  }
  return DEFAULT_TAB;
}

export function useHomeUrlState(): HomeUrlState & HomeUrlActions {
  const [searchParams, setSearchParams] = useSearchParams();

  // --- 读取当前 URL 状态 ---
  const assetId = searchParams.get('asset');
  const tab = parseTab(searchParams.get('tab'));
  const connectionId = searchParams.get('connection');
  const scopeProject = searchParams.get('scope_project');
  const selectedConvId = searchParams.get('conv');

  // --- 辅助：基于当前 params 构建新的 URLSearchParams，只更新指定 key ---
  const buildParams = useCallback(
    (updates: Record<string, string | null>): URLSearchParams => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(updates)) {
        if (value === null) {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      }
      return next;
    },
    [searchParams],
  );

  // --- Actions ---

  const openAsset = useCallback(
    (id: string, newTab?: AssetTab) => {
      const params = buildParams({
        asset: id,
        tab: newTab ?? DEFAULT_TAB,
      });
      setSearchParams(params, { replace: false });
    },
    [buildParams, setSearchParams],
  );

  const closeAsset = useCallback(() => {
    const params = buildParams({ asset: null, tab: null });
    setSearchParams(params, { replace: true });
  }, [buildParams, setSearchParams]);

  const setTab = useCallback(
    (newTab: AssetTab) => {
      const params = buildParams({ tab: newTab });
      setSearchParams(params, { replace: true });
    },
    [buildParams, setSearchParams],
  );

  const setConnection = useCallback(
    (id: string | null) => {
      const params = buildParams({ connection: id });
      setSearchParams(params, { replace: true });
    },
    [buildParams, setSearchParams],
  );

  const setScopeProject = useCallback(
    (id: string | null) => {
      const params = buildParams({ scope_project: id });
      setSearchParams(params, { replace: true });
    },
    [buildParams, setSearchParams],
  );

  return {
    // state
    assetId,
    tab,
    connectionId,
    scopeProject,
    selectedConvId,
    // actions
    openAsset,
    closeAsset,
    setTab,
    setConnection,
    setScopeProject,
  };
}
