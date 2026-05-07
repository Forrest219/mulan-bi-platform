import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import DqcTabs from '../DqcTabs';
import {
  listDerivedRules, updateDerivedRule,
  type DqcDerivedRule,
} from '../../../../api/dqc';

const severityConfig: Record<string, { label: string; bg: string; text: string }> = {
  HIGH:   { label: '高', bg: 'bg-red-50',   text: 'text-red-600' },
  MEDIUM: { label: '中', bg: 'bg-amber-50', text: 'text-amber-600' },
  LOW:    { label: '低', bg: 'bg-blue-50',  text: 'text-blue-600' },
};
const ACTION_LABELS: Record<string, string> = {
  record_only: '仅记录',
  alert:       '告警',
  blocking:    '阻断',
  block_ai:    '阻断 AI',
};
const getErrorMessage = (e: unknown, fallback = '操作失败') =>
  e instanceof Error ? e.message : fallback;

export default function DqcDerivedRulesPage() {
  const navigate = useNavigate();
  const [rules, setRules] = useState<DqcDerivedRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filterTemplate, setFilterTemplate] = useState('');
  const [togglingId, setTogglingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listDerivedRules();
      setRules(data.items);
    } catch {
      setError('检查规则暂不可用，后端接口尚未接入');
      setRules([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleToggleEnabled = async (r: DqcDerivedRule) => {
    setTogglingId(r.id);
    try {
      const updated = await updateDerivedRule(r.id, { enabled: !r.enabled });
      setRules(prev => prev.map(x => x.id === r.id ? updated : x));
    } catch (e) {
      setError(getErrorMessage(e, '更新失败'));
    } finally {
      setTogglingId(null);
    }
  };

  const templateNames = [...new Set(rules.map(r => r.template_name))].sort();
  const displayed = filterTemplate
    ? rules.filter(r => r.template_name === filterTemplate)
    : rules;

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-list-check text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">数据质量监控</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">检查规则</p>
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
            value={filterTemplate}
            onChange={e => setFilterTemplate(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            <option value="">全部来源模板</option>
            {templateNames.map(n => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <span className="text-[11px] text-slate-400 ml-auto">
            共 {displayed.length} 条规则
          </span>
          <button
            onClick={load}
            title="刷新"
            className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-md transition-colors"
          >
            <i className="ri-refresh-line text-sm" />
          </button>
        </div>

        {/* 提示 */}
        {!loading && !error && rules.length === 0 && (
          <div className="flex items-start gap-3 p-4 bg-blue-50 border border-blue-100 rounded-xl mb-4">
            <i className="ri-lightbulb-line text-blue-500 text-sm mt-0.5" />
            <div>
              <p className="text-xs font-medium text-blue-800 mb-0.5">如何生成检查规则？</p>
              <p className="text-[11px] text-blue-600">
                前往
                <button
                  onClick={() => navigate('/governance/dqc/templates')}
                  className="underline mx-1 hover:text-blue-800"
                >规则模板</button>
                页，点击模板行的"广播"图标，系统将扫描匹配资产并批量生成派生规则。
              </p>
            </div>
          </div>
        )}

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
              <col className="w-[16%]" />
              <col className="w-[18%]" />
              <col className="w-[8%]" />
              <col className="w-[10%]" />
              <col className="w-[9%]" />
              <col className="w-[8%]" />
              <col className="w-[9%]" />
            </colgroup>
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">规则名</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">来源模板</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">绑定资产</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">级别</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">执行策略</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">来源</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">启用</th>
                <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="text-center py-16 text-slate-400">
                    <i className="ri-loader-4-line animate-spin mr-2" />加载中...
                  </td>
                </tr>
              ) : displayed.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-16 text-slate-400">
                    <i className="ri-node-tree text-3xl mb-2 block" />
                    暂无检查规则
                  </td>
                </tr>
              ) : (
                displayed.map(r => {
                  const sv = severityConfig[r.severity?.toUpperCase()] ?? severityConfig.MEDIUM;
                  const asset = r.column_name ? `${r.table_name}.${r.column_name}` : r.table_name;
                  const generatedByLabel = r.generated_by === 'system' ? '自动' : r.generated_by === 'ai' ? 'AI' : '手动';
                  return (
                    <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3 font-medium text-slate-800 truncate">{r.rule_name}</td>
                      <td className="px-4 py-3 text-slate-500 truncate">{r.template_name}</td>
                      <td className="px-4 py-3 text-slate-600 font-mono text-[11px] truncate">{asset}</td>
                      <td className="px-4 py-3">
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${sv.bg} ${sv.text}`}>
                          {sv.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {ACTION_LABELS[r.action] ?? r.action}
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-[11px]">{generatedByLabel}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleToggleEnabled(r)}
                          disabled={togglingId === r.id}
                          title={r.enabled ? '点击禁用' : '点击启用'}
                          className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50"
                          style={{ backgroundColor: r.enabled ? '#1e293b' : '#cbd5e1' }}
                        >
                          <span
                            className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${
                              r.enabled ? 'translate-x-4' : 'translate-x-1'
                            }`}
                          />
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 text-slate-400">
                          <button
                            title="查看检查记录"
                            onClick={() => navigate(`/governance/dqc/check-records?rule_id=${r.id}`)}
                            className="hover:text-slate-700 transition-colors"
                          >
                            <i className="ri-bar-chart-line text-sm" />
                          </button>
                        </div>
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
