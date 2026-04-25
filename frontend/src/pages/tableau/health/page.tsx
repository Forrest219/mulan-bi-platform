import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { listConnections, getConnectionHealthOverview } from '@/api/tableau';
import type { HealthOverview, TableauConnection } from '@/api/tableau';
import { ASSET_TYPE_LABELS } from '@/config';

const LEVEL_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  excellent: { label: '优秀', color: 'text-emerald-600', bg: 'bg-emerald-500' },
  good: { label: '良好', color: 'text-blue-600', bg: 'bg-blue-500' },
  warning: { label: '需改进', color: 'text-amber-600', bg: 'bg-amber-500' },
  poor: { label: '较差', color: 'text-red-600', bg: 'bg-red-500' },
};

const CHECK_LABELS: Record<string, string> = {
  has_description: '缺少描述',
  has_owner: '缺少所有者',
  has_datasource_link: '未关联数据源',
  fields_have_captions: '字段缺少中文名',
  is_certified: '未认证',
  naming_convention: '命名不规范',
  not_stale: '长期未更新',
};

export default function TableauHealthPage() {
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [selectedConn, setSelectedConn] = useState<number | null>(null);
  const [overview, setOverview] = useState<HealthOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [overviewLoading, setOverviewLoading] = useState(false);

  useEffect(() => {
    listConnections()
      .then(d => {
        setConnections(d.connections);
        if (d.connections.length > 0) {
          setSelectedConn(d.connections[0].id);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedConn) return;
    setOverviewLoading(true);
    getConnectionHealthOverview(selectedConn)
      .then(setOverview)
      .catch(() => setOverview(null))
      .finally(() => setOverviewLoading(false));
  }, [selectedConn]);

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-heart-pulse-line text-slate-500" />
              <h1 className="text-lg font-semibold text-slate-800">Tableau 资产健康</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">元数据完整性检查 · 资产质量评分</p>
          </div>
          {connections.length > 1 && (
            <select
              value={selectedConn || ''}
              onChange={e => setSelectedConn(Number(e.target.value))}
              className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 bg-white"
            >
              {connections.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {overviewLoading ? (
          <div className="text-center py-20 text-slate-400 text-sm">
            <i className="ri-loader-2-line animate-spin text-xl block mb-2" />
            正在评估资产健康度...
          </div>
        ) : !overview ? (
          <div className="text-center py-20 text-slate-400 text-sm">暂无数据</div>
        ) : (
          <>
            {/* Stats row */}
            <div className="grid grid-cols-4 gap-4 mb-6">
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="text-[11px] text-slate-500 mb-1">平均健康分</div>
                <div className={`text-3xl font-bold ${
                  overview.avg_score >= 80 ? 'text-emerald-600' :
                  overview.avg_score >= 60 ? 'text-amber-600' : 'text-red-600'
                }`}>{overview.avg_score}</div>
                <div className="text-[11px] text-slate-400 mt-1">{overview.connection_name}</div>
              </div>
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="text-[11px] text-slate-500 mb-1">资产总数</div>
                <div className="text-3xl font-bold text-slate-800">{overview.total_assets}</div>
              </div>
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="text-[11px] text-slate-500 mb-2">等级分布</div>
                <div className="flex items-end gap-1 h-8">
                  {['excellent', 'good', 'warning', 'poor'].map(level => {
                    const count = overview.level_distribution[level as keyof typeof overview.level_distribution];
                    const total = overview.total_assets || 1;
                    const pct = (count / total) * 100;
                    const cfg = LEVEL_CONFIG[level];
                    return (
                      <div key={level} className="flex-1 flex flex-col items-center gap-0.5">
                        <div className={`w-full rounded-t ${cfg.bg}`} style={{ height: `${Math.max(4, pct * 0.8)}px` }} />
                        <span className="text-[9px] text-slate-400">{count}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-between mt-1">
                  {['优', '良', '中', '差'].map(l => (
                    <span key={l} className="text-[9px] text-slate-400 flex-1 text-center">{l}</span>
                  ))}
                </div>
              </div>
              <div className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="text-[11px] text-slate-500 mb-2">主要问题</div>
                {overview.top_issues.length === 0 ? (
                  <div className="text-xs text-slate-400">无</div>
                ) : (
                  <div className="space-y-1.5">
                    {overview.top_issues.slice(0, 3).map(issue => (
                      <div key={issue.check} className="flex items-center justify-between">
                        <span className="text-[11px] text-slate-600">{CHECK_LABELS[issue.check] || issue.check}</span>
                        <span className="text-[11px] font-medium text-red-500">{issue.count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Asset list */}
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-100">
                <h3 className="text-[13px] font-semibold text-slate-700">
                  资产健康排名 <span className="text-slate-400 font-normal ml-1">({overview.assets.length})</span>
                </h3>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-50">
                    {['资产名称', '类型', '评分', '等级', '操作'].map(h => (
                      <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {overview.assets.map(a => {
                    const cfg = LEVEL_CONFIG[a.level] || LEVEL_CONFIG.poor;
                    return (
                      <tr key={a.asset_id} className="border-t border-slate-100 hover:bg-slate-50">
                        <td className="px-4 py-3 text-xs font-medium text-slate-700">{a.name}</td>
                        <td className="px-4 py-3">
                          <span className="text-[10px] px-1.5 py-0.5 bg-slate-100 text-slate-600 rounded">
                            {ASSET_TYPE_LABELS[a.asset_type] || a.asset_type}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-sm font-bold ${cfg.color}`}>{a.score}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                            a.level === 'excellent' ? 'bg-emerald-50 text-emerald-600' :
                            a.level === 'good' ? 'bg-blue-50 text-blue-600' :
                            a.level === 'warning' ? 'bg-amber-50 text-amber-600' :
                            'bg-red-50 text-red-600'
                          }`}>{cfg.label}</span>
                        </td>
                        <td className="px-4 py-3">
                          <Link to={`/assets/tableau/${a.asset_id}`} className="text-[11px] text-blue-600 hover:underline">
                            查看详情
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
