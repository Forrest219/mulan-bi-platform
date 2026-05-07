import { useState, useEffect, useCallback } from 'react';
import DqcTabs from '../DqcTabs';
import {
  listCheckResults,
  type DqcCheckResult, type CheckStatus,
  CHECK_STATUS_CONFIG, RULE_PACKAGE_LABELS,
} from '../../../../api/dqc';


export default function DqcCheckRecordsPage() {
  const [results, setResults] = useState<DqcCheckResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterAiReady, setFilterAiReady] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params: Parameters<typeof listCheckResults>[0] = {};
      if (filterStatus) params.status = filterStatus;
      if (filterAiReady === 'true') params.affect_ai_ready = true;
      const data = await listCheckResults(params);
      setResults(data.items);
    } catch {
      setError('检查记录暂不可用，后端接口尚未接入');
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterAiReady]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-list-check text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">检查记录</p>
        </div>
      </div>
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="max-w-6xl mx-auto">
          <DqcTabs />
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
        {/* 筛选栏 */}
        <div className="flex items-center gap-3 mb-4">
          <select
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            <option value="">全部状态</option>
            <option value="PASS">通过</option>
            <option value="FAIL">失败</option>
            <option value="WARNING">警告</option>
            <option value="SKIPPED">跳过</option>
            <option value="ERROR">执行错误</option>
          </select>
          <select
            value={filterAiReady}
            onChange={e => setFilterAiReady(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            <option value="">全部记录</option>
            <option value="true">影响 AI Ready</option>
          </select>
          <span className="text-[11px] text-slate-400 ml-auto">
            共 {results.length} 条记录
          </span>
          <button
            onClick={load}
            title="刷新"
            className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-md transition-colors"
          >
            <i className="ri-refresh-line text-sm" />
          </button>
        </div>

        {/* 表格 */}
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          {error && (
            <div className="flex items-center gap-2 px-6 py-4 bg-amber-50 border-b border-amber-100">
              <i className="ri-information-line text-amber-500 text-sm" />
              <span className="text-xs text-amber-700">{error}</span>
            </div>
          )}
          <table className="w-full text-xs">
            <colgroup>
              <col className="w-[22%]" />
              <col className="w-[18%]" />
              <col className="w-[9%]" />
              <col className="w-[13%]" />
              <col className="w-[10%]" />
              <col className="w-[16%]" />
              <col className="w-[12%]" />
            </colgroup>
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">规则名</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">资产</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">规则包</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">执行时间</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">状态</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">实际值 / 阈值</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">AI Ready</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="text-center py-16 text-slate-400">
                    <i className="ri-loader-4-line animate-spin mr-2" />加载中...
                  </td>
                </tr>
              ) : results.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-16 text-slate-400">
                    <i className="ri-file-list-3-line text-3xl mb-2 block" />
                    暂无检查记录
                    {error ? '' : '，请先运行检查周期或为资产配置派生规则'}
                  </td>
                </tr>
              ) : (
                results.map(r => {
                  const sc = CHECK_STATUS_CONFIG[r.status as CheckStatus] ?? CHECK_STATUS_CONFIG.ERROR;
                  const asset = r.column_name
                    ? `${r.table_name}.${r.column_name}`
                    : r.table_name;
                  return (
                    <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3 font-medium text-slate-800 truncate">{r.rule_name}</td>
                      <td className="px-4 py-3 text-slate-600 font-mono truncate">{asset}</td>
                      <td className="px-4 py-3 text-slate-500">
                        {r.rule_package ? (RULE_PACKAGE_LABELS[r.rule_package] ?? r.rule_package) : '—'}
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {new Date(r.check_time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${sc.bg} ${sc.text}`}>
                          {sc.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-600 font-mono text-[11px]">
                        {r.actual_value !== undefined
                          ? `${(r.actual_value * 100).toFixed(2)}% / ${r.threshold_value !== undefined ? (r.threshold_value * 100).toFixed(2) + '%' : '—'}`
                          : '—'}
                      </td>
                      <td className="px-4 py-3">
                        {r.affect_ai_ready ? (
                          <span className="flex items-center gap-1 text-violet-600 text-[11px]">
                            <i className="ri-robot-line text-xs" />影响
                          </span>
                        ) : (
                          <span className="text-slate-400 text-[11px]">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
      </div>
    </div>
  );
}
