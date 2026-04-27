/**
 * AssetPanel -- 资产浏览模式面板
 *
 * 右侧内容区：集成 AssetExplorer（资产浏览器）
 * 复用 features/tableau-explorer/AssetExplorer
 */
import { lazy, Suspense } from 'react';
import { useScope } from '../../home/context/ScopeContext';

const AssetExplorer = lazy(() =>
  import('../../../features/tableau-explorer/AssetExplorer').then(m => ({ default: m.AssetExplorer }))
);

export interface AssetPanelProps {
  /** 点击资产时回调 */
  onSelectAsset?: (assetId: string) => void;
}

export function AssetPanel({ onSelectAsset }: AssetPanelProps) {
  const { connectionId } = useScope();
  const connId = connectionId ? Number(connectionId) : undefined;

  if (!connId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400">
        <i className="ri-stack-line text-4xl mb-3" />
        <p className="text-sm">请先在顶部选择连接</p>
        <p className="text-xs mt-1">选择 Tableau 连接后可浏览资产</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <Suspense
        fallback={
          <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
            <i className="ri-loader-4-line animate-spin mr-2" />
            加载资产浏览器...
          </div>
        }
      >
        <AssetExplorer
          connectionId={connId}
          onSelect={onSelectAsset}
        />
      </Suspense>
    </div>
  );
}
