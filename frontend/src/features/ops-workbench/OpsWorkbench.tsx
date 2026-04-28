/**
 * OpsWorkbench — 运维工作台外壳（Phase 2 T2）
 *
 * idle/result 状态切换容器，内部组合 ScopePicker + 主内容 + 抽屉。
 *
 * B22: URL 驱动的抽屉状态（pushState/replaceState）
 * B25: 响应式降级（窄屏全屏、超窄屏警告）
 */
import { lazy, Suspense, useState, useEffect } from 'react';
import { ScopeProvider, useScope } from './ScopeContext';
import { ScopePicker } from './ScopePicker';
import { useDrawerUrlState } from './useDrawerUrlState';
import { AssetInspectorDrawer } from './AssetInspectorDrawer';
import { useAuth } from '../../context/AuthContext';
import { ENABLE_OPS_WORKBENCH } from '../../config';

const OpsSnapshotPanel = lazy(() =>
  import('./OpsSnapshotPanel').then((m) => ({ default: m.OpsSnapshotPanel }))
);

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const m = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    m.addEventListener('change', handler);
    return () => m.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

interface OpsWorkbenchInnerProps {
  idleContent: React.ReactNode;
  resultContent?: React.ReactNode;
  submittingContent?: React.ReactNode;
  homeState: 'HOME_IDLE' | 'HOME_SUBMITTING' | 'HOME_RESULT' | 'HOME_ERROR' | 'HOME_OFFLINE';
}

function NoPermissionToast({ message }: { message: string }) {
  return (
    <div className="fixed top-4 right-4 z-[100] bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700 shadow-lg">
      <div className="flex items-center gap-2">
        <i className="ri-error-warning-line text-red-500" />
        {message}
      </div>
    </div>
  );
}

function OpsWorkbenchInner({
  idleContent,
  resultContent,
  submittingContent,
  homeState,
}: OpsWorkbenchInnerProps) {
  const { hasPermission } = useAuth();
  const { assetId, closeAsset, openAsset } = useDrawerUrlState();
  const { connectionId } = useScope();
  const isNarrow = useMediaQuery('(max-width: 767px)');

  const hasAsset = !!assetId;

  // B25: Toast state for permission denied
  const [toast, setToast] = useState<string | null>(null);

  // B25: Show toast when trying to open asset without permission — URL preserved
  useEffect(() => {
    if (hasAsset && !hasPermission('tableau')) {
      setToast('您没有 Tableau 访问权限，无法查看资产详情');
      // Do NOT closeAsset() — URL must be preserved per B25 spec
    }
  }, [hasAsset, hasPermission]);

  let content: React.ReactNode;
  if (homeState === 'HOME_SUBMITTING' && submittingContent) {
    content = submittingContent;
  } else if (homeState === 'HOME_RESULT' && resultContent) {
    content = resultContent;
  } else {
    content = idleContent;
  }

  return (
    <div className="relative flex flex-col min-h-screen bg-white">
      {/* ScopePicker 工具栏 */}
      <div
        className={[
          'w-full px-6',
          homeState === 'HOME_IDLE' ? 'pt-4 pb-2' : 'pt-4 pb-2 border-b border-slate-100',
        ].join(' ')}
      >
        <div className="max-w-3xl mx-auto">
          <ScopePicker variant={homeState === 'HOME_IDLE' ? 'idle' : 'default'} />
        </div>
      </div>

      {/* 主内容区 */}
      <main
        className={[
          'flex-1 flex flex-col w-full',
          homeState === 'HOME_IDLE' ? 'items-center justify-center' : '',
          'pb-40',
        ].join(' ')}
      >
        <div
          className={[
            'w-full max-w-4xl mx-auto px-6',
            homeState === 'HOME_IDLE' ? 'space-y-8' : 'pt-6 space-y-6',
          ].join(' ')}
        >
          {content}
        </div>
      </main>

      {/* B23: OpsSnapshotPanel — idle 态显示运维快照 */}
      {homeState === 'HOME_IDLE' && (
        <div className="w-full max-w-4xl mx-auto px-6 pb-40">
          <Suspense fallback={null}>
            <OpsSnapshotPanel onOpenAsset={openAsset} />
          </Suspense>
        </div>
      )}

      {/* B25: 无权限 Toast */}
      {toast && <NoPermissionToast message={toast} />}

      {/* 资产详情抽屉 */}
      {hasAsset && hasPermission('tableau') && (
        <AssetInspectorDrawer onClose={closeAsset} />
      )}

      {/* B25: 超窄屏降级提示 */}
      {isNarrow && (
        <div className="fixed bottom-20 left-0 right-0 z-50 bg-amber-50 border-t border-amber-200 px-4 py-2 text-xs text-amber-700 text-center">
          窄屏模式下部分功能受限，建议在桌面端使用
        </div>
      )}
    </div>
  );
}

export function OpsWorkbench(props: OpsWorkbenchInnerProps) {
  if (!ENABLE_OPS_WORKBENCH) {
    // Flag disabled: render idle content directly (no workbench shell)
    return <>{props.idleContent}</>;
  }

  return (
    <ScopeProvider>
      <OpsWorkbenchInner {...props} />
    </ScopeProvider>
  );
}
