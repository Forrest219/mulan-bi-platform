import { useState, useEffect } from 'react';
import {
  listFieldSemantics, updateFieldSemantics,
  submitFieldForReview, approveField, rejectField,
  generateFieldAI, getFieldVersions, rollbackField,
  getStatusBadge, getSensitivityBadge,
  SemanticField, SemanticStatus, SensitivityLevel,
  previewFieldDiff, publishFields, syncFields,
} from '../../../api/semantic-maintenance';
import { listConnections, TableauConnection } from '../../../api/tableau';
import { ConfirmModal } from '../../../components/ConfirmModal';

export default function SemanticFieldListPage() {
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [selectedConnId, setSelectedConnId] = useState<number | null>(null);
  const [fields, setFields] = useState<SemanticField[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<SemanticStatus | ''>('');
  const [dsFilter, setDsFilter] = useState<number | ''>('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [pageSize] = useState(50);
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean; title: string; message: string;
    confirmLabel?: string; variant?: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  } | null>(null);
  const [modalNotify, setModalNotify] = useState<{ success: boolean; message: string } | null>(null);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<SemanticField>>({});
  const [syncingConnId, setSyncingConnId] = useState<number | null>(null);
  const [syncResult, setSyncResult] = useState<any>(null);
  const [selectedFields, setSelectedFields] = useState<Set<number>>(new Set());
  const [batchLoading, setBatchLoading] = useState(false);

  useEffect(() => {
    listConnections(true).then(data => {
      setConnections(data.connections);
      if (data.connections.length > 0 && !selectedConnId) {
        setSelectedConnId(data.connections[0].id);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedConnId) return;
    loadFields();
  }, [selectedConnId, statusFilter, dsFilter, page]);

  const loadFields = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await listFieldSemantics({
        connection_id: selectedConnId!,
        status: statusFilter || undefined,
        ds_id: dsFilter || undefined,
        page,
        page_size: pageSize,
      });
      setFields(data.items);
      setTotal(data.total);
      setTotalPages(data.pages);
    } catch (e: any) {
      setLoadError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const handleAction = async (id: number, fn: (id: number) => Promise<any>, successMsg: string) => {
    setActionLoading(id);
    try {
      const result = await fn(id);
      setModalNotify({ success: true, message: result.message || successMsg });
      loadFields();
    } catch (e: any) {
      setModalNotify({ success: false, message: e.message || '操作失败' });
    } finally {
      setActionLoading(null);
    }
  };

  const handleSyncFields = async () => {
    if (!selectedConnId) return;
    setSyncingConnId(selectedConnId);
    setSyncResult(null);
    try {
      // This requires a tableau_datasource_id - we'll prompt or use first available
      const result = await syncFields(selectedConnId, '');
      setSyncResult(result);
      if (result.synced > 0) loadFields();
    } catch (e: any) {
      setModalNotify({ success: false, message: e.message });
    } finally {
      setSyncingConnId(null);
    }
  };

  const openEditModal = (field: SemanticField) => {
    setEditingId(field.id);
    setEditForm({
      semantic_name_zh: field.semantic_name_zh,
      semantic_definition: field.semantic_definition,
      metric_definition: field.metric_definition,
      dimension_definition: field.dimension_definition,
      unit: field.unit,
      sensitivity_level: field.sensitivity_level,
    });
  };

  const handleSaveEdit = async () => {
    if (!editingId) return;
    setActionLoading(editingId);
    try {
      const result = await updateFieldSemantics(editingId, editForm);
      setModalNotify({ success: true, message: result.message });
      setEditingId(null);
      loadFields();
    } catch (e: any) {
      setModalNotify({ success: false, message: e.message });
    } finally {
      setActionLoading(null);
    }
  };

  const handleBatchPublish = async () => {
    if (!selectedConnId || selectedFields.size === 0) return;
    setBatchLoading(true);
    try {
      const result = await publishFields(selectedConnId, Array.from(selectedFields), false);
      setModalNotify({
        success: true,
        message: `成功: ${result.succeeded.length}, 失败: ${result.failed.length}, 跳过: ${result.skipped.length}`,
      });
      setSelectedFields(new Set());
      loadFields();
    } catch (e: any) {
      setModalNotify({ success: false, message: e.message });
    } finally {
      setBatchLoading(false);
    }
  };

  const toggleFieldSelection = (id: number) => {
    const newSet = new Set(selectedFields);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedFields(newSet);
  };

  const toggleAll = () => {
    if (selectedFields.size === fields.length) {
      setSelectedFields(new Set());
    } else {
      setSelectedFields(new Set(fields.map(f => f.id)));
    }
  };

  const statusOptions: { value: SemanticStatus | ''; label: string }[] = [
    { value: '', label: '全部' },
    { value: 'draft', label: '草稿' },
    { value: 'ai_generated', label: 'AI 已生成' },
    { value: 'pending_review', label: '待审核' },
    { value: 'approved', label: '已审核' },
    { value: 'rejected', label: '已驳回' },
    { value: 'published', label: '已发布' },
  ];

  const formatDate = (str: string | null) => str ? new Date(str).toLocaleString() : '-';

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">字段语义管理</h1>
          <p className="text-sm text-slate-400 mt-0.5">批量管理和审核字段语义</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSyncFields}
            disabled={syncingConnId !== null || !selectedConnId}
            className="px-4 py-2 text-sm bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg flex items-center gap-1.5 disabled:opacity-50"
          >
            {syncingConnId ? (
              <><i className="ri-loader-4-line animate-spin" /> 同步中...</>
            ) : (
              <><i className="ri-refresh-line" /> 同步字段</>
            )}
          </button>
          {selectedFields.size > 0 && (
            <button
              onClick={() => setConfirmModal({
                open: true, title: '批量发布',
                message: `确定要发布选中的 ${selectedFields.size} 个字段吗？`,
                confirmLabel: '发布', variant: 'info',
                onConfirm: () => { setConfirmModal(null); handleBatchPublish(); },
              })}
              disabled={batchLoading}
              className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg flex items-center gap-1.5"
            >
              <i className="ri-upload-cloud-line" /> 批量发布 ({selectedFields.size})
            </button>
          )}
        </div>
      </div>

      {/* Sync Result */}
      {syncResult && (
        <div className={`mb-4 p-4 rounded-lg text-sm ${syncResult.errors?.length > 0 ? 'bg-amber-50 border border-amber-200' : 'bg-emerald-50 border border-emerald-200'}`}>
          <div className="font-medium mb-1">同步完成</div>
          <div className="text-slate-600">
            更新 {syncResult.synced} 个字段，{syncResult.skipped} 个跳过
            {syncResult.errors?.length > 0 && `，${syncResult.errors.length} 个错误`}
          </div>
          <button onClick={() => setSyncResult(null)} className="mt-2 text-xs text-slate-400 hover:text-slate-600">关闭</button>
        </div>
      )}

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
          状态：
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
        <span className="text-xs text-slate-400">共 {total} 条，已选 {selectedFields.size}</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center py-12 text-slate-400">加载中...</div>
      ) : loadError ? (
        <div className="text-center py-12 text-red-500">{loadError}</div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-3 py-3 text-left">
                    <input type="checkbox" checked={selectedFields.size === fields.length && fields.length > 0}
                      onChange={toggleAll}
                      className="w-4 h-4 rounded border-slate-300 text-blue-600" />
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">字段名称</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">语义名称</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">定义</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">类型</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">敏感级别</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">状态</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {fields.map(field => {
                  const statusBadge = getStatusBadge(field.status);
                  const sensBadge = getSensitivityBadge(field.sensitivity_level);
                  const isSelected = selectedFields.has(field.id);
                  return (
                    <tr key={field.id} className={`hover:bg-slate-50 ${isSelected ? 'bg-blue-50/50' : ''}`}>
                      <td className="px-3 py-3">
                        <input type="checkbox" checked={isSelected}
                          onChange={() => toggleFieldSelection(field.id)}
                          className="w-4 h-4 rounded border-slate-300 text-blue-600" />
                      </td>
                      <td className="px-4 py-3 text-slate-500">{field.id}</td>
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs text-slate-600">{field.tableau_field_id.slice(0, 20)}...</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-800">{field.semantic_name_zh || '-'}</div>
                        {field.semantic_name && <div className="text-xs text-slate-400">{field.semantic_name}</div>}
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-xs text-slate-600 max-w-xs truncate">
                          {field.metric_definition || field.dimension_definition || field.semantic_definition || '-'}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs text-slate-500">{field.unit || '-'}</span>
                      </td>
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
                        <div className="flex items-center gap-1 flex-wrap">
                          <button
                            onClick={() => openEditModal(field)}
                            className="px-2 py-1 text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded"
                          >
                            编辑
                          </button>
                          {field.status === 'draft' || field.status === 'ai_generated' || field.status === 'rejected' ? (
                            <button
                              onClick={() => handleAction(field.id, submitFieldForReview, '已提交审核')}
                              disabled={actionLoading === field.id}
                              className="px-2 py-1 text-xs text-amber-600 hover:text-amber-700 hover:bg-amber-50 rounded"
                            >
                              提交
                            </button>
                          ) : null}
                          {field.status === 'pending_review' ? (
                            <>
                              <button
                                onClick={() => handleAction(field.id, approveField, '已审核通过')}
                                disabled={actionLoading === field.id}
                                className="px-2 py-1 text-xs text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 rounded"
                              >
                                通过
                              </button>
                              <button
                                onClick={() => setConfirmModal({
                                  open: true, title: '驳回字段',
                                  message: `确定要驳回字段 ${field.semantic_name_zh || field.id} 吗？`,
                                  confirmLabel: '驳回', variant: 'warning',
                                  onConfirm: () => { setConfirmModal(null); handleAction(field.id, rejectField, '已驳回'); },
                                })}
                                disabled={actionLoading === field.id}
                                className="px-2 py-1 text-xs text-red-600 hover:text-red-700 hover:bg-red-50 rounded"
                              >
                                驳回
                              </button>
                            </>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {fields.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-12 text-center text-slate-400">
                      暂无数据{selectedConnId ? '' : '，请先选择连接'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
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
            <h2 className="text-lg font-semibold text-slate-800 mb-4">编辑字段语义</h2>
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
                <label className="block text-sm font-medium text-slate-600 mb-1.5">语义定义</label>
                <textarea
                  value={editForm.semantic_definition || ''}
                  onChange={e => setEditForm({ ...editForm, semantic_definition: e.target.value })}
                  rows={3}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="描述该字段的语义含义..."
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">指标定义</label>
                <textarea
                  value={editForm.metric_definition || ''}
                  onChange={e => setEditForm({ ...editForm, metric_definition: e.target.value })}
                  rows={2}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="SUM(field) / AVG(field)..."
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
                <label className="block text-sm font-medium text-slate-600 mb-1.5">单位</label>
                <input
                  type="text"
                  value={editForm.unit || ''}
                  onChange={e => setEditForm({ ...editForm, unit: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="如：元、%、次"
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