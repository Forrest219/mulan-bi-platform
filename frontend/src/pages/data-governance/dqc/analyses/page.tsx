import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  listAssets, listAnalyses,
  type DqcAsset, type DqcLlmAnalysis,
  SIGNAL_CONFIG, TRIGGER_LABELS,
  type SignalLevel, type LlmTrigger,
} from '../../../../api/dqc';

const getErrorMessage = (error: unknown, fallback = '操作失败'): string =>
  error instanceof Error ? error.message : fallback;

interface AnalysisRow extends DqcLlmAnalysis {
  asset_name: string;
}

export default function DqcAnalysesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const presetAssetId = (location.state as { assetId?: number })?.assetId;

  const [assets, setAssets] = useState<DqcAsset[]>([]);
  const [analyses, setAnalyses] = useState<AnalysisRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const [filterAssetId, setFilterAssetId] = useState<number | 'all'>(presetAssetId ?? 'all');
  const [filterTrigger, setFilterTrigger] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('all');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const assetsRes = await listAssets({ page: 1, page_size: 200 });
      setAssets(assetsRes.items);

      const targetAssets = filterAssetId === 'all'
        ? assetsRes.items
        : assetsRes.items.filter(a => a.id === filterAssetId);

      const results = await Promise.all(
        targetAssets.map(async (asset) => {
          try {
            const res = await listAnalyses(asset.id, {
              trigger: filterTrigger !== 'all' ? filterTrigger : undefined,
              limit: 20,
            });
            return res.items.map(item => ({
              ...item,
              asset_name: asset.display_name || asset.table_name,
            }));
          } catch {
            return [];
          }
        })
      );

      const all = results.flat().sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
        return tb - ta;
      });

      setAnalyses(all);
    } catch (e) {
      setError(getErrorMessage(e, '加载分析数据失败'));
    } finally {
      setLoading(false);
    }
  }, [filterAssetId, filterTrigger]);

  useEffect(() => { loadData(); }, [loadData]);

  const displayed = analyses.filter(a => {
    if (filterStatus !== 'all' && a.status !== filterStatus) return false;
    return true;
  });

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
            <i className="ri-brain-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">LLM 根因分析</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">基于大语言模型的数据质量根因分析</p>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {error && (
          <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-600"><i className="ri-close-line" /></button>
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-3 mb-6 flex-wrap">
          <select
            value={filterAssetId === 'all' ? 'all' : filterAssetId}
            onChange={e => setFilterAssetId(e.target.value === 'all' ? 'all' : Number(e.target.value))}
            className="text-[12px] border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none focus:border-blue-400"
          >
            <option value="all">全部资产</option>
            {assets.map(a => (
              <option key={a.id} value={a.id}>{a.display_name || a.table_name}</option>
            ))}
          </select>
          <select
            value={filterTrigger}
            onChange={e => setFilterTrigger(e.target.value)}
            className="text-[12px] border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none focus:border-blue-400"
          >
            <option value="all">全部触发类型</option>
            {(Object.entries(TRIGGER_LABELS) as [LlmTrigger, string][]).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <select
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
            className="text-[12px] border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none focus:border-blue-400"
          >
            <option value="all">全部状态</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
            <option value="pending">等待中</option>
            <option value="running">执行中</option>
          </select>
          <span className="text-[11px] text-slate-400 ml-auto">共 {displayed.length} 条</span>
        </div>

        {/* Table + Accordion */}
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          {displayed.length === 0 ? (
            <div className="text-center py-16 text-[12px] text-slate-400">
              <i className="ri-brain-line text-3xl text-slate-300 block mb-2" />
              暂无分析记录
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50">
                  {['时间', '资产', '触发原因', '信号', '置信度', '状态'].map(h => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayed.map(item => {
                  const isExpanded = expandedId === item.id;
                  const signalCfg = item.signal ? SIGNAL_CONFIG[item.signal] : null;
                  return (
                    <AnalysisRowView
                      key={item.id}
                      item={item}
                      isExpanded={isExpanded}
                      signalCfg={signalCfg}
                      onToggle={() => setExpandedId(isExpanded ? null : item.id)}
                      onNavigateAsset={() => navigate(`/governance/dqc/assets/${item.asset_id}`)}
                    />
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function AnalysisRowView({ item, isExpanded, signalCfg, onToggle, onNavigateAsset }: {
  item: AnalysisRow;
  isExpanded: boolean;
  signalCfg: { bg: string; text: string; border: string } | null;
  onToggle: () => void;
  onNavigateAsset: () => void;
}) {
  const statusMap: Record<string, { label: string; cls: string }> = {
    completed: { label: '已完成', cls: 'bg-emerald-50 text-emerald-600' },
    failed: { label: '失败', cls: 'bg-red-50 text-red-600' },
    pending: { label: '等待中', cls: 'bg-slate-100 text-slate-500' },
    running: { label: '执行中', cls: 'bg-blue-50 text-blue-600' },
  };
  const st = statusMap[item.status] ?? { label: item.status, cls: 'bg-slate-100 text-slate-500' };

  return (
    <>
      <tr
        onClick={onToggle}
        className={`border-t border-slate-100 cursor-pointer transition-colors ${isExpanded ? 'bg-slate-50' : 'hover:bg-slate-50'}`}
      >
        <td className="px-4 py-3 text-[12px] text-slate-500">
          {item.created_at ? new Date(item.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '--'}
        </td>
        <td className="px-4 py-3 text-[12px] font-medium text-slate-700">{item.asset_name}</td>
        <td className="px-4 py-3 text-[12px] text-slate-600">{TRIGGER_LABELS[item.trigger as LlmTrigger] ?? item.trigger}</td>
        <td className="px-4 py-3">
          {signalCfg ? (
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${signalCfg.bg} ${signalCfg.text} ${signalCfg.border}`}>
              {item.signal}
            </span>
          ) : <span className="text-slate-300">--</span>}
        </td>
        <td className="px-4 py-3 text-[12px] text-slate-600">{item.confidence ?? '--'}</td>
        <td className="px-4 py-3">
          <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${st.cls}`}>{st.label}</span>
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={6} className="bg-slate-50 px-6 py-5 border-t border-slate-100">
            <div className="max-w-3xl space-y-4">
              {/* Meta */}
              <div className="flex items-center gap-4 text-[11px] text-slate-500">
                <button onClick={onNavigateAsset} className="text-blue-600 hover:text-blue-500 flex items-center gap-1">
                  <i className="ri-external-link-line" /> 查看资产
                </button>
                {item.prompt_tokens != null && (
                  <span>Token: prompt {item.prompt_tokens} / completion {item.completion_tokens}</span>
                )}
                {item.latency_ms != null && (
                  <span>耗时 {(item.latency_ms / 1000).toFixed(1)}s</span>
                )}
              </div>

              {item.status === 'failed' && item.error_message && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                  <div className="text-[11px] text-red-400 mb-1">错误信息</div>
                  <div className="text-[12px] text-red-700">{item.error_message}</div>
                </div>
              )}

              {item.root_cause && (
                <div>
                  <div className="text-[11px] text-slate-400 mb-1 flex items-center gap-1">
                    <i className="ri-search-eye-line" /> 根因分析
                  </div>
                  <div className="text-[12px] text-slate-700 bg-white rounded-lg border border-slate-200 p-3 whitespace-pre-wrap">{item.root_cause}</div>
                </div>
              )}

              {item.fix_suggestion && (
                <div>
                  <div className="text-[11px] text-slate-400 mb-1 flex items-center gap-1">
                    <i className="ri-tools-line" /> 修复建议
                  </div>
                  <div className="text-[12px] text-slate-700 bg-white rounded-lg border border-slate-200 p-3 whitespace-pre-wrap">{item.fix_suggestion}</div>
                </div>
              )}

              {item.fix_sql && (
                <div>
                  <div className="text-[11px] text-slate-400 mb-1 flex items-center justify-between">
                    <span className="flex items-center gap-1"><i className="ri-code-s-slash-line" /> 修复 SQL</span>
                    <button
                      onClick={() => navigator.clipboard.writeText(item.fix_sql!)}
                      className="text-blue-500 hover:text-blue-600 flex items-center gap-0.5"
                    >
                      <i className="ri-file-copy-line" /> 复制
                    </button>
                  </div>
                  <pre className="text-[12px] bg-slate-900 text-slate-200 rounded-lg p-3 overflow-x-auto font-mono">{item.fix_sql}</pre>
                </div>
              )}

              {item.suggested_rules && Array.isArray(item.suggested_rules) && item.suggested_rules.length > 0 && (
                <div>
                  <div className="text-[11px] text-slate-400 mb-1 flex items-center gap-1">
                    <i className="ri-lightbulb-line" /> 建议规则 ({item.suggested_rules.length})
                  </div>
                  <div className="text-[12px] text-slate-600 bg-white rounded-lg border border-slate-200 p-3">
                    {item.suggested_rules.map((r, i) => (
                      <div key={i} className="py-1">{JSON.stringify(r)}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
