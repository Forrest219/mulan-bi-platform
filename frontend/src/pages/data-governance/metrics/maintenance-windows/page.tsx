import { useState, useCallback, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ConfirmModal } from '../../../../components/ConfirmModal';
import { useAuth } from '../../../../context/AuthContext';

const API_BASE = '/api';

export interface MaintenanceWindow {
  id: number;
  name: string;
  start_at: string;
  end_at: string;
  timezone: string;
  reason: string | null;
  created_by: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface PaginatedResponse {
  items: MaintenanceWindow[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

function getErrorMessage(error: unknown, fallback = '操作失败'): string {
  return error instanceof Error ? error.message : fallback;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return iso.slice(0, 16).replace('T', ' ');
  } catch {
    return '—';
  }
}

function formatDateForInput(iso: string | null): string {
  if (!iso) return '';
  try {
    return iso.slice(0, 16);
  } catch {
    return '';
  }
}

function isActive(startAt: string, endAt: string): boolean {
  const now = new Date();
  const start = new Date(startAt);
  const end = new Date(endAt);
  return now >= start && now <= end;
}

const TIMEZONE_OPTIONS = [
  { value: 'Asia/Shanghai', label: 'Asia/Shanghai (UTC+8)' },
  { value: 'UTC', label: 'UTC (UTC+0)' },
  { value: 'America/New_York', label: 'America/New_York (UTC-5)' },
  { value: 'Europe/London', label: 'Europe/London (UTC+0)' },
];

interface FormData {
  name: string;
  start_at: string;
  end_at: string;
  timezone: string;
  reason: string;
}

const blankForm = (): FormData => ({
  name: '',
  start_at: '',
  end_at: '',
  timezone: 'Asia/Shanghai',
  reason: '',
});

export default function MaintenanceWindowsPage() {
  const { isAdmin } = useAuth();

  // List state
  const [items, setItems] = useState<MaintenanceWindow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [filterActive, setFilterActive] = useState<boolean | null>(null);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [editingWindow, setEditingWindow] = useState<MaintenanceWindow | null>(null);
  const [formData, setFormData] = useState<FormData>(blankForm());
  const [formError, setFormError] = useState('');
  const [formLoading, setFormLoading] = useState(false);

  // Confirm delete state
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
  }>({ open: false, title: '', message: '', onConfirm: () => {} });

  const fetchList = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (filterActive !== null) {
        params.set('is_active', String(filterActive));
      }
      const res = await fetch(`${API_BASE}/metrics/maintenance-windows?${params}`, {
        credentials: 'include',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { message?: string }).message || '获取维护窗口列表失败');
      }
      const data: PaginatedResponse = await res.json();
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setLoadError(getErrorMessage(e, '获取维护窗口列表失败'));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, filterActive]);

  // Fetch list on mount and when pagination/filter changes
  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const handleCreate = () => {
    setEditingWindow(null);
    setFormData(blankForm());
    setFormError('');
    setShowModal(true);
  };

  const handleEdit = (window: MaintenanceWindow) => {
    setEditingWindow(window);
    setFormData({
      name: window.name,
      start_at: formatDateForInput(window.start_at),
      end_at: formatDateForInput(window.end_at),
      timezone: window.timezone,
      reason: window.reason || '',
    });
    setFormError('');
    setShowModal(true);
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setFormError('请输入窗口名称');
      return;
    }
    if (!formData.start_at) {
      setFormError('请输入开始时间');
      return;
    }
    if (!formData.end_at) {
      setFormError('请输入结束时间');
      return;
    }

    setFormLoading(true);
    setFormError('');
    try {
      const payload = {
        name: formData.name.trim(),
        start_at: new Date(formData.start_at).toISOString(),
        end_at: new Date(formData.end_at).toISOString(),
        timezone: formData.timezone,
        reason: formData.reason.trim() || null,
      };

      const url = editingWindow
        ? `${API_BASE}/metrics/maintenance-windows/${editingWindow.id}`
        : `${API_BASE}/metrics/maintenance-windows`;
      const method = editingWindow ? 'PUT' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { message?: string }).message || (editingWindow ? '更新失败' : '创建失败'));
      }

      setShowModal(false);
      fetchList();
    } catch (e) {
      setFormError(getErrorMessage(e, '操作失败'));
    } finally {
      setFormLoading(false);
    }
  };

  const handleDelete = (window: MaintenanceWindow) => {
    setConfirmModal({
      open: true,
      title: '确认删除',
      message: `确定要删除维护窗口「${window.name}」吗？删除后将无法恢复。`,
      onConfirm: async () => {
        setConfirmModal((prev) => ({ ...prev, open: false }));
        try {
          const res = await fetch(`${API_BASE}/metrics/maintenance-windows/${window.id}`, {
            method: 'DELETE',
            credentials: 'include',
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error((err as { message?: string }).message || '删除失败');
          }
          fetchList();
        } catch (e) {
          alert(getErrorMessage(e, '删除失败'));
        }
      },
    });
  };

  const handleToggleActive = async (window: MaintenanceWindow) => {
    try {
      const res = await fetch(`${API_BASE}/metrics/maintenance-windows/${window.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ is_active: !window.is_active }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { message?: string }).message || '更新失败');
      }
      fetchList();
    } catch (e) {
      alert(getErrorMessage(e, '更新状态失败'));
    }
  };

  const pages = Math.ceil(total / pageSize) || 1;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          {/* Breadcrumb */}
          <div className="flex items-center gap-1.5 text-[12px] text-slate-400 mb-3">
            <Link to="/governance/metrics" className="hover:text-slate-600">指标治理</Link>
            <span>/</span>
            <span className="text-slate-600">维护窗口</span>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold text-slate-800">维护窗口</h1>
              <p className="text-[13px] text-slate-500 mt-1">
                在维护窗口期间，异常检测将跳过，不写入 anomaly 记录
              </p>
            </div>
            {isAdmin && (
              <button
                onClick={handleCreate}
                className="flex items-center gap-1.5 px-4 py-2 text-[13px] font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-500 cursor-pointer"
              >
                <i className="ri-add-line" />
                新建窗口
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
        {/* Filter bar */}
        <div className="flex items-center gap-4 mb-4">
          <div className="flex items-center gap-2">
            <span className="text-[13px] text-slate-500">状态筛选：</span>
            <button
              onClick={() => setFilterActive(null)}
              className={`px-3 py-1 text-[12px] rounded-full cursor-pointer ${
                filterActive === null
                  ? 'bg-slate-700 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              全部
            </button>
            <button
              onClick={() => setFilterActive(true)}
              className={`px-3 py-1 text-[12px] rounded-full cursor-pointer ${
                filterActive === true
                  ? 'bg-emerald-600 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              激活
            </button>
            <button
              onClick={() => setFilterActive(false)}
              className={`px-3 py-1 text-[12px] rounded-full cursor-pointer ${
                filterActive === false
                  ? 'bg-slate-500 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              未激活
            </button>
          </div>
        </div>

        {/* Error banner */}
        {loadError && (
          <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-sm">
            {loadError}
          </div>
        )}

        {/* Table */}
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          {loading ? (
            <div className="text-center py-20 text-slate-400">加载中...</div>
          ) : items.length === 0 ? (
            <div className="text-center py-16">
              <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
                <i className="ri-time-line text-2xl text-slate-400" />
              </div>
              <p className="text-slate-500 mb-2">暂无维护窗口</p>
              <p className="text-[12px] text-slate-400">点击「新建窗口」创建第一个维护窗口</p>
            </div>
          ) : (
            <>
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="bg-slate-50">
                    <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      窗口名称
                    </th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      开始时间
                    </th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      结束时间
                    </th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      时区
                    </th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      状态
                    </th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      维护原因
                    </th>
                    <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((w) => {
                    const active = isActive(w.start_at, w.end_at);
                    return (
                      <tr key={w.id} className="border-t border-slate-100 hover:bg-slate-50">
                        <td className="px-4 py-3 text-[13px] text-slate-700 font-medium">{w.name}</td>
                        <td className="px-4 py-3 text-[12px] text-slate-600 font-mono">
                          {formatDate(w.start_at)}
                        </td>
                        <td className="px-4 py-3 text-[12px] text-slate-600 font-mono">
                          {formatDate(w.end_at)}
                        </td>
                        <td className="px-4 py-3 text-[12px] text-slate-500">{w.timezone}</td>
                        <td className="px-4 py-3">
                          {active ? (
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600">
                              运行中
                            </span>
                          ) : w.is_active ? (
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">
                              待生效
                            </span>
                          ) : (
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">
                              已停用
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-[12px] text-slate-500 max-w-[200px] truncate" title={w.reason || ''}>
                          {w.reason || '—'}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            {isAdmin && (
                              <>
                                <button
                                  onClick={() => handleEdit(w)}
                                  className="text-[12px] text-blue-600 hover:text-blue-800 cursor-pointer"
                                >
                                  编辑
                                </button>
                                <button
                                  onClick={() => handleToggleActive(w)}
                                  className="text-[12px] hover:text-slate-800 cursor-pointer"
                                >
                                  {w.is_active ? '停用' : '启用'}
                                </button>
                                <button
                                  onClick={() => handleDelete(w)}
                                  className="text-[12px] text-red-500 hover:text-red-700 cursor-pointer"
                                >
                                  删除
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {/* Pagination */}
              {pages > 1 && (
                <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
                  <span className="text-[12px] text-slate-500">
                    共 {total} 条，第 {page} / {pages} 页
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      className="px-3 py-1 text-[12px] bg-white border border-slate-200 rounded hover:bg-slate-50 disabled:opacity-50 cursor-pointer"
                    >
                      上一页
                    </button>
                    <button
                      onClick={() => setPage((p) => Math.min(pages, p + 1))}
                      disabled={page >= pages}
                      className="px-3 py-1 text-[12px] bg-white border border-slate-200 rounded hover:bg-slate-50 disabled:opacity-50 cursor-pointer"
                    >
                      下一页
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      </div>

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
            <div className="px-6 py-4 border-b border-slate-200">
              <h3 className="text-[15px] font-semibold text-slate-700">
                {editingWindow ? '编辑维护窗口' : '新建维护窗口'}
              </h3>
            </div>
            <div className="px-6 py-4 space-y-4">
              {formError && (
                <div className="px-3 py-2 bg-red-50 text-red-700 border border-red-200 rounded-lg text-[13px]">
                  {formError}
                </div>
              )}

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">
                  窗口名称 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="例如：数据库升级维护"
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">
                  开始时间 <span className="text-red-500">*</span>
                </label>
                <input
                  type="datetime-local"
                  value={formData.start_at}
                  onChange={(e) => setFormData({ ...formData, start_at: e.target.value })}
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">
                  结束时间 <span className="text-red-500">*</span>
                </label>
                <input
                  type="datetime-local"
                  value={formData.end_at}
                  onChange={(e) => setFormData({ ...formData, end_at: e.target.value })}
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">
                  时区
                </label>
                <select
                  value={formData.timezone}
                  onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {TIMEZONE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-600 mb-1">
                  维护原因
                </label>
                <textarea
                  value={formData.reason}
                  onChange={(e) => setFormData({ ...formData, reason: e.target.value })}
                  placeholder="简要说明本次维护的目的..."
                  rows={3}
                  className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                />
              </div>
            </div>
            <div className="px-6 py-4 border-t border-slate-200 flex items-center justify-end gap-3">
              <button
                onClick={() => setShowModal(false)}
                disabled={formLoading}
                className="px-4 py-2 text-[13px] text-slate-600 hover:bg-slate-50 rounded-lg cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={handleSubmit}
                disabled={formLoading}
                className="px-4 py-2 text-[13px] font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-50 cursor-pointer"
              >
                {formLoading ? '保存中...' : (editingWindow ? '保存' : '创建')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Delete Modal */}
      <ConfirmModal
        open={confirmModal.open}
        title={confirmModal.title}
        message={confirmModal.message}
        onConfirm={confirmModal.onConfirm}
        onCancel={() => setConfirmModal((prev) => ({ ...prev, open: false }))}
      />
    </div>
  );
}
