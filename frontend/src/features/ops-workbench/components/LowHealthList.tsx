/**
 * LowHealthList — 待关注资产列表（健康分最低的前 3 条）
 */
import type { HealthOverview } from '../../../api/tableau';

interface LowHealthListProps {
  assets: HealthOverview['assets'];
  onSelectAsset: (assetId: string) => void;
}

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

export function LowHealthList({ assets, onSelectAsset }: LowHealthListProps) {
  const topIssues = [...assets]
    .sort((a, b) => a.score - b.score)
    .slice(0, 3);

  if (topIssues.length === 0) {
    return (
      <p className="text-xs text-slate-400 text-center py-2">
        所有资产健康状况良好
      </p>
    );
  }

  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-slate-500 mb-1">待关注资产</p>
      {topIssues.map((asset) => (
        <button
          key={asset.asset_id}
          onClick={() => onSelectAsset(String(asset.asset_id))}
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
  );
}
