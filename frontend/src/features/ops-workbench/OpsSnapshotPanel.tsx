/**
 * OpsSnapshotPanel — 运维快照面板（Phase 3 T8 / B23）
 *
 * 从 home/components/OpsSnapshotPanel.tsx 迁移，React Query 化。
 * 使用 useOpsSnapshot 获取健康总览与同步状态。
 */
import { useScope } from './ScopeContext';
import { useOpsSnapshot } from './useOpsSnapshot';
import { LowHealthList } from './components';
import { RecentSyncFailures } from './components';
import { PendingActionsList } from './components';
import type { HealthOverview } from '../../api/tableau';

interface OpsSnapshotPanelProps {
  /** 点击问题资产时打开抽屉 */
  onOpenAsset: (assetId: string, tab?: string) => void;
}

interface SyncState {
  last_sync_at: string | null;
  status: string;
  last_sync_duration_sec: number | null;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  next_sync_at: string | null;
}

/** 健康等级 → Tailwind 颜色类 */
function levelColor(level: string): string {
  switch (level) {
    case 'excellent': return 'bg-emerald-100 text-emerald-700';
    case 'good':      return 'bg-blue-100 text-blue-700';
    case 'warning':   return 'bg-amber-100 text-amber-700';
    case 'poor':      return 'bg-red-100 text-red-700';
    default:          return 'bg-slate-100 text-slate-500';
  }
}

export function OpsSnapshotPanel({ onOpenAsset }: OpsSnapshotPanelProps) {
  const { connectionId } = useScope();
  const { health: overview, healthLoading, sync, syncLoading } = useOpsSnapshot(connectionId);

  // ── 降级：未选择连接 ────────────────────────────────────────────────────
  if (!connectionId) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400 text-center">
        请先选择连接
      </div>
    );
  }

  // ── 加载中 ───────────────────────────────────────────────────────────────
  if (healthLoading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="animate-pulse space-y-3">
          <div className="h-4 w-1/3 bg-slate-100 rounded" />
          <div className="h-3 w-full bg-slate-100 rounded" />
          <div className="h-3 w-5/6 bg-slate-100 rounded" />
        </div>
      </div>
    );
  }

  // ── 降级：API 失败 / 无数据 ───────────────────────────────────────────────
  if (!overview) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400 text-center">
        暂无数据
      </div>
    );
  }

  const dist = overview.level_distribution;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
      {/* 面板标题 */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">运维快照</h3>
        <RecentSyncFailures sync={sync ?? null} />
      </div>

      {/* 健康总览行 */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* 平均健康分 */}
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-bold text-slate-800">
            {Math.round(overview.avg_score)}
          </span>
          <span className="text-xs text-slate-400">/ 100</span>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-emerald-100 text-emerald-700`}>
            优 {dist.excellent}
          </span>
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700`}>
            良 {dist.good}
          </span>
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700`}>
            警 {dist.warning}
          </span>
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700`}>
            差 {dist.poor}
          </span>
        </div>

        <span className="text-xs text-slate-400 ml-auto">
          共 {overview.total_assets} 个资产
        </span>
      </div>

      {/* 右下角面板：LowHealthList + PendingActionsList 双列布局 */}
      <div className="grid grid-cols-2 gap-3">
        <LowHealthList
          assets={overview.assets}
          onSelectAsset={(assetId) => onOpenAsset(assetId, 'health')}
        />

        {/* 待处理建议 */}
        <PendingActionsList overview={overview} />
      </div>
    </div>
  );
}
