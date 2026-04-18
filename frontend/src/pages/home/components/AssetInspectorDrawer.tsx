import { lazy, Suspense, useEffect } from 'react';

const AssetInspector = lazy(() =>
  import('../../../features/tableau-inspector/AssetInspector').then(m => ({ default: m.AssetInspector }))
);

interface AssetInspectorDrawerProps {
  assetId: string | null;
  tab?: string;
  onClose: () => void;
}

export function AssetInspectorDrawer({ assetId, tab, onClose }: AssetInspectorDrawerProps) {
  useEffect(() => {
    if (!assetId) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [assetId, onClose]);

  if (!assetId) return null;

  return (
    <>
      {/* 背景遮罩 */}
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* 抽屉本体 */}
      <div className="fixed right-0 top-0 h-full z-50 flex flex-col w-full max-w-2xl xl:max-w-2xl bg-white border-l border-slate-200 shadow-xl">
        {/* 关闭按钮 */}
        <button
          type="button"
          onClick={onClose}
          className="absolute top-3 right-4 z-10 p-1 rounded hover:bg-slate-100 text-slate-500 hover:text-slate-800 transition-colors"
          aria-label="关闭"
        >
          <i className="ri-close-line text-xl" />
        </button>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto">
          <Suspense fallback={<div className="flex items-center justify-center h-full text-slate-400 text-sm">加载中...</div>}>
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
