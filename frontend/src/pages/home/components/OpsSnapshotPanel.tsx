/**
 * OpsSnapshotPanel — 首页 idle 态运维快照面板（Phase 3 T8）
 *
 * 展示当前连接的健康总览与最后同步时间。
 * 数据来源：
 *   - getConnectionHealthOverview(connId) — 健康总览
 *   - getSyncStatus(connId)              — 同步状态
 */
import { useEffect, useState } from 'react';
import { useScope } from '../context/ScopeContext';
import {
  getConnectionHealthOverview,
  getSyncStatus,
  type HealthOverview,
} from '../../../api/tableau';

interface OpsSnapshotPanelProps {
  /** 点击问题资产时打开抽屉 */
  onOpenAsset: (assetId: string, tab?: string) => void;
}

interface SyncState {
  last_sync_at: string | null;
  status: string;
}

/** 将 ISO 时间转成"X 分钟前 / X 小时前 / X 天前" */
function timeAgo(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
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

/** 健康等级 → 中文标签 */
function levelLabel(level: string): string {
  switch (level) {
    case 'excellent': return '优';
    case 'good':      return '良';
    case 'warning':   return '警';
    case 'poor':      return '差';
    default:          return level;
  }
}

export function OpsSnapshotPanel({ onOpenAsset }: OpsSnapshotPanelProps) {
  const { connectionId } = useScope();

  const [overview, setOverview] = useState<HealthOverview | null>(null);
  const [sync, setSync] = useState<SyncState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!connectionId) return;

    const connId = Number(connectionId);
    setLoading(true);
    setError(false);

    Promise.all([
      getConnectionHealthOverview(connId),
      getSyncStatus(connId),
    ])
      .then(([ov, sy]) => {
        setOverview(ov);
        setSync({ last_sync_at: sy.last_sync_at, status: sy.status });
      })
      .catch(() => {
        setError(true);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [connectionId]);

  // ── 降级：未选择连接 ────────────────────────────────────────────────────
  if (!connectionId) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400 text-center">
        请先选择连接
      </div>
    );
  }

  // ── 加载中 ───────────────────────────────────────────────────────────────
  if (loading) {
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
  if (error || !overview) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400 text-center">
        暂无数据
      </div>
    );
  }

  // ── Top Issues：取健康分最低的前 3 条资产 ────────────────────────────────
  const topIssues = [...overview.assets]
    .sort((a, b) => a.score - b.score)
    .slice(0, 3);

  const dist = overview.level_distribution;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
      {/* 面板标题 */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">运维快照</h3>
        {sync?.last_sync_at && (
          <span className="text-xs text-slate-400">
            最后同步：{timeAgo(sync.last_sync_at)}
          </span>
        )}
        {!sync?.last_sync_at && (
          <span className="text-xs text-slate-400">暂无同步记录</span>
        )}
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

      {/* Top Issues 列表 */}
      {topIssues.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-slate-500 mb-1">待关注资产</p>
          {topIssues.map((asset) => (
            <button
              key={asset.asset_id}
              onClick={() => onOpenAsset(String(asset.asset_id), 'health')}
              className="w-full flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-left hover:bg-slate-50 transition-colors group"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-700 truncate group-hover:text-blue-600 transition-colors">
                  {asset.name}
                </p>
                <p className="text-xs text-slate-400 truncate">{asset.asset_type}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${levelColor(asset.level)}`}>
                  {levelLabel(asset.level)}
                </span>
                <span className="text-xs font-mono text-slate-500 w-6 text-right">
                  {asset.score}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      {topIssues.length === 0 && (
        <p className="text-xs text-slate-400 text-center py-2">所有资产健康状况良好</p>
      )}
    </div>
  );
}
