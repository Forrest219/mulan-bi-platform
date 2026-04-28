/**
 * AssetInspectorDrawer — 资产详情抽屉（Ops Workbench 版本）
 *
 * B25: 响应式行为
 * - 窄屏（< 1280px）: 全屏 Sheet 模式
 * - 超窄屏（< 768px）: 降级提示
 * - 无 tableau 权限: 不打开抽屉，保留 URL，显示 toast
 */
import { lazy, Suspense, useEffect, useState } from 'react';
import { useDrawerUrlState } from './useDrawerUrlState';
import { useAuth } from '../../context/AuthContext';

const AssetInspector = lazy(() =>
  import('../tableau-inspector/AssetInspector').then((m) => ({
    default: m.AssetInspector,
  })),
);

interface AssetInspectorDrawerProps {
  onClose: () => void;
}

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

export function AssetInspectorDrawer({ onClose }: AssetInspectorDrawerProps) {
  const { hasPermission } = useAuth();
  const { assetId, tab } = useDrawerUrlState();
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const isMobile = useMediaQuery('(max-width: 1279px)');
  const isNarrow = useMediaQuery('(max-width: 767px)');

  useEffect(() => {
    if (!assetId) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [assetId, onClose]);

  // B25: 无 tableau 权限用户不打开抽屉，但保留 URL
  if (!assetId) return null;

  if (!hasPermission('tableau')) {
    // Toast will be shown by parent; we don't render the drawer
    return null;
  }

  const isFullScreen = isMobile;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer / Full-Screen Sheet */}
      <div
        className={`fixed z-50 flex flex-col bg-white shadow-xl ${
          isFullScreen
            ? 'inset-0 w-full'
            : 'right-0 top-0 h-full w-full max-w-2xl border-l border-slate-200'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <span className="text-sm text-slate-500">资产详情</span>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-100 text-slate-500 hover:text-slate-800 transition-colors"
            aria-label="关闭"
          >
            <i className="ri-close-line text-xl" />
          </button>
        </div>

        {/* Narrow viewport warning */}
        {isNarrow && (
          <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-xs text-amber-700 text-center">
            窄屏模式下部分功能受限，建议在桌面端使用
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          <Suspense
            fallback={
              <div className="flex items-center justify-center h-full text-slate-400 text-sm">
                加载中...
              </div>
            }
          >
            <AssetInspector
              assetId={assetId}
              layout="drawer"
              defaultTab={tab}
              onClose={onClose}
            />
          </Suspense>
        </div>
      </div>
    </>
  );
}
