import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  listMetrics, createMetric, updateMetric, deleteMetric, getMetricDetail,
  submitReviewMetric, approveMetric, publishMetric,
  MetricItem, MetricsListResponse, MetricDetail, MetricDependency,
} from '../../../api/metrics';
import {
  listConnections, listAssets, getDatasourceMetadata,
  TableauAsset, TableauAssetField, TableauConnection,
} from '../../../api/tableau';
import { ConfirmModal } from '../../../components/ConfirmModal';
import { useAuth } from '../../../context/AuthContext';

const METRIC_TYPE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'atomic', label: '原子' },
  { value: 'derived', label: '派生' },
  { value: 'ratio', label: '比率' },
];

const AGGREGATION_OPTIONS = [
  { value: 'SUM', label: 'SUM' },
  { value: 'AVG', label: 'AVG' },
  { value: 'COUNT', label: 'COUNT' },
  { value: 'COUNT_DISTINCT', label: 'COUNT_DISTINCT' },
  { value: 'MAX', label: 'MAX' },
  { value: 'MIN', label: 'MIN' },
  { value: 'none', label: '无' },
];

const RESULT_TYPE_OPTIONS = [
  { value: 'float', label: '数值' },
  { value: 'integer', label: '整数' },
  { value: 'percentage', label: '百分比' },
  { value: 'currency', label: '金额' },
];

const SENSITIVITY_OPTIONS = [
  { value: 'public', label: '公开' },
  { value: 'internal', label: '内部' },
  { value: 'confidential', label: '机密' },
  { value: 'restricted', label: '高度机密' },
];

const METRIC_TYPE_BADGE: Record<string, string> = {
  atomic: 'bg-blue-50 text-blue-600',
  derived: 'bg-purple-50 text-purple-600',
  ratio: 'bg-orange-50 text-orange-600',
};

const METRIC_TYPE_LABEL: Record<string, string> = {
  atomic: '原子',
  derived: '派生',
  ratio: '比率',
};

const SENSITIVITY_BADGE: Record<string, string> = {
  public: 'bg-emerald-50 text-emerald-600',
  internal: 'bg-yellow-50 text-yellow-600',
  confidential: 'bg-orange-50 text-orange-600',
  restricted: 'bg-red-50 text-red-600',
};

const SENSITIVITY_LABEL: Record<string, string> = {
  public: '公开',
  internal: '内部',
  confidential: '机密',
  restricted: '高度机密',
};

function getErrorMessage(error: unknown, fallback = '操作失败'): string {
  return error instanceof Error ? error.message : fallback;
}

function formatDate(iso: string): string {
  if (!iso) return '—';
  try {
    return iso.slice(0, 10);
  } catch {
    return '—';
  }
}

const NAME_REGEX = /^[a-z][a-z0-9_]{1,127}$/;

function metricDisplayName(metric: Pick<MetricItem, 'metric_code' | 'name' | 'name_zh'>): string {
  return metric.name_zh || metric.name || metric.metric_code || '未命名指标';
}

function fieldCaption(field: TableauAssetField): string {
  return field.caption || field.name || field.field || field.fullyQualifiedName || field.fully_qualified_name || '';
}

function stringifyExpression(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function parseExpression(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return { expression: trimmed };
  }
}

interface FormData {
  metric_code: string;
  name: string;
  name_zh: string;
  metric_type: string;
  business_domain: string;
  formula: string;
  formula_expression: string;
  aggregation_type: string;
  result_type: string;
  unit: string;
  precision: string;
  sensitivity_level: string;
  description: string;
  tableau_connection_id: string;
  tableau_asset_id: string;
  tableau_datasource_luid: string;
  field_caption: string;
  dependency_metric_ids: string[];
  numerator_metric_id: string;
  denominator_metric_id: string;
}

const blankForm = (): FormData => ({
  metric_code: '',
  name: '',
  name_zh: '',
  metric_type: 'atomic',
  business_domain: '',
  formula: '',
  formula_expression: '',
  aggregation_type: 'SUM',
  result_type: 'float',
  unit: '',
  precision: '2',
  sensitivity_level: 'public',
  description: '',
  tableau_connection_id: '',
  tableau_asset_id: '',
  tableau_datasource_luid: '',
  field_caption: '',
  dependency_metric_ids: [],
  numerator_metric_id: '',
  denominator_metric_id: '',
});

export default function MetricsPage() {
  const { isAdmin, isDataAdmin } = useAuth();
  const canManageMetrics = isAdmin || isDataAdmin;

  // ── list state ──
  const [items, setItems] = useState<MetricItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterActive, setFilterActive] = useState<string>('');

  // ── inline form state ──
  const [showForm, setShowForm] = useState(false);
  const [editingItem, setEditingItem] = useState<MetricItem | null>(null);
  const [formData, setFormData] = useState<FormData>(blankForm());
  const [formError, setFormError] = useState('');
  const [formLoading, setFormLoading] = useState(false);
  const [tableauConnections, setTableauConnections] = useState<TableauConnection[]>([]);
  const [tableauAssets, setTableauAssets] = useState<TableauAsset[]>([]);
  const [tableauFields, setTableauFields] = useState<TableauAssetField[]>([]);
  const [dependencyOptions, setDependencyOptions] = useState<MetricItem[]>([]);
  const [tableauLoading, setTableauLoading] = useState(false);
  const formRef = useRef<HTMLDivElement | null>(null);

  // ── confirm delete ──
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean; title: string; message: string; onConfirm: () => void;
  } | null>(null);

  // ── publish flow ──
  const [publishingId, setPublishingId] = useState<string | null>(null);

  const fetchList = useCallback(async (overrides?: {
    page?: number;
    search?: string;
    filterType?: string;
    filterActive?: string;
  }) => {
    setLoading(true);
    setLoadError('');
    try {
      const nextPage = overrides?.page ?? page;
      const nextSearch = overrides?.search ?? search;
      const nextFilterType = overrides?.filterType ?? filterType;
      const nextFilterActive = overrides?.filterActive ?? filterActive;
      const is_active = nextFilterActive === 'published' ? true : nextFilterActive === 'draft' ? false : undefined;
      const data: MetricsListResponse = await listMetrics({
        page: nextPage,
        page_size: pageSize,
        search: nextSearch,
        metric_type: nextFilterType,
        is_active,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setLoadError(getErrorMessage(e, '加载失败'));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, filterType, filterActive]);

  useEffect(() => { fetchList(); }, [fetchList]);

  const fetchModalResources = async (excludeMetricId?: string) => {
    try {
      const [connections, metrics] = await Promise.all([
        listConnections(false),
        listMetrics({ page: 1, page_size: 200 }),
      ]);
      setTableauConnections(connections.connections.filter((conn) => conn.is_active));
      setDependencyOptions(
        metrics.items.filter((metric) => (
          metric.id !== excludeMetricId && (metric.metric_type === 'atomic' || metric.metric_type === 'derived')
        )),
      );
    } catch {
      // non-critical
    }
  };

  const openCreate = async () => {
    setEditingItem(null);
    setFormData(blankForm());
    setTableauAssets([]);
    setTableauFields([]);
    setFormError('');
    await fetchModalResources();
    setShowForm(true);
  };

  const openEdit = async (item: MetricItem) => {
    setEditingItem(item);
    let detail: MetricDetail | MetricItem = item;
    try {
      detail = await getMetricDetail(item.id);
    } catch {
      // Fall back to list payload when detail is temporarily unavailable.
    }
    const dependencies = detail.dependencies || [];
    const numerator = dependencies.find((dep) => dep.dependency_role === 'numerator')?.depends_on_metric_id || '';
    const denominator = dependencies.find((dep) => dep.dependency_role === 'denominator')?.depends_on_metric_id || '';
    setFormData({
      metric_code: detail.metric_code || '',
      name: detail.name || '',
      name_zh: detail.name_zh || '',
      metric_type: detail.metric_type,
      business_domain: detail.business_domain || '',
      formula: detail.formula || '',
      formula_expression: stringifyExpression(detail.formula_expression),
      aggregation_type: detail.aggregation_type || 'SUM',
      result_type: detail.result_type || (detail.metric_type === 'ratio' ? 'percentage' : 'float'),
      unit: detail.unit || (detail.metric_type === 'ratio' ? '%' : ''),
      precision: String(detail.precision ?? 2),
      sensitivity_level: detail.sensitivity_level,
      description: 'description' in detail ? detail.description || '' : '',
      tableau_connection_id: detail.tableau_connection_id ? String(detail.tableau_connection_id) : '',
      tableau_asset_id: detail.tableau_asset_id ? String(detail.tableau_asset_id) : '',
      tableau_datasource_luid: detail.tableau_datasource_luid || '',
      field_caption: detail.field_mappings ? Object.values(detail.field_mappings)[0] || '' : '',
      dependency_metric_ids: dependencies
        .filter((dep) => dep.dependency_role === 'base')
        .sort((a, b) => (a.expression_order ?? 0) - (b.expression_order ?? 0))
        .map((dep) => dep.depends_on_metric_id),
      numerator_metric_id: numerator,
      denominator_metric_id: denominator,
    });
    setTableauAssets([]);
    setTableauFields([]);
    setFormError('');
    await fetchModalResources(item.id);
    setShowForm(true);
  };

  const _resetForm = () => {
    setFormData(blankForm());
    setFormError('');
  };

  useEffect(() => {
    if (showForm) {
      formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [showForm, editingItem?.id]);

  useEffect(() => {
    if (!showForm || !formData.tableau_connection_id) {
      setTableauAssets([]);
      return;
    }
    let ignore = false;
    setTableauLoading(true);
    listAssets({
      connection_id: Number(formData.tableau_connection_id),
      asset_type: 'datasource',
      page: 1,
      page_size: 100,
    })
      .then((res) => {
        if (!ignore) setTableauAssets(res.assets);
      })
      .catch(() => {
        if (!ignore) setTableauAssets([]);
      })
      .finally(() => {
        if (!ignore) setTableauLoading(false);
      });
    return () => { ignore = true; };
  }, [formData.tableau_connection_id, showForm]);

  useEffect(() => {
    if (!showForm || !formData.tableau_asset_id) {
      setTableauFields([]);
      return;
    }
    let ignore = false;
    setTableauLoading(true);
    getDatasourceMetadata(Number(formData.tableau_asset_id))
      .then((res) => {
        if (!ignore) {
          setTableauFields(res.fields || []);
          setFormData((prev) => ({
            ...prev,
            tableau_datasource_luid: res.datasource_luid || prev.tableau_datasource_luid,
          }));
        }
      })
      .catch(() => {
        if (!ignore) setTableauFields([]);
      })
      .finally(() => {
        if (!ignore) setTableauLoading(false);
      });
    return () => { ignore = true; };
  }, [formData.tableau_asset_id, showForm]);

  const handleSave = async () => {
    setFormError('');
    // 校验必填
    if (formData.name.trim() && !NAME_REGEX.test(formData.name.trim())) {
      setFormError('只允许小写字母、数字、下划线，以字母开头，最长 128 字符');
      return;
    }
    if (!formData.name_zh.trim()) {
      setFormError('指标中文名不能为空');
      return;
    }
    if (!formData.metric_type) {
      setFormError('请选择指标类型');
      return;
    }
    if (formData.metric_type === 'atomic') {
      if (!formData.tableau_connection_id) {
        setFormError('请选择 Tableau 连接');
        return;
      }
      if (!formData.tableau_asset_id) {
        setFormError('请选择 Tableau Published Datasource');
        return;
      }
      if (!formData.field_caption) {
        setFormError('请选择 Tableau 字段');
        return;
      }
      if (!formData.aggregation_type) {
        setFormError('请选择聚合方式');
        return;
      }
    }
    if (formData.metric_type === 'derived') {
      if (formData.dependency_metric_ids.length === 0) {
        setFormError('请选择至少一个依赖指标');
        return;
      }
      if (!formData.formula_expression.trim()) {
        setFormError('请填写或生成结构化公式表达');
        return;
      }
    }
    if (formData.metric_type === 'ratio') {
      if (!formData.numerator_metric_id || !formData.denominator_metric_id) {
        setFormError('请选择分子指标和分母指标');
        return;
      }
      if (formData.numerator_metric_id === formData.denominator_metric_id) {
        setFormError('分子指标和分母指标不能相同');
        return;
      }
    }

    setFormLoading(true);
    try {
      const metricType = formData.metric_type as MetricItem['metric_type'];
      const selectedAsset = tableauAssets.find((asset) => String(asset.id) === formData.tableau_asset_id);
      const selectedDependencies = dependencyOptions.filter((metric) => (
        formData.dependency_metric_ids.includes(metric.id)
      ));
      const numeratorMetric = dependencyOptions.find((metric) => metric.id === formData.numerator_metric_id);
      const denominatorMetric = dependencyOptions.find((metric) => metric.id === formData.denominator_metric_id);
      const dependencies: MetricDependency[] = [];

      if (metricType === 'derived') {
        formData.dependency_metric_ids.forEach((metricId, index) => {
          dependencies.push({
            depends_on_metric_id: metricId,
            dependency_role: 'base',
            expression_order: index,
          });
        });
      }
      if (metricType === 'ratio') {
        dependencies.push(
          { depends_on_metric_id: formData.numerator_metric_id, dependency_role: 'numerator', expression_order: 0 },
          { depends_on_metric_id: formData.denominator_metric_id, dependency_role: 'denominator', expression_order: 1 },
        );
      }

      const expression = metricType === 'atomic'
        ? {
            type: 'tableau_field',
            field_caption: formData.field_caption,
            aggregation_type: formData.aggregation_type,
          }
        : metricType === 'ratio'
          ? {
              type: 'ratio',
              numerator_metric_id: formData.numerator_metric_id,
              denominator_metric_id: formData.denominator_metric_id,
              operator: 'divide',
            }
          : parseExpression(formData.formula_expression);

      const payload = {
        name: formData.name.trim() || undefined,
        name_zh: formData.name_zh.trim(),
        metric_type: metricType,
        business_domain: formData.business_domain.trim() || undefined,
        description: formData.description.trim() || undefined,
        formula: metricType === 'atomic'
          ? `${formData.aggregation_type}([${formData.field_caption}])`
          : formData.formula.trim() || undefined,
        aggregation_type: metricType === 'ratio'
          ? 'none' as const
          : formData.aggregation_type as MetricItem['aggregation_type'],
        result_type: (metricType === 'ratio' ? 'percentage' : formData.result_type) as MetricItem['result_type'],
        unit: metricType === 'ratio' ? '%' : formData.unit.trim() || undefined,
        precision: formData.precision ? Number(formData.precision) : 2,
        sensitivity_level: formData.sensitivity_level as MetricItem['sensitivity_level'],
        dependencies: dependencies.length ? dependencies : undefined,
        tableau_connection_id: formData.tableau_connection_id ? Number(formData.tableau_connection_id) : undefined,
        tableau_asset_id: formData.tableau_asset_id ? Number(formData.tableau_asset_id) : undefined,
        tableau_datasource_luid: formData.tableau_datasource_luid || selectedAsset?.tableau_id || undefined,
        field_caption: metricType === 'atomic' ? formData.field_caption : undefined,
        field_mappings: metricType === 'atomic' ? { value: formData.field_caption } : undefined,
        required_base_metrics: metricType === 'derived'
          ? selectedDependencies.map(metricDisplayName)
          : metricType === 'ratio'
            ? [numeratorMetric, denominatorMetric].filter(Boolean).map((metric) => metricDisplayName(metric!))
            : undefined,
        formula_expression: expression,
      };

      if (editingItem) {
        await updateMetric(editingItem.id, payload);
        await fetchList();
      } else {
        await createMetric(payload as Parameters<typeof createMetric>[0]);
        setSearch('');
        setFilterType('');
        setFilterActive('');
        setPage(1);
        await fetchList({ page: 1, search: '', filterType: '', filterActive: '' });
      }
      setShowForm(false);
      setEditingItem(null);
    } catch (e) {
      setFormError(getErrorMessage(e));
    } finally {
      setFormLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteMetric(id);
      setConfirmModal(null);
      fetchList();
    } catch (e) {
      setConfirmModal(null);
      setLoadError(getErrorMessage(e));
    }
  };

  const handlePublish = async (item: MetricItem) => {
    if (item.lineage_status === 'unknown') {
      setLoadError('血缘关系未解析，无法发布');
      return;
    }
    setPublishingId(item.id);
    try {
      await submitReviewMetric(item.id);
      await approveMetric(item.id);
      await publishMetric(item.id);
      setPublishingId(null);
      fetchList();
    } catch (e) {
      setPublishingId(null);
      setLoadError(getErrorMessage(e));
    }
  };

  const pages = Math.ceil(total / pageSize) || 1;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="w-5 h-5 flex items-center justify-center">
                <i className="ri-hammer-line text-slate-500 text-base" />
              </span>
              <h1 className="text-lg font-semibold text-slate-800">指标治理</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">管理指标定义、口径与发布状态</p>
          </div>
          {canManageMetrics && (
            <button
              onClick={openCreate}
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 text-white text-[12px] font-medium rounded-lg hover:bg-blue-500 transition-colors cursor-pointer"
            >
              <i className="ri-add-line" />
              新建指标
            </button>
          )}
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto">
        {/* Error banner */}
        {loadError && (
          <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-sm flex items-center justify-between">
            <span>{loadError}</span>
            <button onClick={() => setLoadError('')} className="text-slate-400 hover:text-slate-600 cursor-pointer">×</button>
          </div>
        )}

        {/* Filter bar */}
        <div className="flex items-center gap-3 mb-4 flex-wrap">
          {/* Search */}
          <div className="relative">
            <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
            <input
              type="text"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder="搜索指标名或中文名"
              className="pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-[13px] w-56 focus:outline-none focus:border-slate-400"
            />
          </div>

          {/* metric_type filter */}
          <select
            value={filterType}
            onChange={(e) => { setFilterType(e.target.value); setPage(1); }}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-[13px] bg-white focus:outline-none focus:border-slate-400"
          >
            {METRIC_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          {/* is_active filter */}
          <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-0.5">
            {['', 'published', 'draft'].map((v) => (
              <button
                key={v}
                onClick={() => { setFilterActive(v); setPage(1); }}
                className={`px-3 py-1 text-[12px] rounded-md transition-colors cursor-pointer ${
                  filterActive === v
                    ? 'bg-white text-slate-700 shadow-sm font-medium'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {v === '' ? '全部' : v === 'published' ? '已发布' : '草稿'}
              </button>
            ))}
          </div>
        </div>

        {/* Table / empty state */}
        {showForm ? null : loading ? (
          <div className="text-center py-20 text-slate-400">加载中...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-20">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
              <i className="ri-bar-chart-grouped-line text-2xl text-slate-400" />
            </div>
            <p className="text-slate-500 mb-4">暂无指标</p>
            {canManageMetrics && (
              <button onClick={openCreate} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-500 cursor-pointer">
                新建指标
              </button>
            )}
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="bg-slate-50">
                  {['指标名', '类型', '业务域', '数据源', '状态', '敏感级别', '创建时间', '操作'].map((h) => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-t border-slate-100 hover:bg-slate-50">
                    {/* 指标名 */}
                    <td className="px-4 py-3">
                      <Link to={`/governance/metrics/${item.id}`} className="font-semibold text-blue-600 hover:text-blue-800 text-[13px] hover:underline">
                        {metricDisplayName(item)}
                      </Link>
                      <div className="text-[11px] text-slate-500">
                        {item.metric_code || '未编号'}{item.name ? ` · ${item.name}` : ''}
                      </div>
                    </td>
                    {/* 类型 */}
                    <td className="px-4 py-3" style={{ width: 80 }}>
                      <span className={`text-[11px] font-medium px-2 py-0.5 rounded ${METRIC_TYPE_BADGE[item.metric_type] || 'bg-slate-100 text-slate-600'}`}>
                        {METRIC_TYPE_LABEL[item.metric_type] || item.metric_type}
                      </span>
                    </td>
                    {/* 业务域 */}
                    <td className="px-4 py-3 text-[12px] text-slate-600" style={{ width: 100 }}>
                      {item.business_domain || '—'}
                    </td>
                    {/* 数据源 */}
                    <td className="px-4 py-3 text-[12px] text-slate-600 font-mono" style={{ width: 80 }}>
                      {item.tableau_datasource_luid
                        ? `Tableau ${item.tableau_datasource_luid.slice(0, 8)}`
                        : item.datasource_id
                          ? `DS-${item.datasource_id}`
                          : '—'}
                    </td>
                    {/* 状态 */}
                    <td className="px-4 py-3" style={{ width: 80 }}>
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                        item.is_active
                          ? 'bg-emerald-50 text-emerald-600'
                          : 'bg-slate-100 text-slate-400'
                      }`}>
                        {item.is_active ? '已发布' : '草稿'}
                      </span>
                    </td>
                    {/* 敏感级别 */}
                    <td className="px-4 py-3" style={{ width: 80 }}>
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${SENSITIVITY_BADGE[item.sensitivity_level] || 'bg-slate-100 text-slate-600'}`}>
                        {SENSITIVITY_LABEL[item.sensitivity_level] || item.sensitivity_level}
                      </span>
                    </td>
                    {/* 创建时间 */}
                    <td className="px-4 py-3 text-[12px] text-slate-500" style={{ width: 100 }}>
                      {formatDate(item.created_at)}
                    </td>
                    {/* 操作 */}
                    <td className="px-4 py-3" style={{ width: 120 }}>
                      <div className="flex items-center gap-2 flex-wrap">
                        <button
                          onClick={() => openEdit(item)}
                          disabled={!canManageMetrics}
                          className={`text-[11px] px-2 py-1 border rounded transition-colors cursor-pointer ${
                            canManageMetrics
                              ? 'border-slate-200 text-slate-500 hover:text-slate-800 hover:border-slate-300'
                              : 'border-slate-100 text-slate-300 cursor-not-allowed'
                          }`}
                        >
                          编辑
                        </button>
                        {!item.is_active && (item.lineage_status === 'resolved' || item.lineage_status === 'manual') && (
                          <button
                            onClick={() => handlePublish(item)}
                            disabled={publishingId === item.id}
                            className="text-[11px] px-2 py-1 border border-blue-200 text-blue-600 hover:border-blue-400 hover:text-blue-700 rounded transition-colors cursor-pointer disabled:opacity-50"
                          >
                            {publishingId === item.id ? '发布中...' : '发布'}
                          </button>
                        )}
                        {item.is_active && (
                          <button
                            onClick={() => setConfirmModal({
                              open: true,
                              title: '下线指标',
                              message: `确定下线指标「${metricDisplayName(item)}」？下线后可在列表中查看但不可用。`,
                              onConfirm: () => handleDelete(item.id),
                            })}
                            disabled={!canManageMetrics}
                            className="text-[11px] px-2 py-1 text-red-400 hover:text-red-600 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            下线
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {!showForm && !loading && items.length > 0 && (
          <div className="mt-4 flex items-center justify-between text-[13px] text-slate-500">
            <span>第 {page} 页，共 {pages} 页，共 {total} 条</span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-3 py-1 border border-slate-200 rounded hover:bg-slate-50 disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
              >
                上一页
              </button>
              <button
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
                disabled={page >= pages}
                className="px-3 py-1 border border-slate-200 rounded hover:bg-slate-50 disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
      </div>

      {/* Inline Create / Edit Form */}
      {showForm && (
        <div ref={formRef} className="px-8 pb-7">
          <div className="max-w-6xl mx-auto bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-white">
              <h2 className="text-[15px] font-semibold text-slate-800">
                {editingItem ? `编辑指标: ${metricDisplayName(editingItem)}` : '新建指标'}
              </h2>
              <button
                onClick={() => {
                  setShowForm(false);
                  setEditingItem(null);
                }}
                className="text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <i className="ri-close-line text-lg" />
              </button>
            </div>
            <div className="px-6 py-5">
              {formError && (
                <div className="mb-4 px-3 py-2 bg-red-50 text-red-600 text-xs rounded border border-red-200">{formError}</div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">指标编号</label>
                  <div className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] bg-slate-50 text-slate-500 font-mono">
                    {formData.metric_code || '保存后自动生成'}
                  </div>
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">
                    指标中文名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    value={formData.name_zh}
                    onChange={(e) => setFormData({ ...formData, name_zh: e.target.value })}
                    placeholder="如 商品交易总额"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">指标英文名</label>
                  <input
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value.toLowerCase() })}
                    placeholder="可选，如 gmv"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">
                    指标类型 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={formData.metric_type}
                    onChange={(e) => {
                      const nextType = e.target.value;
                      setFormData({
                        ...formData,
                        metric_type: nextType,
                        aggregation_type: nextType === 'ratio' ? 'none' : formData.aggregation_type,
                        result_type: nextType === 'ratio' ? 'percentage' : formData.result_type,
                        unit: nextType === 'ratio' ? '%' : formData.unit,
                      });
                    }}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                  >
                    <option value="atomic">原子</option>
                    <option value="derived">派生</option>
                    <option value="ratio">比率</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">业务域</label>
                  <input
                    value={formData.business_domain}
                    onChange={(e) => setFormData({ ...formData, business_domain: e.target.value })}
                    placeholder="如 commerce"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                {formData.metric_type !== 'ratio' && (
                  <div>
                    <label className="block text-[11px] font-medium text-slate-500 mb-1">
                      聚合方式 {formData.metric_type === 'atomic' && <span className="text-red-500">*</span>}
                    </label>
                    <select
                      value={formData.aggregation_type}
                      onChange={(e) => setFormData({ ...formData, aggregation_type: e.target.value })}
                      className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                    >
                      {AGGREGATION_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">结果类型</label>
                  <select
                    value={formData.result_type}
                    onChange={(e) => setFormData({ ...formData, result_type: e.target.value })}
                    disabled={formData.metric_type === 'ratio'}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                  >
                    {RESULT_TYPE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">单位</label>
                  <input
                    value={formData.unit}
                    onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
                    disabled={formData.metric_type === 'ratio'}
                    placeholder="如 元、%"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">精度</label>
                  <input
                    type="number"
                    value={formData.precision}
                    onChange={(e) => setFormData({ ...formData, precision: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>

                {formData.metric_type === 'atomic' && (
                  <>
                    <div className="col-span-2 border-t border-slate-100 pt-4">
                      <div className="text-[12px] font-semibold text-slate-700 mb-3">Tableau Binding</div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-[11px] font-medium text-slate-500 mb-1">
                            Tableau 连接 <span className="text-red-500">*</span>
                          </label>
                          <select
                            value={formData.tableau_connection_id}
                            onChange={(e) => setFormData({
                              ...formData,
                              tableau_connection_id: e.target.value,
                              tableau_asset_id: '',
                              tableau_datasource_luid: '',
                              field_caption: '',
                            })}
                            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                          >
                            <option value="">请选择 Tableau 连接</option>
                            {tableauConnections.map((conn) => (
                              <option key={conn.id} value={conn.id}>{conn.name}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-[11px] font-medium text-slate-500 mb-1">
                            Published Datasource <span className="text-red-500">*</span>
                          </label>
                          <select
                            value={formData.tableau_asset_id}
                            onChange={(e) => {
                              const asset = tableauAssets.find((a) => String(a.id) === e.target.value);
                              setFormData({
                                ...formData,
                                tableau_asset_id: e.target.value,
                                tableau_datasource_luid: asset?.tableau_id || '',
                                field_caption: '',
                              });
                            }}
                            disabled={!formData.tableau_connection_id}
                            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                          >
                            <option value="">{tableauLoading ? '加载中...' : '请选择数据源资产'}</option>
                            {tableauAssets.map((asset) => (
                              <option key={asset.id} value={asset.id}>{asset.name}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    </div>
                    <div className="col-span-2">
                      <label className="block text-[11px] font-medium text-slate-500 mb-1">
                        字段 Caption <span className="text-red-500">*</span>
                      </label>
                      <select
                        value={formData.field_caption}
                        onChange={(e) => setFormData({ ...formData, field_caption: e.target.value })}
                        disabled={!formData.tableau_asset_id}
                        className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                      >
                        <option value="">{tableauLoading ? '加载中...' : '请选择字段'}</option>
                        {tableauFields.map((field) => {
                          const caption = fieldCaption(field);
                          return caption ? (
                            <option key={`${caption}-${field.fullyQualifiedName || field.fully_qualified_name || field.name || field.field}`} value={caption}>
                              {caption}
                            </option>
                          ) : null;
                        })}
                      </select>
                    </div>
                  </>
                )}

                {formData.metric_type === 'derived' && (
                  <>
                    <div className="col-span-2 border-t border-slate-100 pt-4">
                      <div className="flex items-center justify-between mb-2">
                        <label className="block text-[11px] font-medium text-slate-500">
                          依赖指标 <span className="text-red-500">*</span>
                        </label>
                        <button
                          type="button"
                          onClick={() => setFormData({
                            ...formData,
                            formula_expression: JSON.stringify({
                              type: 'derived',
                              expression: formData.dependency_metric_ids.map((id) => `metric("${id}")`).join(' + '),
                              dependencies: formData.dependency_metric_ids,
                            }, null, 2),
                          })}
                          className="text-[11px] text-blue-600 hover:text-blue-700 cursor-pointer"
                        >
                          生成表达式
                        </button>
                      </div>
                      <select
                        value=""
                        onChange={(e) => {
                          if (!e.target.value || formData.dependency_metric_ids.includes(e.target.value)) return;
                          setFormData({ ...formData, dependency_metric_ids: [...formData.dependency_metric_ids, e.target.value] });
                        }}
                        className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                      >
                        <option value="">添加依赖指标</option>
                        {dependencyOptions.map((metric) => (
                          <option key={metric.id} value={metric.id}>{metricDisplayName(metric)}</option>
                        ))}
                      </select>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {formData.dependency_metric_ids.map((metricId) => {
                          const metric = dependencyOptions.find((m) => m.id === metricId);
                          return (
                            <span key={metricId} className="inline-flex items-center gap-1 px-2 py-1 bg-slate-100 text-slate-600 rounded text-[12px]">
                              {metric ? metricDisplayName(metric) : metricId}
                              <button
                                type="button"
                                onClick={() => setFormData({
                                  ...formData,
                                  dependency_metric_ids: formData.dependency_metric_ids.filter((id) => id !== metricId),
                                })}
                                className="text-slate-400 hover:text-slate-600 cursor-pointer"
                              >
                                <i className="ri-close-line" />
                              </button>
                            </span>
                          );
                        })}
                      </div>
                    </div>
                    <div className="col-span-2">
                      <label className="block text-[11px] font-medium text-slate-500 mb-1">
                        结构化公式表达 <span className="text-red-500">*</span>
                      </label>
                      <textarea
                        value={formData.formula_expression}
                        onChange={(e) => setFormData({ ...formData, formula_expression: e.target.value })}
                        rows={5}
                        placeholder='如 {"type":"derived","expression":"metric(\"...\") + metric(\"...\")"}'
                        className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 resize-none font-mono"
                      />
                    </div>
                  </>
                )}

                {formData.metric_type === 'ratio' && (
                  <div className="col-span-2 border-t border-slate-100 pt-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[11px] font-medium text-slate-500 mb-1">
                          分子指标 <span className="text-red-500">*</span>
                        </label>
                        <select
                          value={formData.numerator_metric_id}
                          onChange={(e) => setFormData({ ...formData, numerator_metric_id: e.target.value })}
                          className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                        >
                          <option value="">请选择分子</option>
                          {dependencyOptions.map((metric) => (
                            <option key={metric.id} value={metric.id}>{metricDisplayName(metric)}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-[11px] font-medium text-slate-500 mb-1">
                          分母指标 <span className="text-red-500">*</span>
                        </label>
                        <select
                          value={formData.denominator_metric_id}
                          onChange={(e) => setFormData({ ...formData, denominator_metric_id: e.target.value })}
                          className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                        >
                          <option value="">请选择分母</option>
                          {dependencyOptions.map((metric) => (
                            <option key={metric.id} value={metric.id}>{metricDisplayName(metric)}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                )}

                {/* 全宽：敏感级别 */}
                <div className="col-span-2">
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">敏感级别</label>
                  <select
                    value={formData.sensitivity_level}
                    onChange={(e) => setFormData({ ...formData, sensitivity_level: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                  >
                    {SENSITIVITY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>

                {/* 全宽：描述 */}
                <div className="col-span-2">
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">描述</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={3}
                    placeholder="指标的业务含义、计算口径说明"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 resize-none"
                  />
                </div>

                {formData.metric_type !== 'atomic' && (
                  <div className="col-span-2">
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">公式</label>
                  <textarea
                    value={formData.formula}
                    onChange={(e) => setFormData({ ...formData, formula: e.target.value })}
                    rows={2}
                    placeholder={formData.metric_type === 'ratio' ? '默认按分子 / 分母生成，可选填写展示公式' : '可选，填写业务展示公式'}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 resize-none font-mono"
                  />
                  </div>
                )}
              </div>
            </div>
            <div className="px-6 py-4 border-t border-slate-100 flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowForm(false);
                  setEditingItem(null);
                }}
                className="px-4 py-2 text-[13px] text-slate-600 hover:text-slate-800 cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={formLoading}
                className="px-4 py-2 bg-blue-600 text-white text-[13px] rounded-lg hover:bg-blue-500 cursor-pointer disabled:opacity-50"
              >
                {formLoading ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm delete */}
      {confirmModal?.open && (
        <ConfirmModal
          open={confirmModal.open}
          title={confirmModal.title}
          message={confirmModal.message}
          confirmLabel="下线"
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(null)}
        />
      )}
    </div>
  );
}
