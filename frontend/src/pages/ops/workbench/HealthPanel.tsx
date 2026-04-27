/**
 * HealthPanel -- 健康模式面板
 *
 * 右侧内容区：健康概览仪表板
 * 显示健康总览、低分资产、同步状态
 */
import { useEffect, useState } from 'react';
import { useScope } from '../../home/context/ScopeContext';
import {
  getConnectionHealthOverview,
  getSyncStatus,
  type HealthOverview,
} from '../../../api/tableau';

export interface HealthPanelProps {
  /** 点击资产时打开抽屉 */
  onOpenAsset?: (assetId: string, tab?: string) => void;
}

/** 健康等级 -> Tailwind 颜色类 */
function levelColor(level: string): string {
  switch (level) {
    case 'excellent': return 'bg-emerald-100 text-emerald-700';
    case 'good':      return 'bg-blue-100 text-blue-700';
    case 'warning':   return 'bg-amber-100 text-amber-700';
    case 'poor':      return 'bg-red-100 text-red-700';
    default:          return 'bg-slate-100 text-slate-500';
  }
}

function levelLabel(level: string): string {
  switch (level) {
    case 'excellent': return '优';
    case 'good':      return '良';
    case 'warning':   return '警';
    case 'poor':      return '差';
    default:          return level;
  }
}

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

interface SyncState {
  last_sync_at: string | null;
  status: string;
}

type SeverityFilter = 'all' | 'poor' | 'warning' | 'good' | 'excellent';

export function HealthPanel({ onOpenAsset }: HealthPanelProps) {
  const { connectionId } = useScope();

  const [overview, setOverview] = useState<HealthOverview | null>(null);
  const [sync, setSync] = useState<SyncState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');

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

  // -- 未选择连接 --
  if (!connectionId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400">
        <i className="ri-heart-pulse-line text-4xl mb-3" />
        <p className="text-sm">请先在顶部选择连接</p>
        <p className="text-xs mt-1">选择连接后可查看健康概览</p>
      </div>
    );
  }

  // -- 加载中 --
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
        <i className="ri-loader-4-line animate-spin mr-2" />
        加载健康数据...
      </div>
    );
  }

  // -- 错误 / 无数据 --
  if (error || !overview) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400">
        <i className="ri-error-warning-line text-3xl mb-3" />
        <p className="text-sm">健康数据加载失败</p>
        <p className="text-xs mt-1">请检查连接状态后重试</p>
      </div>
    );
  }

  const dist = overview.level_distribution;

  // 过滤资产列表
  const filteredAssets = [...overview.assets]
    .filter(a => severityFilter === 'all' || a.level === severityFilter)
    .sort((a, b) => a.score - b.score);

  const severityOptions: { key: SeverityFilter; label: string; count: number }[] = [
    { key: 'all', label: '全部', count: overview.total_assets },
    { key: 'poor', label: '差', count: dist.poor },
    { key: 'warning', label: '警', count: dist.warning },
    { key: 'good', label: '良', count: dist.good },
    { key: 'excellent', label: '优', count: dist.excellent },
  ];

  return (
    <div className="h-full overflow-y-auto px-6 py-5 space-y-6">
      {/* 健康概览卡片 */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <i className="ri-heart-pulse-line text-blue-500" />
            健康概览
          </h3>
          {sync?.last_sync_at && (
            <span className="text-xs text-slate-400">
              最后同步：{timeAgo(sync.last_sync_at)}
            </span>
          )}
        </div>

        {/* 平均分 + 分布 */}
        <div className="flex items-center gap-6 mb-4">
          <div className="flex items-baseline gap-1.5">
            <span className="text-4xl font-bold text-slate-800">
              {Math.round(overview.avg_score)}
            </span>
            <span className="text-sm text-slate-400">/ 100</span>
          </div>
          <div className="flex-1 grid grid-cols-4 gap-3">
            {([
              { key: 'excellent', label: '优', count: dist.excellent, color: 'bg-emerald-500' },
              { key: 'good', label: '良', count: dist.good, color: 'bg-blue-500' },
              { key: 'warning', label: '警', count: dist.warning, color: 'bg-amber-500' },
              { key: 'poor', label: '差', count: dist.poor, color: 'bg-red-500' },
            ] as const).map(item => (
              <div key={item.key} className="text-center">
                <div className="text-lg font-semibold text-slate-700">{item.count}</div>
                <div className="flex items-center justify-center gap-1 text-xs text-slate-400">
                  <span className={`w-2 h-2 rounded-full ${item.color}`} />
                  {item.label}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="text-xs text-slate-400">
          共 {overview.total_assets} 个资产
        </div>
      </div>

      {/* 严重度筛选 */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500 mr-1">筛选</span>
        {severityOptions.map(opt => (
          <button
            key={opt.key}
            onClick={() => setSeverityFilter(opt.key)}
            className={`px-3 py-1 text-xs rounded-full transition-colors ${
              severityFilter === opt.key
                ? 'bg-slate-800 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {opt.label} ({opt.count})
          </button>
        ))}
      </div>

      {/* 资产列表 */}
      <div className="rounded-xl border border-slate-200 bg-white divide-y divide-slate-100">
        {filteredAssets.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-slate-400">
            {severityFilter === 'all' ? '暂无资产数据' : '没有匹配的资产'}
          </div>
        )}
        {filteredAssets.map(asset => (
          <button
            key={asset.asset_id}
            onClick={() => onOpenAsset?.(String(asset.asset_id), 'health')}
            className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors group"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm text-slate-700 truncate group-hover:text-blue-600 transition-colors">
                {asset.name}
              </p>
              <p className="text-xs text-slate-400 truncate">{asset.asset_type}</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${levelColor(asset.level)}`}>
                {levelLabel(asset.level)}
              </span>
              <span className="text-sm font-mono text-slate-500 w-8 text-right">
                {asset.score}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
