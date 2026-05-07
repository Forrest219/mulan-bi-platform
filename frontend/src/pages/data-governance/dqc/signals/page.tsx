import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import DqcTabs from '../DqcTabs';
import {
  listAssets, fetchDashboard,
  type DqcAsset, type DqcDashboard,
  SIGNAL_CONFIG, DIMENSION_LABELS,
  type SignalLevel, type Dimension,
} from '../../../../api/dqc';

type FilterSignal = 'ALL' | SignalLevel;

const getErrorMessage = (error: unknown, fallback = '操作失败'): string =>
  error instanceof Error ? error.message : fallback;

export default function DqcSignalsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const presetSignal = (location.state as { signal?: string })?.signal as FilterSignal | undefined;

  const [filter, setFilter] = useState<FilterSignal>(presetSignal ?? 'ALL');
  const [assets, setAssets] = useState<DqcAsset[]>([]);
  const [dashboard, setDashboard] = useState<DqcDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [assetsRes, dashRes] = await Promise.all([
        listAssets({ page: 1, page_size: 200 }),
        fetchDashboard(),
      ]);
      setAssets(assetsRes.items);
      setDashboard(dashRes);
    } catch (e) {
      setError(getErrorMessage(e, '加载信号灯数据失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const filtered = assets.filter(a => {
    const signal = a.current_signal ?? 'GREEN';
    if (filter !== 'ALL' && signal !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      const name = (a.display_name || a.table_name).toLowerCase();
      if (!name.includes(q)) return false;
    }
    return true;
  });

  const groups: { key: SignalLevel; items: DqcAsset[] }[] = ([
    { key: 'P0' as const, items: filtered.filter(a => (a.current_signal ?? 'GREEN') === 'P0') },
    { key: 'P1' as const, items: filtered.filter(a => (a.current_signal ?? 'GREEN') === 'P1') },
    { key: 'GREEN' as const, items: filtered.filter(a => (a.current_signal ?? 'GREEN') === 'GREEN') },
  ] as const).filter(g => filter === 'ALL' || g.key === filter);

  const signalCounts: Record<string, number> = {
    ALL: assets.length,
    P0: dashboard?.summary?.assets_p0 ?? assets.filter(a => a.current_signal === 'P0').length,
    P1: dashboard?.summary?.assets_p1 ?? assets.filter(a => a.current_signal === 'P1').length,
    GREEN: dashboard?.summary?.assets_green ?? assets.filter(a => (a.current_signal ?? 'GREEN') === 'GREEN').length,
  };

  const filterButtons: { key: FilterSignal; label: string }[] = [
    { key: 'P0', label: 'P0 严重' },
    { key: 'P1', label: 'P1 需关注' },
    { key: 'GREEN', label: 'GREEN 正常' },
    { key: 'ALL', label: '全部' },
  ];

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-400 text-sm">加载中...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-signal-tower-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">数据质量状态可视化与告警信号</p>
        </div>
      </div>
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto">
          <DqcTabs />
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto">
        {error && (
          <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-600"><i className="ri-close-line" /></button>
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-3 mb-6 flex-wrap">
          {filterButtons.map(({ key, label }) => {
            const active = filter === key;
            const cfg = key !== 'ALL' ? SIGNAL_CONFIG[key] : null;
            return (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[12px] font-medium border transition-colors ${
                  active
                    ? cfg ? `${cfg.bg} ${cfg.text} ${cfg.border}` : 'bg-slate-800 text-white border-slate-800'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}
              >
                {cfg && <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />}
                {label}
                <span className={`text-[11px] ${active ? 'opacity-80' : 'text-slate-400'}`}>({signalCounts[key] ?? 0})</span>
              </button>
            );
          })}
          <div className="flex-1" />
          <div className="relative">
            <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="搜索资产..."
              className="pl-9 pr-3 py-2 text-[12px] border border-slate-200 rounded-lg w-48 focus:outline-none focus:border-blue-400"
            />
          </div>
        </div>

        {/* Signal Groups */}
        <div className="space-y-6">
          {groups.map(({ key, items }) => {
            const cfg = SIGNAL_CONFIG[key];
            if (items.length === 0 && filter === 'ALL') return null;
            return (
              <div key={key}>
                <div className="flex items-center gap-2 mb-3">
                  <span className={`w-2.5 h-2.5 rounded-full ${cfg.dot}`} />
                  <span className={`text-[13px] font-semibold ${cfg.text}`}>{key} {cfg.label}</span>
                  <span className="text-[11px] text-slate-400">({items.length})</span>
                </div>
                {items.length === 0 ? (
                  <div className="text-center py-8 text-[12px] text-slate-400 bg-white border border-slate-200 rounded-xl">
                    无匹配资产
                  </div>
                ) : (
                  <div className="grid grid-cols-3 gap-3">
                    {items
                      .sort((a, b) => (a.current_confidence_score ?? 100) - (b.current_confidence_score ?? 100))
                      .map(asset => (
                        <SignalCard key={asset.id} asset={asset} signalKey={key} onDetail={() => navigate(`/governance/dqc/assets/${asset.id}`)} />
                      ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Recent Signal Changes */}
        {dashboard?.recent_signal_changes && dashboard.recent_signal_changes.length > 0 && (
          <div className="mt-8 bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
              <i className="ri-exchange-line text-slate-400" />
              <h3 className="text-[13px] font-semibold text-slate-700">最近信号变更</h3>
            </div>
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50">
                  {['时间', '资产', '变更', '操作'].map(h => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dashboard.recent_signal_changes.map((change, i) => {
                  const prevCfg = SIGNAL_CONFIG[change.prev_signal as SignalLevel];
                  const currCfg = SIGNAL_CONFIG[change.current_signal as SignalLevel];
                  return (
                    <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-4 py-3 text-[12px] text-slate-500">
                        {change.changed_at ? new Date(change.changed_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-medium text-slate-700">{change.display_name}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1 text-[11px]">
                          <span className={prevCfg?.text ?? 'text-slate-400'}>{change.prev_signal}</span>
                          <i className="ri-arrow-right-line text-slate-300 text-[10px]" />
                          <span className={currCfg?.text ?? 'text-slate-400'}>{change.current_signal}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => navigate(`/governance/dqc/assets/${change.asset_id}`)}
                          className="text-[12px] text-blue-600 hover:text-blue-500"
                        >
                          详情
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
      </div>
  );
}

function SignalCard({ asset, signalKey, onDetail }: { asset: DqcAsset; signalKey: SignalLevel; onDetail: () => void }) {
  const cfg = SIGNAL_CONFIG[signalKey];
  const score = asset.current_confidence_score ?? 0;
  const snapshot = asset.dimension_snapshot;

  const worstDims = snapshot
    ? (Object.entries(snapshot) as [string, { score: number | null }][])
        .filter(([, v]) => v.score !== null && v.score < 70)
        .sort((a, b) => (a[1].score ?? 100) - (b[1].score ?? 100))
        .slice(0, 2)
    : [];

  return (
    <button
      onClick={onDetail}
      className={`${cfg.bg} border ${cfg.border} rounded-xl p-4 text-left hover:shadow-sm transition-shadow`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[12px] font-medium text-slate-700 truncate max-w-[160px]">{asset.display_name || asset.table_name}</span>
        <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
      </div>
      <div className="text-[11px] text-slate-400 mb-2 truncate">{asset.datasource_name ?? `数据源 #${asset.datasource_id}`}</div>
      <div className={`text-lg font-bold ${cfg.text} mb-1`}>置信分 {Math.round(score)}</div>
      {worstDims.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {worstDims.map(([dim, v]) => (
            <span key={dim} className="text-[10px] text-slate-500 bg-white/60 rounded px-1.5 py-0.5">
              {DIMENSION_LABELS[dim as Dimension] ?? dim} {Math.round(v.score!)}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}
