import { useState, useEffect, useCallback } from 'react';
import {
  listMetrics, createMetric, updateMetric, deleteMetric,
  submitReviewMetric, approveMetric, publishMetric,
  MetricItem, MetricsListResponse,
} from '../../../api/metrics';
import { listDataSources, DataSource } from '../../../api/datasources';
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

interface FormData {
  name: string;
  name_zh: string;
  metric_type: string;
  business_domain: string;
  datasource_id: string;
  table_name: string;
  column_name: string;
  formula: string;
  aggregation_type: string;
  result_type: string;
  unit: string;
  precision: string;
  sensitivity_level: string;
  description: string;
}

const blankForm = (): FormData => ({
  name: '',
  name_zh: '',
  metric_type: 'atomic',
  business_domain: '',
  datasource_id: '',
  table_name: '',
  column_name: '',
  formula: '',
  aggregation_type: 'SUM',
  result_type: 'float',
  unit: '',
  precision: '2',
  sensitivity_level: 'public',
  description: '',
});

export default function MetricsPage() {
  const { user, isDataAdmin } = useAuth();

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

  // ── modal state ──
  const [showModal, setShowModal] = useState(false);
  const [editingItem, setEditingItem] = useState<MetricItem | null>(null);
  const [formData, setFormData] = useState<FormData>(blankForm());
  const [formError, setFormError] = useState('');
  const [formLoading, setFormLoading] = useState(false);
  const [dataSources, setDataSources] = useState<DataSource[]>([]);

  // ── confirm delete ──
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean; title: string; message: string; onConfirm: () => void;
  } | null>(null);

  // ── publish flow ──
  const [publishingId, setPublishingId] = useState<string | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const is_active = filterActive === 'published' ? true : filterActive === 'draft' ? false : undefined;
      const data: MetricsListResponse = await listMetrics({
        page,
        page_size: pageSize,
        search,
        metric_type: filterType,
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

  const fetchDataSourcesForModal = async () => {
    try {
      const ds = await listDataSources();
      setDataSources(ds.datasources);
    } catch {
      // non-critical
    }
  };

  const openCreate = async () => {
    setEditingItem(null);
    setFormData(blankForm());
    setFormError('');
    await fetchDataSourcesForModal();
    setShowModal(true);
  };

  const openEdit = async (item: MetricItem) => {
    setEditingItem(item);
    setFormData({
      name: item.name,
      name_zh: item.name_zh,
      metric_type: item.metric_type,
      business_domain: item.business_domain,
      datasource_id: String(item.datasource_id),
      table_name: item.table_name,
      column_name: item.column_name,
      formula: item.formula,
      aggregation_type: item.aggregation_type,
      result_type: item.result_type,
      unit: item.unit,
      precision: String(item.precision),
      sensitivity_level: item.sensitivity_level,
      description: '',
    });
    setFormError('');
    await fetchDataSourcesForModal();
    setShowModal(true);
  };

  const resetForm = () => {
    setFormData(blankForm());
    setFormError('');
  };

  const handleSave = async () => {
    setFormError('');
    // 校验必填
    if (!formData.name.trim()) {
      setFormError('指标英文名不能为空');
      return;
    }
    if (!NAME_REGEX.test(formData.name)) {
      setFormError('只允许小写字母、数字、下划线，以字母开头，最长 128 字符');
      return;
    }
    if (!formData.metric_type) {
      setFormError('请选择指标类型');
      return;
    }
    if (!formData.datasource_id) {
      setFormError('请选择数据源');
      return;
    }
    if (!formData.table_name.trim()) {
      setFormError('数据表名不能为空');
      return;
    }
    if (!formData.column_name.trim()) {
      setFormError('字段名不能为空');
      return;
    }

    setFormLoading(true);
    try {
      const payload = {
        name: formData.name.trim(),
        name_zh: formData.name_zh.trim() || undefined,
        metric_type: formData.metric_type as MetricItem['metric_type'],
        business_domain: formData.business_domain.trim() || undefined,
        description: formData.description.trim() || undefined,
        formula: formData.formula.trim() || undefined,
        aggregation_type: formData.aggregation_type as MetricItem['aggregation_type'],
        result_type: formData.result_type as MetricItem['result_type'],
        unit: formData.unit.trim() || undefined,
        precision: formData.precision ? Number(formData.precision) : 2,
        datasource_id: Number(formData.datasource_id),
        table_name: formData.table_name.trim(),
        column_name: formData.column_name.trim(),
        sensitivity_level: formData.sensitivity_level as MetricItem['sensitivity_level'],
      };

      if (editingItem) {
        await updateMetric(editingItem.id, payload);
      } else {
        await createMetric(payload as Parameters<typeof createMetric>[0]);
      }
      setShowModal(false);
      fetchList();
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
                <i className="ri-bar-chart-grouped-line text-slate-500 text-base" />
              </span>
              <h1 className="text-lg font-semibold text-slate-800">指标管理</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">管理指标定义、口径与发布状态</p>
          </div>
          {isDataAdmin && (
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

      <div className="max-w-6xl mx-auto px-8 py-7">
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

        {/* Table */}
        {loading ? (
          <div className="text-center py-20 text-slate-400">加载中...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-20">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
              <i className="ri-bar-chart-grouped-line text-2xl text-slate-400" />
            </div>
            <p className="text-slate-500 mb-4">暂无指标</p>
            {isDataAdmin && (
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
                      <div className="font-semibold text-slate-700 text-[13px]">{item.name}</div>
                      {item.name_zh && <div className="text-[11px] text-slate-500">{item.name_zh}</div>}
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
                      DS-{item.datasource_id}
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
                          disabled={!isDataAdmin}
                          className={`text-[11px] px-2 py-1 border rounded transition-colors cursor-pointer ${
                            isDataAdmin
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
                              message: `确定下线指标「${item.name}」？下线后可在列表中查看但不可用。`,
                              onConfirm: () => handleDelete(item.id),
                            })}
                            disabled={!isDataAdmin}
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
        {!loading && items.length > 0 && (
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

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between sticky top-0 bg-white">
              <h2 className="text-[15px] font-semibold text-slate-800">
                {editingItem ? `编辑指标: ${editingItem.name}` : '新建指标'}
              </h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600 cursor-pointer">
                <i className="ri-close-line text-lg" />
              </button>
            </div>
            <div className="px-6 py-5">
              {formError && (
                <div className="mb-4 px-3 py-2 bg-red-50 text-red-600 text-xs rounded border border-red-200">{formError}</div>
              )}
              <div className="grid grid-cols-2 gap-4">
                {/* 左列 */}
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">
                    指标英文名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value.toLowerCase() })}
                    placeholder="如 gmv"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">指标中文名</label>
                  <input
                    value={formData.name_zh}
                    onChange={(e) => setFormData({ ...formData, name_zh: e.target.value })}
                    placeholder="如 商品交易总额"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">
                    指标类型 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={formData.metric_type}
                    onChange={(e) => setFormData({ ...formData, metric_type: e.target.value })}
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
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">聚合方式</label>
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
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">结果类型</label>
                  <select
                    value={formData.result_type}
                    onChange={(e) => setFormData({ ...formData, result_type: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                  >
                    {RESULT_TYPE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">
                    数据表名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    value={formData.table_name}
                    onChange={(e) => setFormData({ ...formData, table_name: e.target.value })}
                    placeholder="如 orders"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">
                    字段名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    value={formData.column_name}
                    onChange={(e) => setFormData({ ...formData, column_name: e.target.value })}
                    placeholder="如 order_amount"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">单位</label>
                  <input
                    value={formData.unit}
                    onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
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

                {/* 全宽：数据源 */}
                <div className="col-span-2">
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">
                    数据源 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={formData.datasource_id}
                    onChange={(e) => setFormData({ ...formData, datasource_id: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                  >
                    <option value="">请选择数据源</option>
                    {dataSources.map((ds) => (
                      <option key={ds.id} value={ds.id}>{ds.name}</option>
                    ))}
                  </select>
                </div>

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

                {/* 全宽：公式 */}
                <div className="col-span-2">
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">公式</label>
                  <textarea
                    value={formData.formula}
                    onChange={(e) => setFormData({ ...formData, formula: e.target.value })}
                    rows={2}
                    placeholder="如 SUM(order_amount)"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 resize-none font-mono"
                  />
                </div>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-slate-100 flex justify-end gap-3">
              <button
                onClick={() => setShowModal(false)}
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
