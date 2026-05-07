import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import {
  getAsset, listRules, listAnalyses, listScores,
  type DqcAssetDetail, type DqcRule, type DqcLlmAnalysis, type DqcDimensionScore,
  DIMENSION_LABELS, SIGNAL_CONFIG, TRIGGER_LABELS,
  type Dimension, type SignalLevel, type LlmTrigger,
} from '../../../../api/dqc';

const getErrorMessage = (error: unknown, fallback = '操作失败'): string =>
  error instanceof Error ? error.message : fallback;

export default function DqcAssetDetailPage() {
  const { assetId } = useParams<{ assetId: string }>();
  const navigate = useNavigate();
  const id = Number(assetId);

  const [asset, setAsset] = useState<DqcAssetDetail | null>(null);
  const [rules, setRules] = useState<DqcRule[]>([]);
  const [analyses, setAnalyses] = useState<DqcLlmAnalysis[]>([]);
  const [scores, setScores] = useState<DqcDimensionScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!id || isNaN(id)) return;
    setLoading(true);
    setError('');
    try {
      const [assetData, rulesData, analysesData, scoresData] = await Promise.all([
        getAsset(id),
        listRules(id),
        listAnalyses(id, { limit: 5 }),
        listScores(id, { limit: 200 }),
      ]);
      setAsset(assetData);
      setRules(rulesData.items);
      setAnalyses(analysesData.items);
      setScores(scoresData.items);
    } catch (e) {
      setError(getErrorMessage(e, '加载资产详情失败'));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-400 text-sm">加载中...</div>
      </div>
    );
  }

  if (error || !asset) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-sm mb-3">{error || '资产不存在'}</div>
          <button onClick={() => navigate(-1)} className="text-sm text-blue-600 hover:text-blue-500">返回</button>
        </div>
      </div>
    );
  }

  const snapshot = asset.current_snapshot;
  const signalKey = (snapshot?.signal ?? asset.current_signal ?? 'GREEN') as SignalLevel;
  const signalCfg = SIGNAL_CONFIG[signalKey] ?? SIGNAL_CONFIG.GREEN;
  const confidenceScore = snapshot?.confidence_score ?? asset.current_confidence_score ?? 0;

  const trendData = (asset.recent_trend ?? []).map(t => ({
    date: t.date ? new Date(t.date).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) : '',
    score: t.confidence_score,
  }));

  const latestScoreByDim = new Map<string, DqcDimensionScore>();
  for (const s of scores) {
    if (!latestScoreByDim.has(s.dimension)) latestScoreByDim.set(s.dimension, s);
  }

  const latestAnalysis = analyses.length > 0 ? analyses[0] : null;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 mb-2">
            <i className="ri-arrow-left-line" /> 返回
          </button>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold text-slate-800">{asset.display_name || asset.table_name}</h1>
              <p className="text-[13px] text-slate-400 mt-0.5">
                {asset.datasource_name ?? `数据源 #${asset.datasource_id}`} · {asset.schema_name} · {asset.table_name}
              </p>
            </div>
            <span className={`text-[11px] font-semibold px-3 py-1 rounded-full border ${signalCfg.bg} ${signalCfg.text} ${signalCfg.border}`}>
              {signalKey} · {signalCfg.label}
            </span>
          </div>
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto space-y-6">
        {/* KPI Cards */}
        <div className="grid grid-cols-4 gap-4">
          <KpiCard label="置信分" value={Math.round(confidenceScore)} sub="/100" icon="ri-bar-chart-box-line" />
          <KpiCard
            label="当前信号"
            value={signalKey}
            sub={signalCfg.label}
            icon="ri-signal-tower-line"
            valueClass={signalCfg.text}
          />
          <KpiCard
            label="规则数"
            value={`${asset.active_rules_count} / ${asset.rules_count}`}
            sub="活跃 / 总数"
            icon="ri-list-check-3"
          />
          <KpiCard
            label="最近扫描"
            value={asset.last_computed_at ? formatTimeAgo(asset.last_computed_at) : '暂无'}
            sub=""
            icon="ri-time-line"
          />
        </div>

        {/* Dimension Scores */}
        <div className="bg-white border border-slate-200 rounded-xl p-5">
          <h3 className="text-[13px] font-semibold text-slate-700 mb-4 flex items-center gap-2">
            <i className="ri-pie-chart-line text-slate-400" />
            维度评分
          </h3>
          <div className="space-y-3">
            {(Object.entries(DIMENSION_LABELS) as [Dimension, string][]).map(([dim, label]) => {
              const dimScore = latestScoreByDim.get(dim);
              const score = dimScore?.score ?? snapshot?.dimension_scores?.[dim] ?? 0;
              const dimSignal = (dimScore?.signal ?? snapshot?.dimension_signals?.[dim] ?? 'GREEN') as SignalLevel;
              const dimCfg = SIGNAL_CONFIG[dimSignal] ?? SIGNAL_CONFIG.GREEN;
              const drift = dimScore?.drift_24h ?? null;
              const barColor = score >= 80 ? 'bg-emerald-500' : score >= 60 ? 'bg-amber-500' : 'bg-red-500';

              return (
                <div key={dim} className="flex items-center gap-3">
                  <span className="text-[12px] text-slate-600 w-14 shrink-0">{label}</span>
                  <div className="flex-1 bg-slate-100 rounded-full h-2.5">
                    <div className={`${barColor} rounded-full h-2.5 transition-all`} style={{ width: `${Math.min(score, 100)}%` }} />
                  </div>
                  <span className="text-[12px] font-medium text-slate-700 w-8 text-right">{Math.round(score)}</span>
                  <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${dimCfg.bg} ${dimCfg.text}`}>{dimSignal}</span>
                  {drift !== null && (
                    <span className={`text-[11px] w-10 text-right ${drift > 0 ? 'text-emerald-600' : drift < 0 ? 'text-red-500' : 'text-slate-400'}`}>
                      {drift > 0 ? '+' : ''}{Math.round(drift)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Confidence Score Trend */}
        {trendData.length > 1 && (
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <h3 className="text-[13px] font-semibold text-slate-700 mb-4 flex items-center gap-2">
              <i className="ri-line-chart-line text-slate-400" />
              置信分趋势
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={trendData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#94a3b8' }} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
                  formatter={(value: number) => [`${Math.round(value)} 分`, '置信分']}
                />
                <Line type="monotone" dataKey="score" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Rules Table */}
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-slate-700 flex items-center gap-2">
              <i className="ri-list-check-3 text-slate-400" />
              质量规则
              <span className="text-[11px] text-slate-400 font-normal">({rules.length})</span>
            </h3>
          </div>
          {rules.length === 0 ? (
            <div className="text-center py-10 text-[12px] text-slate-400">暂无规则</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50">
                  {['规则名称', '维度', '类型', '状态', '来源'].map(h => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rules.map(rule => (
                  <tr key={rule.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3 text-[12px] font-medium text-slate-700">{rule.name}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-600">{DIMENSION_LABELS[rule.dimension] ?? rule.dimension}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-600">{rule.rule_type}</td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${rule.is_active ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'}`}>
                        {rule.is_active ? '启用' : '停用'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {rule.is_system_suggested && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-500">AI 推荐</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Latest LLM Analysis */}
        {latestAnalysis && (
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <h3 className="text-[13px] font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <i className="ri-brain-line text-slate-400" />
              最近 LLM 分析
            </h3>
            <div className="text-[12px] text-slate-500 mb-3 flex items-center gap-3">
              <span>{latestAnalysis.created_at ? new Date(latestAnalysis.created_at).toLocaleString('zh-CN') : ''}</span>
              <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{TRIGGER_LABELS[latestAnalysis.trigger as LlmTrigger] ?? latestAnalysis.trigger}</span>
              {latestAnalysis.signal && (
                <span className={`px-1.5 py-0.5 rounded ${SIGNAL_CONFIG[latestAnalysis.signal]?.bg} ${SIGNAL_CONFIG[latestAnalysis.signal]?.text}`}>
                  {latestAnalysis.signal}
                </span>
              )}
              {latestAnalysis.confidence && (
                <span className="text-slate-400">置信度: {latestAnalysis.confidence}</span>
              )}
            </div>
            {latestAnalysis.root_cause && (
              <div className="mb-3">
                <div className="text-[11px] text-slate-400 mb-1">根因分析</div>
                <div className="text-[12px] text-slate-700 bg-slate-50 rounded-lg p-3 whitespace-pre-wrap">{latestAnalysis.root_cause}</div>
              </div>
            )}
            {latestAnalysis.fix_suggestion && (
              <div className="mb-3">
                <div className="text-[11px] text-slate-400 mb-1">修复建议</div>
                <div className="text-[12px] text-slate-700 bg-slate-50 rounded-lg p-3 whitespace-pre-wrap">{latestAnalysis.fix_suggestion}</div>
              </div>
            )}
            {latestAnalysis.fix_sql && (
              <div>
                <div className="text-[11px] text-slate-400 mb-1 flex items-center justify-between">
                  <span>修复 SQL</span>
                  <button
                    onClick={() => navigator.clipboard.writeText(latestAnalysis.fix_sql!)}
                    className="text-blue-500 hover:text-blue-600"
                  >
                    复制
                  </button>
                </div>
                <pre className="text-[12px] text-slate-700 bg-slate-900 text-slate-200 rounded-lg p-3 overflow-x-auto font-mono">{latestAnalysis.fix_sql}</pre>
              </div>
            )}
            <button
              onClick={() => navigate('/governance/dqc/analyses', { state: { assetId: id } })}
              className="mt-3 text-[12px] text-blue-600 hover:text-blue-500 flex items-center gap-1"
            >
              查看完整分析 <i className="ri-arrow-right-line" />
            </button>
          </div>
        )}
      </div>
    </div>
      </div>
  );
}

function KpiCard({ label, value, sub, icon, valueClass }: {
  label: string; value: string | number; sub: string; icon: string; valueClass?: string;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] text-slate-500">{label}</span>
        <i className={`${icon} text-slate-400`} />
      </div>
      <div className={`text-2xl font-bold ${valueClass ?? 'text-slate-800'}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-400 mt-0.5">{sub}</div>}
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
