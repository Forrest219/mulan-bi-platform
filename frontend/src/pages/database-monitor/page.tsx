import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { mockDataSources, mockQualityMetrics, monitorStats, DataSource } from '../../mocks/databaseMonitorData';

const statusConfig = {
  connected: { label: 'Connected', dot: 'bg-emerald-500', text: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  warning: { label: 'Warning', dot: 'bg-amber-500', text: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200' },
  error: { label: 'Error', dot: 'bg-red-500', text: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200' },
};

function ScoreBar({ score }: { score: number }) {
  const color = score >= 90 ? 'bg-emerald-500' : score >= 75 ? 'bg-amber-400' : 'bg-red-500';
  const textColor = score >= 90 ? 'text-emerald-600' : score >= 75 ? 'text-amber-600' : 'text-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className={`text-[11px] font-semibold w-7 text-right ${textColor}`}>{score}</span>
    </div>
  );
}

export default function DatabaseMonitorPage() {
  const navigate = useNavigate();
  const [selectedDs, setSelectedDs] = useState<DataSource | null>(null);
  const [activeTab, setActiveTab] = useState<'sources' | 'quality'>('sources');

  const filteredMetrics = selectedDs
    ? mockQualityMetrics.filter((m) => m.datasource === selectedDs.name)
    : mockQualityMetrics;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="w-5 h-5 flex items-center justify-center">
                <i className="ri-database-2-line text-slate-500 text-base" />
              </span>
              <h1 className="text-lg font-semibold text-slate-800">数据库监控</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">数据源连接状态 · 质量指标监控</p>
          </div>
          <button
            onClick={() => navigate('/datasources')}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors cursor-pointer whitespace-nowrap"
          >
            <i className="ri-add-line" />
            添加数据源
          </button>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {/* Stats row */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { label: '数据源总数', value: mockDataSources.length, icon: 'ri-server-line', sub: `${mockDataSources.filter((d) => d.status === 'connected').length} 正常连接` },
            { label: '监控表数量', value: monitorStats.totalTables, icon: 'ri-table-line', sub: '跨 4 个数据库' },
            { label: '平均质量评分', value: monitorStats.avgScore, icon: 'ri-award-line', sub: '高风险表 7 个' },
            { label: '最近扫描', value: '09:15', icon: 'ri-time-line', sub: '今日 2026-03-25' },
          ].map((s) => (
            <div key={s.label} className="bg-white border border-slate-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] text-slate-500">{s.label}</span>
                <div className="w-6 h-6 flex items-center justify-center">
                  <i className={`${s.icon} text-slate-400`} />
                </div>
              </div>
              <div className="text-2xl font-bold text-slate-800">{s.value}</div>
              <div className="text-[11px] text-slate-400 mt-0.5">{s.sub}</div>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 px-1 py-1 bg-slate-100 rounded-lg w-fit mb-5">
          {[
            { key: 'sources', label: '数据源管理' },
            { key: 'quality', label: '质量指标' },
          ].map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key as 'sources' | 'quality')}
              className={`px-4 py-1.5 rounded-md text-[12px] font-medium transition-colors cursor-pointer whitespace-nowrap ${
                activeTab === t.key ? 'bg-white text-slate-800' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {activeTab === 'sources' && (
          <div className="grid grid-cols-2 gap-4">
            {mockDataSources.map((ds) => {
              const sc = statusConfig[ds.status];
              const isSelected = selectedDs?.id === ds.id;
              return (
                <div
                  key={ds.id}
                  onClick={() => setSelectedDs(isSelected ? null : ds)}
                  className={`bg-white border rounded-xl p-5 cursor-pointer transition-all ${
                    isSelected ? 'border-slate-400 ring-1 ring-slate-300' : 'border-slate-200 hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 flex items-center justify-center bg-slate-100 rounded-lg">
                        <i className="ri-database-line text-slate-600" />
                      </div>
                      <div>
                        <div className="text-[13px] font-semibold text-slate-800">{ds.name}</div>
                        <div className="text-[11px] text-slate-400">{ds.host}</div>
                      </div>
                    </div>
                    <span className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${sc.bg} ${sc.text} ${sc.border} whitespace-nowrap`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${sc.dot}`} />
                      {sc.label}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[11px]">
                    <div>
                      <div className="text-slate-400">Type</div>
                      <div className="font-medium text-slate-700 mt-0.5">{ds.type}</div>
                    </div>
                    <div>
                      <div className="text-slate-400">Database</div>
                      <div className="font-medium text-slate-700 mt-0.5 font-mono">{ds.database}</div>
                    </div>
                    <div>
                      <div className="text-slate-400">Tables</div>
                      <div className="font-medium text-slate-700 mt-0.5">{ds.tableCount}</div>
                    </div>
                  </div>
                  <div className="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400">
                    <span>最近扫描：{ds.lastScan}</span>
                    {ds.status !== 'error' && (
                      <button
                        onClick={(e) => e.stopPropagation()}
                        className="text-slate-500 hover:text-slate-800 cursor-pointer flex items-center gap-1"
                      >
                        <i className="ri-refresh-line" />
                        重新扫描
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {activeTab === 'quality' && (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-[13px] font-semibold text-slate-700">质量指标详情</h3>
              {selectedDs && (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-slate-500">筛选：{selectedDs.name}</span>
                  <button onClick={() => setSelectedDs(null)} className="text-slate-400 hover:text-slate-600 cursor-pointer">
                    <i className="ri-close-line text-sm" />
                  </button>
                </div>
              )}
            </div>
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50">
                  {['数据源', '表名', '空值率', '重复率', '异常率', '质量评分', '趋势'].map((h) => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredMetrics.map((m, i) => (
                  <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3 text-[12px] text-slate-500 font-mono">{m.datasource}</td>
                    <td className="px-4 py-3 text-[12px] font-semibold text-slate-700 font-mono">{m.table}</td>
                    <td className="px-4 py-3">
                      <span className={`text-[12px] font-medium ${m.nullRate > 15 ? 'text-red-500' : m.nullRate > 5 ? 'text-amber-500' : 'text-slate-600'}`}>
                        {m.nullRate}%
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[12px] font-medium ${m.duplicateRate > 1 ? 'text-amber-500' : 'text-slate-600'}`}>
                        {m.duplicateRate}%
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[12px] font-medium ${m.invalidRate > 3 ? 'text-red-500' : 'text-slate-600'}`}>
                        {m.invalidRate}%
                      </span>
                    </td>
                    <td className="px-4 py-3 w-36">
                      <ScoreBar score={m.score} />
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-sm ${m.trend === 'up' ? 'text-emerald-500' : m.trend === 'down' ? 'text-red-400' : 'text-slate-400'}`}>
                        {m.trend === 'up' ? <i className="ri-arrow-up-line" /> : m.trend === 'down' ? <i className="ri-arrow-down-line" /> : <i className="ri-subtract-line" />}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
