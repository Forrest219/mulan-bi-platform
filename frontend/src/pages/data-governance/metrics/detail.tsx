import { useState, useEffect, useCallback, useMemo, lazy, Suspense } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getMetricDetail,
  getMetricLineage,
  listConsistencyChecks,
  listMetricAnomalies,
  resolveLineage,
  getActiveMaintenanceWindow,
  MetricDetail,
  LineageRecord,
  ConsistencyCheckResult,
  AnomalyRecord,
} from '../../../api/metrics';
import { useHelpAgentSelection } from '../../agents/help-agent/helpAgentContext';

const FormulaTemplatePreview = lazy(() =>
  import('./components/FormulaTemplatePreview').then(m => ({ default: m.default }))
);
import { useAuth } from '../../../context/AuthContext';

// ---------------------------------------------------------------------------
// 常量映射
// ---------------------------------------------------------------------------

const METRIC_TYPE_LABEL: Record<string, string> = {
  atomic: '原子',
  derived: '派生',
  ratio: '比率',
};

const METRIC_TYPE_BADGE: Record<string, string> = {
  atomic: 'bg-blue-50 text-blue-600',
  derived: 'bg-purple-50 text-purple-600',
  ratio: 'bg-orange-50 text-orange-600',
};

const SENSITIVITY_LABEL: Record<string, string> = {
  public: '公开',
  internal: '内部',
  confidential: '机密',
  restricted: '高度机密',
};

const LINEAGE_STATUS_LABEL: Record<string, string> = {
  unknown: '未解析',
  resolved: '已解析',
  manual: '手动录入',
};

const LINEAGE_STATUS_BADGE: Record<string, string> = {
  unknown: 'bg-slate-100 text-slate-500',
  resolved: 'bg-emerald-50 text-emerald-600',
  manual: 'bg-blue-50 text-blue-600',
};

const RELATIONSHIP_LABEL: Record<string, string> = {
  source: '直接来源',
  upstream_joined: '上游关联',
  upstream_calculated: '上游计算',
};

const CHECK_STATUS_BADGE: Record<string, string> = {
  pass: 'bg-emerald-50 text-emerald-600',
  warning: 'bg-yellow-50 text-yellow-600',
  fail: 'bg-red-50 text-red-600',
};

const CHECK_STATUS_LABEL: Record<string, string> = {
  pass: '通过',
  warning: '警告',
  fail: '失败',
};

const ANOMALY_STATUS_BADGE: Record<string, string> = {
  detected: 'bg-red-50 text-red-600',
  investigating: 'bg-yellow-50 text-yellow-600',
  resolved: 'bg-emerald-50 text-emerald-600',
  false_positive: 'bg-slate-100 text-slate-500',
};

const ANOMALY_STATUS_LABEL: Record<string, string> = {
  detected: '已检测',
  investigating: '排查中',
  resolved: '已解决',
  false_positive: '误报',
};

const ALERT_STATUS_BADGE: Record<string, string> = {
  sent: 'bg-emerald-50 text-emerald-600',
  pending: 'bg-yellow-50 text-yellow-600',
};

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return iso.slice(0, 19).replace('T', ' ');
  } catch {
    return '—';
  }
}

function getErrorMessage(error: unknown, fallback = '操作失败'): string {
  return error instanceof Error ? error.message : fallback;
}

function metricDisplayName(metric: Pick<MetricDetail, 'metric_code' | 'name' | 'name_zh'>): string {
  return metric.name_zh || metric.name || metric.metric_code || '未命名指标';
}

function stringifyJson(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

type TabKey = 'info' | 'lineage' | 'consistency' | 'anomalies';

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function MetricDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { isAdmin, isDataAdmin } = useAuth();
  const canManageMetrics = isAdmin || isDataAdmin;
  const helpAgentSelection = useMemo(
    () => ({
      primary_entity: {
        type: 'metric',
        id: String(id),
        source: 'route' as const,
      },
    }),
    [id]
  );

  useHelpAgentSelection(helpAgentSelection);

  const [activeTab, setActiveTab] = useState<TabKey>('info');
  const [metric, setMetric] = useState<MetricDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Lineage
  const [lineageRecords, setLineageRecords] = useState<LineageRecord[]>([]);
  const [lineageStatus, setLineageStatus] = useState('');
  const [lineageLoading, setLineageLoading] = useState(false);
  const [resolvingLineage, setResolvingLineage] = useState(false);

  // Consistency
  const [consistencyItems, setConsistencyItems] = useState<ConsistencyCheckResult[]>([]);
  const [consistencyTotal, setConsistencyTotal] = useState(0);
  const [consistencyLoading, setConsistencyLoading] = useState(false);

  // Anomalies
  const [anomalyItems, setAnomalyItems] = useState<AnomalyRecord[]>([]);
  const [anomalyTotal, setAnomalyTotal] = useState(0);
  const [anomalyLoading, setAnomalyLoading] = useState(false);

  // ── fetch metric detail ──
  const fetchDetail = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError('');
    try {
      const data = await getMetricDetail(id);
      setMetric(data);
    } catch (e) {
      setError(getErrorMessage(e, '获取指标详情失败'));
    } finally {
      setLoading(false);
    }
  }, [id]);

  // ── fetch lineage ──
  const fetchLineage = useCallback(async () => {
    if (!id) return;
    setLineageLoading(true);
    try {
      const data = await getMetricLineage(id);
      setLineageRecords(data.records);
      setLineageStatus(data.lineage_status);
    } catch (e) {
      setError(getErrorMessage(e, '获取血缘信息失败'));
    } finally {
      setLineageLoading(false);
    }
  }, [id]);

  // ── fetch consistency checks ──
  const fetchConsistency = useCallback(async () => {
    if (!id) return;
    setConsistencyLoading(true);
    try {
      const data = await listConsistencyChecks({ metric_id: id, page: 1, page_size: 50 });
      setConsistencyItems(data.items);
      setConsistencyTotal(data.total);
    } catch (e) {
      setError(getErrorMessage(e, '获取一致性校验记录失败'));
    } finally {
      setConsistencyLoading(false);
    }
  }, [id]);

  // ── fetch anomalies ──
  const fetchAnomalies = useCallback(async () => {
    if (!id) return;
    setAnomalyLoading(true);
    try {
      const data = await listMetricAnomalies(id, { page: 1, page_size: 50 });
      setAnomalyItems(data.items);
      setAnomalyTotal(data.total);
    } catch (e) {
      setError(getErrorMessage(e, '获取异常记录失败'));
    } finally {
      setAnomalyLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  useEffect(() => {
    if (activeTab === 'lineage') fetchLineage();
    if (activeTab === 'consistency') fetchConsistency();
    if (activeTab === 'anomalies') fetchAnomalies();
  }, [activeTab, fetchLineage, fetchConsistency, fetchAnomalies]);

  // ── trigger lineage resolve ──
  const handleResolveLineage = async () => {
    if (!id) return;
    setResolvingLineage(true);
    try {
      await resolveLineage(id, false);
      await fetchLineage();
      await fetchDetail();
    } catch (e) {
      setError(getErrorMessage(e, '触发血缘解析失败'));
    } finally {
      setResolvingLineage(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <span className="text-slate-400">加载中...</span>
      </div>
    );
  }

  if (error && !metric) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 mb-4">{error}</p>
          <Link to="/governance/metrics" className="text-blue-600 hover:underline text-sm">
            返回指标列表
          </Link>
        </div>
      </div>
    );
  }

  if (!metric) return null;

  const TABS: { key: TabKey; label: string; icon: string }[] = [
    { key: 'info', label: '基本信息', icon: 'ri-information-line' },
    { key: 'lineage', label: '指标血缘', icon: 'ri-git-merge-line' },
    { key: 'consistency', label: '一致性校验', icon: 'ri-scales-3-line' },
    { key: 'anomalies', label: '异常检测', icon: 'ri-alarm-warning-line' },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          {/* Breadcrumb */}
          <div className="flex items-center gap-1.5 text-[12px] text-slate-400 mb-3">
            <Link to="/governance/metrics" className="hover:text-slate-600">指标治理</Link>
            <span>/</span>
            <span className="text-slate-600">{metricDisplayName(metric)}</span>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-lg font-semibold text-slate-800">{metricDisplayName(metric)}</h1>
                <span className={`text-[11px] font-medium px-2 py-0.5 rounded ${METRIC_TYPE_BADGE[metric.metric_type] || 'bg-slate-100 text-slate-600'}`}>
                  {METRIC_TYPE_LABEL[metric.metric_type] || metric.metric_type}
                </span>
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${metric.is_active ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'}`}>
                  {metric.is_active ? '已发布' : '草稿'}
                </span>
              </div>
              <p className="text-[13px] text-slate-500 mt-1">
                {metric.metric_code || '未编号'}{metric.name ? ` · ${metric.name}` : ''}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
        {/* Error banner */}
        {error && (
          <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError('')} className="text-slate-400 hover:text-slate-600 cursor-pointer">x</button>
          </div>
        )}

        {/* Tabs */}
        <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1 mb-6 w-fit">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-4 py-2 text-[13px] rounded-md transition-colors cursor-pointer ${
                activeTab === tab.key
                  ? 'bg-white text-slate-700 shadow-sm font-medium'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              <i className={tab.icon} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {activeTab === 'info' && <InfoTab metric={metric} />}
        {activeTab === 'lineage' && (
          <LineageTab
            records={lineageRecords}
            status={lineageStatus}
            loading={lineageLoading}
            resolving={resolvingLineage}
            isDataAdmin={canManageMetrics}
            onResolve={handleResolveLineage}
          />
        )}
        {activeTab === 'consistency' && (
          <ConsistencyTab items={consistencyItems} total={consistencyTotal} loading={consistencyLoading} />
        )}
        {activeTab === 'anomalies' && (
          <AnomaliesTabWithMw items={anomalyItems} total={anomalyTotal} loading={anomalyLoading} />
        )}
      </div>
      </div>
    </div>
  );
}

// =============================================================================
// Tab: 基本信息
// =============================================================================

function InfoTab({ metric }: { metric: MetricDetail }) {
  const activeBindings = metric.bindings?.filter((binding) => binding.is_active) || [];
  const fields: { label: string; value: string | number | null | undefined; mono?: boolean }[] = [
    { label: '指标编号', value: metric.metric_code, mono: true },
    { label: '指标中文名', value: metric.name_zh },
    { label: '指标英文名', value: metric.name, mono: true },
    { label: '指标类型', value: METRIC_TYPE_LABEL[metric.metric_type] || metric.metric_type },
    { label: '业务域', value: metric.business_domain },
    { label: 'Primary Tableau 连接', value: metric.primary_binding?.tableau_connection_id ?? metric.tableau_connection_id },
    { label: 'Primary Tableau 资产', value: metric.primary_binding?.tableau_asset_id ?? metric.tableau_asset_id },
    { label: 'Primary Datasource LUID', value: metric.primary_binding?.tableau_datasource_luid ?? metric.tableau_datasource_luid, mono: true },
    { label: 'Active Binding 数', value: activeBindings.length || undefined },
    { label: '旧数据源 ID', value: metric.datasource_id },
    { label: '旧数据表', value: metric.table_name, mono: true },
    { label: '旧字段', value: metric.column_name, mono: true },
    { label: '聚合方式', value: metric.metric_type === 'ratio' ? '—' : metric.aggregation_type },
    { label: '结果类型', value: metric.result_type },
    { label: '单位', value: metric.unit },
    { label: '精度', value: metric.precision },
    { label: '可查询', value: metric.queryable == null ? undefined : metric.queryable ? '是' : '否' },
    { label: '敏感级别', value: SENSITIVITY_LABEL[metric.sensitivity_level] || metric.sensitivity_level },
    { label: '血缘状态', value: LINEAGE_STATUS_LABEL[metric.lineage_status] || metric.lineage_status },
    { label: '创建时间', value: formatDate(metric.created_at) },
    { label: '更新时间', value: formatDate(metric.updated_at) },
    { label: '发布时间', value: formatDate(metric.published_at) },
  ];

  return (
    <div className="space-y-6">
      {/* Metadata grid */}
      <div className="bg-white border border-slate-200 rounded-xl p-6">
        <h3 className="text-[14px] font-semibold text-slate-700 mb-4">元数据</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {fields.map((f) => (
            <div key={f.label}>
              <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide mb-1">{f.label}</div>
              <div className={`text-[13px] text-slate-700 ${f.mono ? 'font-mono' : ''}`}>
                {f.value ?? '—'}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Description */}
      {metric.description && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h3 className="text-[14px] font-semibold text-slate-700 mb-3">描述</h3>
          <p className="text-[13px] text-slate-600 whitespace-pre-wrap">{metric.description}</p>
        </div>
      )}

      {/* Formula */}
      {metric.formula && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h3 className="text-[14px] font-semibold text-slate-700 mb-3">计算公式</h3>
          <pre className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-[13px] text-slate-700 font-mono overflow-x-auto">
            {metric.formula}
          </pre>
        </div>
      )}

      {metric.dependencies && metric.dependencies.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h3 className="text-[14px] font-semibold text-slate-700 mb-3">指标依赖</h3>
          <div className="space-y-2">
            {metric.dependencies.map((dep) => (
              <div key={`${dep.depends_on_metric_id}-${dep.dependency_role}`} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 text-[13px]">
                <span className="text-slate-700">{dep.name_zh || dep.name || dep.metric_code || dep.depends_on_metric_id}</span>
                <span className="text-[11px] text-slate-500 bg-slate-100 rounded px-2 py-0.5">{dep.dependency_role}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {(activeBindings.length > 0 || metric.field_mappings || metric.required_base_metrics?.length || metric.formula_expression) && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h3 className="text-[14px] font-semibold text-slate-700 mb-3">执行绑定</h3>
          {activeBindings.length > 0 && (
            <div className="overflow-x-auto mb-4">
              <table className="min-w-full text-[12px]">
                <thead>
                  <tr className="border-b border-slate-100 text-slate-500">
                    <th className="text-left font-medium py-2 pr-4">角色</th>
                    <th className="text-left font-medium py-2 pr-4">连接</th>
                    <th className="text-left font-medium py-2 pr-4">资产</th>
                    <th className="text-left font-medium py-2 pr-4">Datasource LUID</th>
                    <th className="text-left font-medium py-2">字段映射</th>
                  </tr>
                </thead>
                <tbody>
                  {activeBindings.map((binding) => (
                    <tr key={binding.id || `${binding.tableau_connection_id}-${binding.tableau_datasource_luid}`} className="border-b border-slate-50">
                      <td className="py-2 pr-4">
                        <span className={`px-2 py-0.5 rounded text-[11px] ${binding.is_primary ? 'bg-blue-50 text-blue-600' : 'bg-slate-100 text-slate-500'}`}>
                          {binding.is_primary ? 'Primary' : 'Secondary'}
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-slate-700">{binding.tableau_connection_id ?? '—'}</td>
                      <td className="py-2 pr-4 text-slate-700">{binding.tableau_asset_id ?? '—'}</td>
                      <td className="py-2 pr-4 text-slate-700 font-mono">{binding.tableau_datasource_luid ?? '—'}</td>
                      <td className="py-2 text-slate-700 font-mono">{binding.field_mappings ? stringifyJson(binding.field_mappings) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {metric.field_mappings && (
            <pre className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-[13px] text-slate-700 font-mono overflow-x-auto mb-3">
              {stringifyJson(metric.field_mappings)}
            </pre>
          )}
          {metric.required_base_metrics && metric.required_base_metrics.length > 0 && (
            <div className="mb-3 text-[13px] text-slate-600">
              依赖基础指标：{metric.required_base_metrics.join('、')}
            </div>
          )}
          {metric.formula_expression && (
            <pre className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-[13px] text-slate-700 font-mono overflow-x-auto">
              {stringifyJson(metric.formula_expression)}
            </pre>
          )}
        </div>
      )}

      {metric.binding_errors && metric.binding_errors.length > 0 && (
        <div className="bg-white border border-red-100 rounded-xl p-6">
          <h3 className="text-[14px] font-semibold text-red-700 mb-3">绑定错误</h3>
          <pre className="bg-red-50 border border-red-100 rounded-lg p-4 text-[13px] text-red-700 font-mono overflow-x-auto">
            {stringifyJson(metric.binding_errors)}
          </pre>
        </div>
      )}

      {/* Filters */}
      {metric.filters && Object.keys(metric.filters).length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h3 className="text-[14px] font-semibold text-slate-700 mb-3">过滤条件</h3>
          <pre className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-[13px] text-slate-700 font-mono overflow-x-auto">
            {JSON.stringify(metric.filters, null, 2)}
          </pre>
        </div>
      )}

      {/* Formula Template Preview */}
      <Suspense fallback={null}>
        <FormulaTemplatePreview
          formulaTemplate={metric.formula_template}
          filters={metric.filters}
        />
      </Suspense>
    </div>
  );
}

// =============================================================================
// Tab: 血缘
// =============================================================================

function LineageTab({
  records,
  status,
  loading,
  resolving,
  isDataAdmin,
  onResolve,
}: {
  records: LineageRecord[];
  status: string;
  loading: boolean;
  resolving: boolean;
  isDataAdmin: boolean;
  onResolve: () => void;
}) {
  if (loading) {
    return <div className="text-center py-20 text-slate-400">加载血缘数据中...</div>;
  }

  // Group records by table
  const tableMap = new Map<string, LineageRecord[]>();
  for (const r of records) {
    const key = r.table_name;
    if (!tableMap.has(key)) tableMap.set(key, []);
    tableMap.get(key)!.push(r);
  }

  return (
    <div className="space-y-6">
      {/* Status bar */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[13px] text-slate-600">血缘状态：</span>
          <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${LINEAGE_STATUS_BADGE[status] || 'bg-slate-100 text-slate-500'}`}>
            {LINEAGE_STATUS_LABEL[status] || status}
          </span>
          <span className="text-[12px] text-slate-400">
            {records.length} 条血缘记录
          </span>
        </div>
        {isDataAdmin && (
          <button
            onClick={onResolve}
            disabled={resolving}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-500 cursor-pointer disabled:opacity-50"
          >
            <i className={resolving ? 'ri-loader-4-line animate-spin' : 'ri-refresh-line'} />
            {resolving ? '解析中...' : '触发血缘解析'}
          </button>
        )}
      </div>

      {records.length === 0 ? (
        <div className="text-center py-16">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
            <i className="ri-git-merge-line text-2xl text-slate-400" />
          </div>
          <p className="text-slate-500 mb-2">暂无血缘记录</p>
          <p className="text-[12px] text-slate-400">请点击「触发血缘解析」自动分析公式依赖</p>
        </div>
      ) : (
        <>
          {/* Lineage graph (simplified tree) */}
          <div className="bg-white border border-slate-200 rounded-xl p-6">
            <h3 className="text-[14px] font-semibold text-slate-700 mb-4">血缘关系图</h3>
            <div className="flex items-start gap-8 overflow-x-auto pb-4">
              {/* Source tables */}
              <div className="flex flex-col gap-3 min-w-[200px]">
                <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide mb-1">上游依赖</div>
                {Array.from(tableMap.entries()).map(([tableName, cols]) => (
                  <div key={tableName} className="bg-slate-50 border border-slate-200 rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <i className="ri-table-line text-slate-500" />
                      <span className="text-[13px] font-semibold text-slate-700 font-mono">{tableName}</span>
                    </div>
                    <div className="space-y-1">
                      {cols.map((col) => (
                        <div key={col.id} className="flex items-center gap-2 text-[12px]">
                          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                          <span className="text-slate-600 font-mono">{col.column_name}</span>
                          {col.column_type && (
                            <span className="text-slate-400 text-[10px]">({col.column_type})</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              {/* Arrow */}
              <div className="flex flex-col items-center justify-center py-8">
                <div className="w-16 h-0.5 bg-slate-300" />
                <i className="ri-arrow-right-s-line text-slate-400 text-xl -mt-2.5" />
              </div>

              {/* Current metric */}
              <div className="min-w-[200px]">
                <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide mb-2">当前指标</div>
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <i className="ri-bar-chart-grouped-line text-blue-600" />
                    <span className="text-[13px] font-semibold text-blue-700">{records.length > 0 ? '当前指标' : ''}</span>
                  </div>
                  <div className="text-[12px] text-blue-600">
                    依赖 {tableMap.size} 个表，{records.length} 个字段
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Lineage detail table */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-6 py-3 border-b border-slate-100">
              <h3 className="text-[14px] font-semibold text-slate-700">血缘详细记录</h3>
            </div>
            <table className="min-w-full text-sm">
              <thead>
                <tr className="bg-slate-50">
                  {['数据表', '字段', '字段类型', '关系类型', '跳数', '转换逻辑'].map((h) => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">{r.table_name}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">{r.column_name}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-500">{r.column_type || '—'}</td>
                    <td className="px-4 py-3">
                      <span className="text-[11px] font-medium px-2 py-0.5 rounded bg-slate-100 text-slate-600">
                        {RELATIONSHIP_LABEL[r.relationship_type] || r.relationship_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-slate-500 text-center">{r.hop_number}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-500 max-w-[200px] truncate" title={r.transformation_logic || ''}>
                      {r.transformation_logic || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// =============================================================================
// Tab: 一致性校验
// =============================================================================

function ConsistencyTab({
  items,
  total,
  loading,
}: {
  items: ConsistencyCheckResult[];
  total: number;
  loading: boolean;
}) {
  if (loading) {
    return <div className="text-center py-20 text-slate-400">加载一致性校验数据中...</div>;
  }

  if (items.length === 0) {
    return (
      <div className="text-center py-16">
        <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
          <i className="ri-scales-3-line text-2xl text-slate-400" />
        </div>
        <p className="text-slate-500 mb-2">暂无一致性校验记录</p>
        <p className="text-[12px] text-slate-400">可通过 API 触发跨数据源一致性校验</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="text-[13px] text-slate-500">共 {total} 条校验记录</div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-slate-50">
              {['校验时间', '数据源 A', '数据源 B', '值 A', '值 B', '差值', '差异百分比', '容差', '状态'].map((h) => (
                <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 text-[12px] text-slate-500">{formatDate(c.checked_at)}</td>
                <td className="px-4 py-3 text-[12px] text-slate-600 font-mono">DS-{c.datasource_id_a}</td>
                <td className="px-4 py-3 text-[12px] text-slate-600 font-mono">DS-{c.datasource_id_b}</td>
                <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">{c.value_a?.toFixed(2) ?? '—'}</td>
                <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">{c.value_b?.toFixed(2) ?? '—'}</td>
                <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">{c.difference?.toFixed(2) ?? '—'}</td>
                <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">
                  {c.difference_pct != null ? `${c.difference_pct.toFixed(2)}%` : '—'}
                </td>
                <td className="px-4 py-3 text-[12px] text-slate-500">{c.tolerance_pct}%</td>
                <td className="px-4 py-3">
                  <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${CHECK_STATUS_BADGE[c.check_status] || 'bg-slate-100 text-slate-500'}`}>
                    {CHECK_STATUS_LABEL[c.check_status] || c.check_status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// =============================================================================
// Tab: 异常检测
// =============================================================================

function AnomaliesTab({
  items,
  total,
  loading,
}: {
  items: AnomalyRecord[];
  total: number;
  loading: boolean;
}) {
  if (loading) {
    return <div className="text-center py-20 text-slate-400">加载异常记录中...</div>;
  }

  if (items.length === 0) {
    return (
      <div className="text-center py-16">
        <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
          <i className="ri-alarm-warning-line text-2xl text-slate-400" />
        </div>
        <p className="text-slate-500 mb-2">暂无异常记录</p>
        <p className="text-[12px] text-slate-400">可通过 API 触发批量异常检测</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="text-[13px] text-slate-500">共 {total} 条异常记录</div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-slate-50">
              {['检测时间', '检测方法', '实际值', '期望值', '偏差分数', '阈值', '状态', '告警状态', '处理备注'].map((h) => (
                <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 text-[12px] text-slate-500">{formatDate(a.detected_at)}</td>
                <td className="px-4 py-3 text-[12px] text-slate-600">{a.detection_method}</td>
                <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">{a.metric_value.toFixed(2)}</td>
                <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">{a.expected_value.toFixed(2)}</td>
                <td className="px-4 py-3 text-[12px] text-slate-700 font-mono">{a.deviation_score.toFixed(2)}</td>
                <td className="px-4 py-3 text-[12px] text-slate-500 font-mono">{a.deviation_threshold.toFixed(2)}</td>
                <td className="px-4 py-3">
                  <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${ANOMALY_STATUS_BADGE[a.status] || 'bg-slate-100 text-slate-500'}`}>
                    {ANOMALY_STATUS_LABEL[a.status] || a.status}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {a.alert_sent_at ? (
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${ALERT_STATUS_BADGE.sent}`}>
                      已发送
                    </span>
                  ) : (
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-400">
                      未发送
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-[12px] text-slate-500 max-w-[150px] truncate" title={a.resolution_note || ''}>
                  {a.resolution_note || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// =============================================================================
// AnomaliesTab with Maintenance Window Hint
// =============================================================================

function AnomaliesTabWithMw({
  items,
  total,
  loading,
}: {
  items: AnomalyRecord[];
  total: number;
  loading: boolean;
}) {
  const [mwActive, setMwActive] = useState(false);
  const [mwName, setMwName] = useState('');

  useEffect(() => {
    getActiveMaintenanceWindow()
      .then((res) => {
        setMwActive(res.has_active_window);
        setMwName(res.window?.name || '');
      })
      .catch(() => {
        // 忽略错误，不阻断页面显示
      });
  }, []);

  return (
    <div className="space-y-4">
      {/* Maintenance window banner */}
      {mwActive && (
        <div className="px-4 py-3 bg-blue-50 border border-blue-200 rounded-lg text-sm flex items-center gap-2">
          <i className="ri-time-line text-blue-600" />
          <span className="text-blue-700">
            当前处于维护窗口「{mwName}」，异常检测已暂停
          </span>
        </div>
      )}
      <AnomaliesTab items={items} total={total} loading={loading} />
    </div>
  );
}
