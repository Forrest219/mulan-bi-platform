import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import DqcTabs from '../DqcTabs';
import {
  fetchDashboard, runCycle, DqcDashboard, DIMENSION_LABELS, SIGNAL_CONFIG,
  type Dimension, type SignalLevel,
} from '../../../../api/dqc';
import { useAuth } from '../../../../context/AuthContext';

const getErrorMessage = (error: unknown, fallback = '操作失败'): string =>
  error instanceof Error ? error.message : fallback;

export default function DqcOverviewPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [dashboard, setDashboard] = useState<DqcDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [scanLoading, setScanLoading] = useState(false);
  const [scanDropdown, setScanDropdown] = useState(false);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchDashboard();
      setDashboard(data);
    } catch (e) {
      setError(getErrorMessage(e, '获取数据质量概览失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  const handleScan = async (scope: 'full' | 'hourly_light') => {
    setScanDropdown(false);
    setScanLoading(true);
    try {
      await runCycle({ scope });
      await loadDashboard();
    } catch (e) {
      setError(getErrorMessage(e, '触发扫描失败'));
    } finally {
      setScanLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-400 text-sm">加载中...</div>
      </div>
    );
  }

  const summary = dashboard?.summary;
  const signalCards: { key: SignalLevel; count: number; icon: string }[] = [
    { key: 'GREEN', count: summary?.assets_green ?? 0, icon: 'ri-checkbox-circle-line' },
    { key: 'P1', count: summary?.assets_p1 ?? 0, icon: 'ri-error-warning-line' },
    { key: 'P0', count: summary?.assets_p0 ?? 0, icon: 'ri-alarm-warning-line' },
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
            <p className="text-[13px] text-slate-400 ml-7">质量评分、信号灯与监控规则概览</p>
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
          {signalCards.map(({ key, count, icon }) => {
            const cfg = SIGNAL_CONFIG[key];
            return (
              <button
                key={key}
                onClick={() => navigate('/governance/dqc/signals', { state: { signal: key } })}
                className={`${cfg.bg} border ${cfg.border} rounded-xl p-4 text-left hover:shadow-sm transition-shadow`}
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

        {/* Middle Row: Dimension Avg + Recent Signal Changes */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {/* Dimension Average Scores */}
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

          {/* Recent Signal Changes */}
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

function formatTimeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  return `${days}天前`;
}
