import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import DqcTabs from '../DqcTabs';
import {
  fetchDashboard, runCycle, listAssets,
  type DqcDashboard, type DqcAsset,
  DIMENSION_LABELS, SIGNAL_CONFIG,
  type Dimension, type SignalLevel,
} from '../../../../api/dqc';
import { useAuth } from '../../../../context/AuthContext';

type FilterSignal = 'ALL' | SignalLevel;

const getErrorMessage = (error: unknown, fallback = '操作失败'): string =>
  error instanceof Error ? error.message : fallback;

export default function DqcOverviewPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [dashboard, setDashboard] = useState<DqcDashboard | null>(null);
  const [assets, setAssets] = useState<DqcAsset[]>([]);
  const [filter, setFilter] = useState<FilterSignal>('ALL');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [scanLoading, setScanLoading] = useState(false);
  const [scanDropdown, setScanDropdown] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [dashRes, assetsRes] = await Promise.all([
        fetchDashboard(),
        listAssets({ page: 1, page_size: 200 }),
      ]);
      setDashboard(dashRes);
      setAssets(assetsRes.items);
    } catch (e) {
      setError(getErrorMessage(e, '加载健康看板失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleScan = async (scope: 'full' | 'hourly_light') => {
    setScanDropdown(false);
    setScanLoading(true);
    try {
      await runCycle({ scope });
      await loadData();
    } catch (e) {
      setError(getErrorMessage(e, '触发扫描失败'));
    } finally {
      setScanLoading(false);
    }
  };

  const summary = dashboard?.summary;

  const signalCounts: Record<string, number> = {
    ALL: assets.length,
    P0: summary?.assets_p0 ?? assets.filter(a => a.current_signal === 'P0').length,
    P1: summary?.assets_p1 ?? assets.filter(a => a.current_signal === 'P1').length,
    GREEN: summary?.assets_green ?? assets.filter(a => (a.current_signal ?? 'GREEN') === 'GREEN').length,
  };

  const filteredAssets = assets.filter(a => {
    const signal = a.current_signal ?? 'GREEN';
    if (filter !== 'ALL' && signal !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!(a.display_name || a.table_name).toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const signalGroups: { key: SignalLevel; items: DqcAsset[] }[] = (
    [
      { key: 'P0' as const, items: filteredAssets.filter(a => (a.current_signal ?? 'GREEN') === 'P0') },
      { key: 'P1' as const, items: filteredAssets.filter(a => (a.current_signal ?? 'GREEN') === 'P1') },
      { key: 'GREEN' as const, items: filteredAssets.filter(a => (a.current_signal ?? 'GREEN') === 'GREEN') },
    ] as const
  ).filter(g => filter === 'ALL' ? g.items.length > 0 : g.key === filter);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-400 text-sm">加载中...</div>
      </div>
    );
  }

  const kpiSignalCards: { key: SignalLevel; icon: string }[] = [
    { key: 'GREEN', icon: 'ri-checkbox-circle-line' },
    { key: 'P1', icon: 'ri-error-warning-line' },
    { key: 'P0', icon: 'ri-alarm-warning-line' },
  ];

  const filterButtons: { key: FilterSignal; label: string }[] = [
    { key: 'P0', label: 'P0 严重' },
    { key: 'P1', label: 'P1 需关注' },
    { key: 'GREEN', label: 'GREEN 正常' },
    { key: 'ALL', label: '全部' },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-dashboard-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">数据资产质量检查 · 规则驱动问题发现</p>
          </div>
          {isAdmin && (
            <div className="relative">
              <button
                onClick={() => setScanDropdown(!scanDropdown)}
                disabled={scanLoading}
                className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors disabled:opacity-50"
              >
                {scanLoading ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-play-line" />}
                执行扫描
                <i className="ri-arrow-down-s-line" />
              </button>
              {scanDropdown && (
                <div className="absolute right-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg z-10 py-1 w-36">
                  <button onClick={() => handleScan('full')} className="w-full text-left px-3 py-2 text-[12px] text-slate-700 hover:bg-slate-50">全量扫描</button>
                  <button onClick={() => handleScan('hourly_light')} className="w-full text-left px-3 py-2 text-[12px] text-slate-700 hover:bg-slate-50">轻量扫描</button>
                </div>
              )}
            </div>
          )}
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

        {/* KPI Cards */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-white border border-slate-200 rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] text-slate-500">监控资产</span>
              <i className="ri-database-2-line text-slate-400" />
            </div>
            <div className="text-2xl font-bold text-slate-800">{summary?.total_assets ?? 0}</div>
            <div className="text-[11px] text-slate-400 mt-0.5">总监控表数</div>
          </div>
          {kpiSignalCards.map(({ key, icon }) => {
            const cfg = SIGNAL_CONFIG[key];
            const count = signalCounts[key] ?? 0;
            const isActive = filter === key;
            return (
              <button
                key={key}
                onClick={() => setFilter(isActive ? 'ALL' : key)}
                className={`${cfg.bg} border rounded-xl p-4 text-left hover:shadow-sm transition-all ${
                  isActive ? `${cfg.border} ring-2 ring-offset-1 ring-current` : cfg.border
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-[11px] ${cfg.text}`}>{key}</span>
                  <i className={`${icon} ${cfg.text}`} />
                </div>
                <div className={`text-2xl font-bold ${cfg.text}`}>{count}</div>
                <div className={`text-[11px] ${cfg.text} opacity-70 mt-0.5`}>{cfg.label}</div>
              </button>
            );
          })}
        </div>

        {/* Signal View */}
        {assets.length > 0 && (
          <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
            {/* Filter bar */}
            <div className="flex items-center gap-3 mb-5 flex-wrap">
              {filterButtons.map(({ key, label }) => {
                const active = filter === key;
                const cfg = key !== 'ALL' ? SIGNAL_CONFIG[key] : null;
                return (
                  <button
                    key={key}
                    onClick={() => setFilter(key)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors ${
                      active
                        ? cfg ? `${cfg.bg} ${cfg.text} ${cfg.border}` : 'bg-slate-800 text-white border-slate-800'
                        : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    {cfg && <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />}
                    {label}
                    <span className={`text-[11px] ${active ? 'opacity-80' : 'text-slate-400'}`}>
                      ({signalCounts[key] ?? 0})
                    </span>
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
                  className="pl-9 pr-3 py-1.5 text-[12px] border border-slate-200 rounded-lg w-44 focus:outline-none focus:border-blue-400"
                />
              </div>
            </div>

            {/* Signal groups */}
            {filteredAssets.length === 0 ? (
              <div className="text-center py-8 text-[12px] text-slate-400">无匹配资产</div>
            ) : (
              <div className="space-y-5">
                {signalGroups.map(({ key, items }) => {
                  const cfg = SIGNAL_CONFIG[key];
                  return (
                    <div key={key}>
                      <div className="flex items-center gap-2 mb-2.5">
                        <span className={`w-2.5 h-2.5 rounded-full ${cfg.dot}`} />
                        <span className={`text-[12px] font-semibold ${cfg.text}`}>{key} {cfg.label}</span>
                        <span className="text-[11px] text-slate-400">({items.length})</span>
                      </div>
                      <div className="grid grid-cols-4 gap-2.5">
                        {items
                          .sort((a, b) => (a.current_confidence_score ?? 100) - (b.current_confidence_score ?? 100))
                          .slice(0, 8)
                          .map(asset => (
                            <SignalCard
                              key={asset.id}
                              asset={asset}
                              signalKey={key}
                              onDetail={() => navigate(`/governance/dqc/assets/${asset.id}`)}
                            />
                          ))}
                        {items.length > 8 && (
                          <button
                            className="border border-dashed border-slate-200 rounded-xl p-3 text-[11px] text-slate-400 hover:bg-slate-50 flex items-center justify-center"
                            onClick={() => setFilter(key)}
                          >
                            还有 {items.length - 8} 个
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Middle Row: Dimension Avg + Recent Signal Changes */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <h3 className="text-[13px] font-semibold text-slate-700 mb-4 flex items-center gap-2">
              <i className="ri-bar-chart-horizontal-line text-slate-400" />
              维度平均分
            </h3>
            <div className="space-y-3">
              {(Object.entries(DIMENSION_LABELS) as [Dimension, string][]).map(([dim, label]) => {
                const score = dashboard?.dimension_avg?.[dim] ?? 0;
                const barColor = score >= 80 ? 'bg-emerald-500' : score >= 60 ? 'bg-amber-500' : 'bg-red-500';
                return (
                  <div key={dim} className="flex items-center gap-3">
                    <span className="text-[12px] text-slate-600 w-14 shrink-0">{label}</span>
                    <div className="flex-1 bg-slate-100 rounded-full h-2">
                      <div className={`${barColor} rounded-full h-2 transition-all`} style={{ width: `${score}%` }} />
                    </div>
                    <span className="text-[12px] font-medium text-slate-700 w-8 text-right">{Math.round(score)}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <h3 className="text-[13px] font-semibold text-slate-700 mb-4 flex items-center gap-2">
              <i className="ri-exchange-line text-slate-400" />
              最近信号变更
            </h3>
            {(!dashboard?.recent_signal_changes?.length) ? (
              <div className="text-center py-6 text-[12px] text-slate-400">暂无信号变更</div>
            ) : (
              <div className="space-y-2">
                {dashboard.recent_signal_changes.slice(0, 6).map((change, i) => {
                  const prevCfg = SIGNAL_CONFIG[change.prev_signal as SignalLevel];
                  const currCfg = SIGNAL_CONFIG[change.current_signal as SignalLevel];
                  return (
                    <button
                      key={i}
                      onClick={() => navigate(`/governance/dqc/assets/${change.asset_id}`)}
                      className="w-full flex items-center justify-between p-2.5 rounded-lg hover:bg-slate-50 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-[12px] font-medium text-slate-700 truncate max-w-[140px]">{change.display_name}</span>
                        <div className="flex items-center gap-1 text-[11px]">
                          <span className={prevCfg?.text ?? 'text-slate-400'}>{change.prev_signal}</span>
                          <i className="ri-arrow-right-line text-slate-300 text-[10px]" />
                          <span className={currCfg?.text ?? 'text-slate-400'}>{change.current_signal}</span>
                        </div>
                      </div>
                      <span className="text-[11px] text-slate-400">{formatTimeAgo(change.changed_at)}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Top Failing Assets */}
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
            <i className="ri-error-warning-line text-red-400" />
            <h3 className="text-[13px] font-semibold text-slate-700">质量最差资产</h3>
          </div>
          {(!dashboard?.top_failing_assets?.length) ? (
            <div className="text-center py-10 text-[12px] text-slate-400">
              <i className="ri-shield-check-line text-3xl text-emerald-300 block mb-2" />
              所有资产质量正常
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50">
                  {['资产名称', '信号', '置信分', '最差维度', '操作'].map(h => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dashboard.top_failing_assets.map(asset => {
                  const cfg = SIGNAL_CONFIG[asset.signal as SignalLevel];
                  const dimLabel = DIMENSION_LABELS[asset.top_failed_dimension as Dimension] ?? asset.top_failed_dimension;
                  return (
                    <tr key={asset.asset_id} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-4 py-3 text-[12px] font-medium text-slate-700">{asset.display_name}</td>
                      <td className="px-4 py-3">
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${cfg?.bg} ${cfg?.text} ${cfg?.border}`}>
                          {asset.signal}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[12px] font-medium text-slate-700">{Math.round(asset.confidence_score)}</td>
                      <td className="px-4 py-3 text-[12px] text-slate-600">{dimLabel}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => navigate(`/governance/dqc/assets/${asset.asset_id}`)}
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
          )}
        </div>
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
      className={`${cfg.bg} border ${cfg.border} rounded-xl p-3 text-left hover:shadow-sm transition-shadow`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] font-medium text-slate-700 truncate max-w-[120px]">{asset.display_name || asset.table_name}</span>
        <span className={`w-2 h-2 rounded-full ${cfg.dot} shrink-0`} />
      </div>
      <div className="text-[10px] text-slate-400 mb-1.5 truncate">{asset.datasource_name ?? `数据源 #${asset.datasource_id}`}</div>
      <div className={`text-base font-bold ${cfg.text} mb-1`}>置信分 {Math.round(score)}</div>
      {worstDims.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {worstDims.map(([dim, v]) => (
            <span key={dim} className="text-[9px] text-slate-500 bg-white/60 rounded px-1 py-0.5">
              {DIMENSION_LABELS[dim as Dimension] ?? dim} {Math.round(v.score!)}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

function formatTimeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  return `${days}天前`;
}
