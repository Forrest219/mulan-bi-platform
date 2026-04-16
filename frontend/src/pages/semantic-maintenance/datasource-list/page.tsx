import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listDatasourceSemantics, updateDatasourceSemantics,
  submitDatasourceForReview, approveDatasource, rejectDatasource,
  getStatusBadge, getSensitivityBadge,
  SemanticDatasource, SemanticStatus, SensitivityLevel,
  previewDatasourceDiff, publishDatasource,
} from '../../../api/semantic-maintenance';
import { listConnections, TableauConnection } from '../../../api/tableau';
import { ConfirmModal } from '../../../components/ConfirmModal';

type DatasourceDiffPreview = {
  tableau_current?: unknown;
  mulan_pending?: unknown;
  diff?: Record<string, unknown>;
  can_publish?: boolean;
  sensitivity_level?: SensitivityLevel;
};

type ActionResult = { message?: string };

const getErrorMessage = (error: unknown, fallback = '操作失败'): string => {
  return error instanceof Error ? error.message : fallback;
};

export default function SemanticDatasourceListPage() {
  const navigate = useNavigate();
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [selectedConnId, setSelectedConnId] = useState<number | null>(null);
  const [datasources, setDatasources] = useState<SemanticDatasource[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<SemanticStatus | ''>('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [pageSize] = useState(20);
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean; title: string; message: string;
    confirmLabel?: string; variant?: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  } | null>(null);
  const [modalNotify, setModalNotify] = useState<{ success: boolean; message: string } | null>(null);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<SemanticDatasource>>({});
  const [showDiff, setShowDiff] = useState<{ open: boolean; diff: DatasourceDiffPreview; ds: SemanticDatasource } | null>(null);

  // Load connections on mount
  /* eslint-disable react-hooks/exhaustive-deps -- listConnections 稳定引用，故意不放入 deps */
  useEffect(() => {
    listConnections(true).then(data => {
      setConnections(data.connections);
      if (data.connections.length > 0 && !selectedConnId) {
        setSelectedConnId(data.connections[0].id);
      }
    }).catch(() => {});
  }, []);
  /* eslint-enable react-hooks/exhaustive-deps */

  // Load datasources when connection or filters change
  /* eslint-disable react-hooks/exhaustive-deps -- loadDatasources 在 selectedConnId 等变化时调用，故意不放入 deps */
  useEffect(() => {
    if (!selectedConnId) return;
    loadDatasources();
  }, [selectedConnId, statusFilter, page]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const loadDatasources = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await listDatasourceSemantics({
        connection_id: selectedConnId!,
        status: statusFilter || undefined,
        page,
        page_size: pageSize,
      });
      setDatasources(data.items);
      setTotal(data.total);
      setTotalPages(data.pages);
    } catch (e: unknown) {
      setLoadError(getErrorMessage(e, '加载失败'));
    } finally {
      setLoading(false);
    }
  };

  const handleAction = async (id: number, _action: string, fn: (id: number) => Promise<ActionResult>, successMsg: string) => {
    setActionLoading(id);
    try {
      const result = await fn(id);
      setModalNotify({ success: true, message: result.message || successMsg });
      loadDatasources();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    } finally {
      setActionLoading(null);
    }
  };

  const handlePreviewDiff = async (ds: SemanticDatasource) => {
    try {
      const diff = await previewDatasourceDiff(ds.connection_id, ds.id);
      setShowDiff({ open: true, diff, ds });
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    }
  };

  const handlePublish = async (ds: SemanticDatasource, simulate = false) => {
    try {
      const result = await publishDatasource(ds.connection_id, ds.id, simulate);
      setModalNotify({
        success: true,
        message: simulate ? '模拟发布完成，请查看差异' : (result.message || '发布成功'),
      });
      if (!simulate) loadDatasources();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    }
  };

  const openEditModal = (ds: SemanticDatasource) => {
    setEditingId(ds.id);
    setEditForm({
      semantic_name_zh: ds.semantic_name_zh,
      semantic_description: ds.semantic_description,
      metric_definition: ds.metric_definition,
      dimension_definition: ds.dimension_definition,
      sensitivity_level: ds.sensitivity_level,
    });
  };

  const handleSaveEdit = async () => {
    if (!editingId) return;
    setActionLoading(editingId);
    try {
      const result = await updateDatasourceSemantics(editingId, editForm);
      setModalNotify({ success: true, message: result.message });
      setEditingId(null);
      loadDatasources();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    } finally {
      setActionLoading(null);
    }
  };

  const statusOptions: { value: SemanticStatus | ''; label: string }[] = [
    { value: '', label: '全部' },
    { value: 'draft', label: '草稿' },
    { value: 'ai_generated', label: 'AI 已生成' },
    { value: 'reviewed', label: '待审核' },
    { value: 'approved', label: '已审核' },
    { value: 'rejected', label: '已驳回' },
    { value: 'published', label: '已发布' },
  ];

  const formatDate = (str: string | null) => str ? new Date(str).toLocaleString() : '-';

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">数据源语义管理</h1>
          <p className="text-sm text-slate-400 mt-0.5">管理和审核数据源语义描述</p>
        </div>
      </div>

      {/* Connection Selector */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-slate-600 mb-1.5">选择连接</label>
        <select
          value={selectedConnId || ''}
          onChange={e => { setSelectedConnId(Number(e.target.value)); setPage(1); }}
          className="px-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 w-64"
        >
          <option value="">-- 选择连接 --</option>
          {connections.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 mb-4">
        <label className="flex items-center gap-2 text-sm text-slate-600">
          状态筛选：
          <select
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value as SemanticStatus | ''); setPage(1); }}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
          >
            {statusOptions.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <span className="text-xs text-slate-400">共 {total} 条</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center py-12 text-slate-400">加载中...</div>
      ) : loadError ? (
        <div className="text-center py-12 text-red-500">{loadError}</div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">Tableau ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">语义名称</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">描述</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">敏感级别</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">状态</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">发布状态</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">更新时间</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {datasources.map(ds => {
                const statusBadge = getStatusBadge(ds.status);
                const sensBadge = getSensitivityBadge(ds.sensitivity_level);
                return (
                  <tr key={ds.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 text-slate-500">{ds.id}</td>
                    <td className="px-4 py-3 text-slate-600 font-mono text-xs">{ds.tableau_datasource_id.slice(0, 16)}...</td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">{ds.semantic_name_zh || '-'}</div>
                      {ds.semantic_name && <div className="text-xs text-slate-400">{ds.semantic_name}</div>}
                    </td>
                    <td className="px-4 py-3 text-slate-600 max-w-xs truncate">{ds.semantic_description || '-'}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${sensBadge.className}`}>
                        {sensBadge.text}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${statusBadge.className}`}>
                        {statusBadge.text}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {ds.published_to_tableau ? (
                        <span className="text-xs text-blue-600">已发布</span>
                      ) : (
                        <span className="text-xs text-slate-400">未发布</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-xs">{formatDate(ds.updated_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1 flex-wrap">
                        <button
                          onClick={() => navigate(`/semantic-maintenance/datasources/${ds.id}`)}
                          className="px-2 py-1 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded"
                        >
                          详情
                        </button>
                        <button
                          onClick={() => openEditModal(ds)}
                          className="px-2 py-1 text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded"
                        >
                          编辑
                        </button>
                        {ds.status === 'draft' || ds.status === 'ai_generated' || ds.status === 'rejected' ? (
                          <button
                            onClick={() => handleAction(ds.id, 'submit', submitDatasourceForReview, '已提交审核')}
                            disabled={actionLoading === ds.id}
                            className="px-2 py-1 text-xs text-amber-600 hover:text-amber-700 hover:bg-amber-50 rounded"
                          >
                            提交
                          </button>
                        ) : null}
                        {ds.status === 'reviewed' ? (
                          <>
                            <button
                              onClick={() => handleAction(ds.id, 'approve', approveDatasource, '已审核通过')}
                              disabled={actionLoading === ds.id}
                              className="px-2 py-1 text-xs text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 rounded"
                            >
                              通过
                            </button>
                            <button
                              onClick={() => setConfirmModal({
                                open: true, title: '驳回数据源',
                                message: `确定要驳回数据源 ${ds.semantic_name_zh || ds.id} 吗？`,
                                confirmLabel: '驳回', variant: 'warning',
                                onConfirm: () => { setConfirmModal(null); handleAction(ds.id, 'reject', rejectDatasource, '已驳回'); },
                              })}
                              disabled={actionLoading === ds.id}
                              className="px-2 py-1 text-xs text-red-600 hover:text-red-700 hover:bg-red-50 rounded"
                            >
                              驳回
                            </button>
                          </>
                        ) : null}
                        {ds.status === 'approved' ? (
                          <>
                            <button
                              onClick={() => handlePreviewDiff(ds)}
                              className="px-2 py-1 text-xs text-purple-600 hover:text-purple-700 hover:bg-purple-50 rounded"
                            >
                              差异
                            </button>
                            <button
                              onClick={() => handlePublish(ds, true)}
                              className="px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 rounded"
                            >
                              模拟
                            </button>
                            <button
                              onClick={() => setConfirmModal({
                                open: true, title: '发布数据源',
                                message: `确定要将 "${ds.semantic_name_zh || ds.id}" 发布到 Tableau 吗？`,
                                confirmLabel: '发布', variant: 'info',
                                onConfirm: () => { setConfirmModal(null); handlePublish(ds, false); },
                              })}
                              className="px-2 py-1 text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded"
                            >
                              发布
                            </button>
                          </>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {datasources.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-slate-400">
                    暂无数据{selectedConnId ? '' : '，请先选择连接'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-4">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50"
          >
            上一页
          </button>
          <span className="text-sm text-slate-500">第 {page} / {totalPages} 页</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50"
          >
            下一页
          </button>
        </div>
      )}

      {/* Edit Modal */}
      {editingId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-lg shadow-xl max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-slate-800 mb-4">编辑数据源语义</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">语义名称（中文）</label>
                <input
                  type="text"
                  value={editForm.semantic_name_zh || ''}
                  onChange={e => setEditForm({ ...editForm, semantic_name_zh: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="如：月度销售额"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">语义描述</label>
                <textarea
                  value={editForm.semantic_description || ''}
                  onChange={e => setEditForm({ ...editForm, semantic_description: e.target.value })}
                  rows={3}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="描述该数据源的语义含义..."
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">指标定义</label>
                <textarea
                  value={editForm.metric_definition || ''}
                  onChange={e => setEditForm({ ...editForm, metric_definition: e.target.value })}
                  rows={2}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="SUM(sales) / COUNT(orders)..."
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">维度定义</label>
                <textarea
                  value={editForm.dimension_definition || ''}
                  onChange={e => setEditForm({ ...editForm, dimension_definition: e.target.value })}
                  rows={2}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="按地区、按产品分类..."
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">敏感级别</label>
                <select
                  value={editForm.sensitivity_level || ''}
                  onChange={e => setEditForm({ ...editForm, sensitivity_level: e.target.value as SensitivityLevel })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                >
                  <option value="">未设置</option>
                  <option value="public">公开</option>
                  <option value="internal">内部</option>
                  <option value="confidential">机密</option>
                  <option value="high">高度机密</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setEditingId(null)}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">取消</button>
              <button onClick={handleSaveEdit}
                disabled={actionLoading === editingId}
                className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800 disabled:opacity-50">
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Diff Preview Modal */}
      {showDiff && showDiff.open && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-2xl shadow-xl max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-slate-800 mb-4">发布差异预览</h2>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 bg-slate-50 rounded-lg">
                  <h3 className="text-sm font-medium text-slate-600 mb-2">Tableau 当前值</h3>
                  <pre className="text-xs text-slate-500 overflow-auto">
                    {JSON.stringify(showDiff.diff.tableau_current, null, 2)}
                  </pre>
                </div>
                <div className="p-4 bg-blue-50 rounded-lg">
                  <h3 className="text-sm font-medium text-blue-600 mb-2">Mulan 待发布值</h3>
                  <pre className="text-xs text-blue-700 overflow-auto">
                    {JSON.stringify(showDiff.diff.mulan_pending, null, 2)}
                  </pre>
                </div>
              </div>
              {Object.keys(showDiff.diff.diff || {}).length > 0 ? (
                <div className="p-4 bg-amber-50 rounded-lg">
                  <h3 className="text-sm font-medium text-amber-600 mb-2">差异内容</h3>
                  <pre className="text-xs text-amber-700 overflow-auto">
                    {JSON.stringify(showDiff.diff.diff, null, 2)}
                  </pre>
                </div>
              ) : (
                <div className="p-4 bg-emerald-50 rounded-lg text-sm text-emerald-600">
                  无差异，Tableau 当前值与 Mulan 待发布值一致
                </div>
              )}
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-1 rounded-full ${showDiff.diff.can_publish ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
                  {showDiff.diff.can_publish ? '可发布' : '禁止发布'}
                </span>
                {showDiff.diff.sensitivity_level && (
                  <span className="text-xs text-slate-500">
                    敏感级别: {getSensitivityBadge(showDiff.diff.sensitivity_level).text}
                  </span>
                )}
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowDiff(null)}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">关闭</button>
              {showDiff.diff.can_publish && (
                <button
                  onClick={() => { setShowDiff(null); handlePublish(showDiff.ds, false); }}
                  className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500"
                >
                  确认发布
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Notification Toast */}
      {modalNotify && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[60]" onClick={() => setModalNotify(null)}>
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-start gap-3">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center ${modalNotify.success ? 'bg-emerald-100' : 'bg-red-100'}`}>
                <i className={`${modalNotify.success ? 'ri-check-line text-emerald-600' : 'ri-error-warning-line text-red-600'} text-xl`} />
              </div>
              <div className="flex-1">
                <h3 className={`font-semibold ${modalNotify.success ? 'text-emerald-700' : 'text-red-700'}`}>
                  {modalNotify.success ? '操作成功' : '操作失败'}
                </h3>
                <p className="text-sm text-slate-600 mt-1">{modalNotify.message}</p>
              </div>
            </div>
            <button onClick={() => setModalNotify(null)}
              className="mt-4 w-full py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium rounded-lg">
              关闭
            </button>
          </div>
        </div>
      )}

      {/* Confirm Modal */}
      {confirmModal && confirmModal.open && (
        <ConfirmModal
          open={confirmModal.open}
          title={confirmModal.title}
          message={confirmModal.message}
          confirmLabel={confirmModal.confirmLabel}
          variant={confirmModal.variant}
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(null)}
        />
      )}
    </div>
  );
}