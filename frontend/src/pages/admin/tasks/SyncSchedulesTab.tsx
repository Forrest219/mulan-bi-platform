import { useState, useEffect } from 'react';
import {
  fetchSyncSchedules,
  createSyncSchedule,
  updateSyncSchedule,
  deleteSyncSchedule,
  bindConnections,
  unbindConnections,
  fetchSyncSchedule,
  parseCron,
  previewCron,
  type SyncSchedule,
  type TableauConnectionSimple,
} from '../../../api/tasks';

const FREQUENCY_OPTIONS = [
  { value: 'hourly', label: '每小时' },
  { value: 'daily', label: '每日' },
  { value: 'weekly', label: '每周' },
  { value: 'monthly', label: '每月' },
];

const EXECUTION_MODE_OPTIONS = [
  { value: 'parallel', label: '并行' },
  { value: 'sequential', label: '顺序' },
];

function StatusBadge({ enabled }: { enabled: boolean }) {
  return enabled ? (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-100 text-emerald-700">已启用</span>
  ) : (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-500">已禁用</span>
  );
}

function ModeBadge({ mode }: { mode: string }) {
  return mode === 'parallel' ? (
    <span className="text-[12px] text-slate-500">并行</span>
  ) : (
    <span className="text-[12px] text-blue-600">顺序</span>
  );
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

interface ScheduleFormData {
  name: string;
  description: string;
  frequency_type: string;
  cron_expr: string;
  priority: number;
  execution_mode: string;
  is_enabled: boolean;
}

interface EditModalProps {
  schedule?: SyncSchedule;
  onSave: (data: ScheduleFormData) => Promise<void>;
  onClose: () => void;
}

function EditModal({ schedule, onSave, onClose }: EditModalProps) {
  const [form, setForm] = useState<ScheduleFormData>({
    name: schedule?.name || '',
    description: schedule?.description || '',
    frequency_type: schedule?.frequency_type || 'daily',
    cron_expr: schedule?.cron_expr || '0 0 * * *',
    priority: schedule?.priority || 50,
    execution_mode: schedule?.execution_mode || 'parallel',
    is_enabled: schedule?.is_enabled ?? true,
  });
  const [cronInput, setCronInput] = useState(schedule?.cron_expr || '0 0 * * *');
  const [nextRuns, setNextRuns] = useState<string[]>([]);
  const [aiDesc, setAiDesc] = useState('');
  const [loading, setLoading] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [error, setError] = useState('');

  const loadPreview = async (expr: string) => {
    if (!expr) return;
    try {
      const data = await previewCron(expr, 3);
      setNextRuns(data.next_runs);
    } catch { /* ignore */ }
  };

  useEffect(() => { loadPreview(form.cron_expr); }, [form.cron_expr]);

  const handleAiParse = async () => {
    if (!aiDesc.trim()) return;
    setAiLoading(true);
    try {
      const data = await parseCron(aiDesc);
      setForm(f => ({ ...f, cron_expr: data.cron_expr }));
      setCronInput(data.cron_expr);
      await loadPreview(data.cron_expr);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'AI 解析失败');
    } finally {
      setAiLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) { setError('计划名称不能为空'); return; }
    if (!cronInput.trim()) { setError('Cron 表达式不能为空'); return; }
    setLoading(true);
    setError('');
    try {
      await onSave({ ...form, cron_expr: cronInput.trim() });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-[560px] max-h-[85vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-800">{schedule ? '编辑同步计划' : '新建同步计划'}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-lg">×</button>
        </div>
        <div className="px-6 py-4 space-y-4">
          {/* 名称 */}
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">计划名称 <span className="text-red-500">*</span></label>
            <input
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="例如：每日两次同步"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </div>
          {/* 描述 */}
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">描述</label>
            <input
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              placeholder="可选的描述信息"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </div>
          {/* 频率类型 + 执行模式 */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-[12px] font-medium text-slate-600 mb-1">频率</label>
              <select
                value={form.frequency_type}
                onChange={e => setForm(f => ({ ...f, frequency_type: e.target.value }))}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:ring-1 focus:ring-slate-400"
              >
                {FREQUENCY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div className="flex-1">
              <label className="block text-[12px] font-medium text-slate-600 mb-1">执行模式</label>
              <select
                value={form.execution_mode}
                onChange={e => setForm(f => ({ ...f, execution_mode: e.target.value }))}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:ring-1 focus:ring-slate-400"
              >
                {EXECUTION_MODE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>
          {/* 优先级 */}
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">优先级：{form.priority}（数值越大越优先）</label>
            <input
              type="range" min="1" max="100" value={form.priority}
              onChange={e => setForm(f => ({ ...f, priority: Number(e.target.value) }))}
              className="w-full"
            />
          </div>
          {/* AI 自然语言解析 */}
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">AI 解析 Cron（可选）</label>
            <div className="flex gap-2">
              <input
                value={aiDesc}
                onChange={e => setAiDesc(e.target.value)}
                placeholder='描述执行时间，例如 "每天凌晨两点"'
                className="flex-1 px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:ring-1 focus:ring-slate-400"
              />
              <button
                onClick={handleAiParse}
                disabled={aiLoading}
                className="px-3 py-2 bg-slate-800 text-white text-[12px] rounded-lg hover:bg-slate-700 disabled:opacity-50"
              >
                {aiLoading ? '解析中…' : 'AI 解析'}
              </button>
            </div>
          </div>
          {/* Cron 表达式 */}
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">Cron 表达式 <span className="text-red-500">*</span></label>
            <input
              value={cronInput}
              onChange={e => { setCronInput(e.target.value); setForm(f => ({ ...f, cron_expr: e.target.value })); }}
              placeholder="0 0 * * *"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] font-mono focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
            {/* 预览 */}
            {nextRuns.length > 0 && (
              <div className="mt-1.5 space-y-0.5">
                <p className="text-[11px] text-slate-400">接下来 3 次执行时间：</p>
                {nextRuns.map((t, i) => (
                  <p key={i} className="text-[11px] text-slate-500">{new Date(t).toLocaleString('zh-CN')}</p>
                ))}
              </div>
            )}
          </div>
          {/* 启用开关 */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setForm(f => ({ ...f, is_enabled: !f.is_enabled }))}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${form.is_enabled ? 'bg-emerald-500' : 'bg-slate-200'}`}
            >
              <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${form.is_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
            <span className="text-[12px] text-slate-600">{form.is_enabled ? '启用' : '禁用'}</span>
          </div>
          {error && <p className="text-[12px] text-red-500">{error}</p>}
        </div>
        <div className="px-6 py-4 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-[12px] text-slate-500 hover:text-slate-700">取消</button>
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="px-4 py-2 bg-slate-800 text-white text-[12px] rounded-lg hover:bg-slate-700 disabled:opacity-50"
          >
            {loading ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

interface BindDrawerProps {
  schedule: SyncSchedule;
  onClose: () => void;
}

function BindDrawer({ schedule, onClose }: BindDrawerProps) {
  const [connections, setConnections] = useState<TableauConnectionSimple[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchSyncSchedule(schedule.id);
        setConnections(data.connections || []);
        setSelected(new Set((data.connections || []).map(c => c.id)));
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : '加载失败');
      } finally {
        setLoading(false);
      }
    })();
  }, [schedule.id]);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const currentIds = new Set(connections.map(c => c.id));
      const toBind = [...selected].filter(id => !currentIds.has(id));
      const toUnbind = connections.filter(c => selected.has(c.id) === false).map(c => c.id);
      if (toBind.length > 0) await bindConnections(schedule.id, toBind);
      if (toUnbind.length > 0) await unbindConnections(schedule.id, toUnbind);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-stretch z-50">
      <div className="flex-1" onClick={onClose} />
      <div className="w-[420px] bg-white flex flex-col">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-800">管理引用连接：{schedule.name}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl">×</button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? <p className="text-[13px] text-slate-400 text-center py-8">加载中…</p> : (
            connections.length === 0 ? (
              <p className="text-[13px] text-slate-400 text-center py-8">暂无已绑定的连接</p>
            ) : (
              <div className="space-y-2">
                <p className="text-[11px] text-slate-400">已绑定 {connections.length} 个连接（点击可解绑）</p>
                {connections.map(conn => (
                  <div key={conn.id} className="flex items-center gap-2 p-2 rounded-lg border border-slate-200 hover:border-red-300 cursor-pointer"
                       onClick={() => toggle(conn.id)}>
                    <div className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${selected.has(conn.id) ? 'bg-slate-800 border-slate-800' : 'border-slate-300'}`}>
                      {selected.has(conn.id) && <span className="text-white text-[10px]">✓</span>}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-medium text-slate-700 truncate">{conn.name}</p>
                      <p className="text-[11px] text-slate-400 truncate">{conn.server_url}</p>
                    </div>
                    <span className={`text-[11px] px-1.5 py-0.5 rounded ${conn.auto_sync_enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>
                      {conn.auto_sync_enabled ? '自动' : '手动'}
                    </span>
                  </div>
                ))}
              </div>
            )
          )}
        </div>
        {error && <p className="px-5 py-2 text-[12px] text-red-500">{error}</p>}
        <div className="px-5 py-4 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-[12px] text-slate-500 hover:text-slate-700">取消</button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-slate-800 text-white text-[12px] rounded-lg hover:bg-slate-700 disabled:opacity-50"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SyncSchedulesTab() {
  const [schedules, setSchedules] = useState<SyncSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editSchedule, setEditSchedule] = useState<SyncSchedule | undefined>();
  const [showEdit, setShowEdit] = useState(false);
  const [bindSchedule, setBindSchedule] = useState<SyncSchedule | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const loadSchedules = async () => {
    setLoading(true);
    try {
      const data = await fetchSyncSchedules({ page, page_size: 20 });
      setSchedules(data.items);
      setTotal(data.total);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  /* eslint-disable react-hooks/exhaustive-deps -- loadSchedules intentionally stable for page change */
  useEffect(() => { loadSchedules(); }, [page]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const handleSave = async (form: ScheduleFormData) => {
    if (editSchedule) {
      await updateSyncSchedule(editSchedule.id, form);
    } else {
      await createSyncSchedule(form);
    }
    setShowEdit(false);
    setEditSchedule(undefined);
    await loadSchedules();
  };

  const handleToggle = async (s: SyncSchedule) => {
    await updateSyncSchedule(s.id, { is_enabled: !s.is_enabled });
    await loadSchedules();
  };

  const handleDelete = async (id: number) => {
    await deleteSyncSchedule(id);
    setDeleteConfirm(null);
    await loadSchedules();
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-semibold text-slate-700">同步计划</h2>
        <button
          onClick={() => { setEditSchedule(undefined); setShowEdit(true); }}
          className="flex items-center gap-1 px-3 py-1.5 bg-slate-800 text-white text-[12px] rounded-lg hover:bg-slate-700"
        >
          <span>+</span> 新建计划
        </button>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {['计划名称', '调度周期', '频率', '优先级', '模式', '引用连接', '状态', '下次执行', '操作'].map(h => (
                <th key={h} className="px-3 py-2 text-left text-[11px] font-medium text-slate-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="px-4 py-12 text-center text-slate-400 text-[13px]">加载中…</td></tr>
            ) : schedules.length === 0 ? (
              <tr><td colSpan={9} className="px-4 py-12 text-center text-slate-400 text-[13px]">暂无同步计划</td></tr>
            ) : schedules.map(s => (
              <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50/50">
                <td className="px-3 py-2.5">
                  <p className="text-[13px] font-medium text-slate-800">{s.name}</p>
                  {s.description && <p className="text-[11px] text-slate-400 mt-0.5">{s.description}</p>}
                </td>
                <td className="px-3 py-2.5">
                  <span className="text-[12px] text-slate-600 font-mono">{s.cron_expr}</span>
                  {s.cron_description && <p className="text-[11px] text-slate-400 mt-0.5">{s.cron_description}</p>}
                </td>
                <td className="px-3 py-2.5">
                  <span className="text-[12px] text-slate-600">{FREQUENCY_OPTIONS.find(o => o.value === s.frequency_type)?.label || s.frequency_type}</span>
                </td>
                <td className="px-3 py-2.5">
                  <span className="text-[12px] text-slate-600">{s.priority}</span>
                </td>
                <td className="px-3 py-2.5"><ModeBadge mode={s.execution_mode} /></td>
                <td className="px-3 py-2.5">
                  <button
                    onClick={() => setBindSchedule(s)}
                    className="text-[12px] text-blue-600 hover:text-blue-800 hover:underline"
                  >
                    {s.connection_count ?? 0} 个连接
                  </button>
                  {s.is_enabled && (s.connection_count ?? 0) === 0 && (
                    <p className="text-[10px] text-amber-500 mt-0.5" title="计划已启用但无绑定连接，不会产生任务">⚠ 无绑定连接</p>
                  )}
                </td>
                <td className="px-3 py-2.5"><StatusBadge enabled={s.is_enabled} /></td>
                <td className="px-3 py-2.5 text-[12px] text-slate-500">{formatDateTime(s.next_run_at ?? null)}</td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => { setEditSchedule(s); setShowEdit(true); }}
                      className="px-2 py-1 text-[11px] text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded"
                    >编辑</button>
                    <button
                      onClick={() => handleToggle(s)}
                      className={`px-2 py-1 text-[11px] rounded ${s.is_enabled ? 'text-amber-600 hover:text-amber-800 hover:bg-amber-50' : 'text-emerald-600 hover:text-emerald-800 hover:bg-emerald-50'}`}
                    >{s.is_enabled ? '禁用' : '启用'}</button>
                    <button
                      onClick={() => setDeleteConfirm(s.id)}
                      className="px-2 py-1 text-[11px] text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                    >删除</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > 20 && (
        <div className="flex items-center justify-between">
          <p className="text-[12px] text-slate-400">共 {total} 条</p>
          <div className="flex gap-1">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
              className="px-3 py-1 text-[12px] border border-slate-200 rounded hover:bg-slate-50 disabled:opacity-40">上一页</button>
            <button onClick={() => setPage(p => p + 1)} disabled={page * 20 >= total}
              className="px-3 py-1 text-[12px] border border-slate-200 rounded hover:bg-slate-50 disabled:opacity-40">下一页</button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && <p className="text-[12px] text-red-500">{error}</p>}

      {/* Edit Modal */}
      {showEdit && (
        <EditModal
          schedule={editSchedule}
          onSave={handleSave}
          onClose={() => { setShowEdit(false); setEditSchedule(undefined); }}
        />
      )}

      {/* Bind Drawer */}
      {bindSchedule && (
        <BindDrawer schedule={bindSchedule} onClose={() => { setBindSchedule(null); loadSchedules(); }} />
      )}

      {/* Delete Confirm */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-[360px] p-6">
            <h3 className="text-sm font-semibold text-slate-800 mb-2">确认删除</h3>
            <p className="text-[13px] text-slate-500 mb-4">删除后将无法恢复，确认删除此同步计划？</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeleteConfirm(null)} className="px-4 py-2 text-[12px] text-slate-500 hover:text-slate-700">取消</button>
              <button onClick={() => handleDelete(deleteConfirm)} className="px-4 py-2 bg-red-500 text-white text-[12px] rounded-lg hover:bg-red-600">删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
