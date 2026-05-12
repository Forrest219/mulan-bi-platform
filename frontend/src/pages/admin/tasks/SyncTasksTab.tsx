import { useState, useEffect, useCallback } from 'react';
import { fetchSyncTasks, type SyncTask, type SyncTasksParams } from '../../../api/tasks';

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待执行' },
  { value: 'running', label: '执行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'skipped', label: '已跳过' },
] as const;

const STATUS_STYLE: Record<string, { bg: string; text: string; dot: string }> = {
  pending:   { bg: 'bg-slate-100',   text: 'text-slate-500',   dot: 'bg-slate-400' },
  running:   { bg: 'bg-blue-100',    text: 'text-blue-700',    dot: 'bg-blue-500' },
  completed: { bg: 'bg-emerald-100', text: 'text-emerald-700', dot: 'bg-emerald-500' },
  failed:    { bg: 'bg-red-100',     text: 'text-red-700',     dot: 'bg-red-500' },
  skipped:   { bg: 'bg-amber-100',   text: 'text-amber-700',   dot: 'bg-amber-400' },
};

const STATUS_LABEL: Record<string, string> = {
  pending: '待执行', running: '执行中', completed: '已完成', failed: '失败', skipped: '已跳过',
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.pending;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium ${s.bg} ${s.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function SyncTasksTab() {
  const [tasks, setTasks] = useState<SyncTask[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [date, setDate] = useState(todayStr());
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params: SyncTasksParams = { date, page, page_size: PAGE_SIZE };
      if (status) params.status = status;
      const data = await fetchSyncTasks(params);
      setTasks(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [date, status, page]);

  useEffect(() => { load(); }, [load]);

  const pages = Math.ceil(total / PAGE_SIZE) || 1;

  // Count by status for summary pills
  const counts = tasks.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="bg-white rounded-xl border border-slate-200 px-4 py-3 flex flex-wrap items-center gap-4">
        {/* Date picker */}
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-slate-500 shrink-0">日期</span>
          <input
            type="date"
            value={date}
            onChange={(e) => { setDate(e.target.value); setPage(1); }}
            className="text-[12px] border border-slate-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
          />
        </div>

        {/* Status pills */}
        <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => { setStatus(opt.value); setPage(1); }}
              className={`px-3 py-1.5 text-[11px] font-medium rounded-md transition-colors ${
                status === opt.value
                  ? 'bg-white text-slate-700 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {opt.label}
              {opt.value && counts[opt.value] != null && (
                <span className="ml-1 opacity-60">{counts[opt.value]}</span>
              )}
            </button>
          ))}
        </div>

        <button
          onClick={() => load()}
          disabled={loading}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50"
        >
          <i className={`ri-refresh-line ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>

        <span className="text-[11px] text-slate-400">共 {total} 条</span>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-[12px] rounded-lg px-4 py-3 flex items-center justify-between">
          {error}
          <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">
            <i className="ri-close-line" />
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="text-left text-[11px] font-semibold text-slate-400 uppercase px-4 py-3 w-16">ID</th>
              <th className="text-left text-[11px] font-semibold text-slate-400 uppercase px-4 py-3">连接</th>
              <th className="text-left text-[11px] font-semibold text-slate-400 uppercase px-4 py-3">关联计划</th>
              <th className="text-left text-[11px] font-semibold text-slate-400 uppercase px-4 py-3">计划执行时间</th>
              <th className="text-left text-[11px] font-semibold text-slate-400 uppercase px-4 py-3">状态</th>
              <th className="text-left text-[11px] font-semibold text-slate-400 uppercase px-4 py-3">触发方式</th>
              <th className="text-left text-[11px] font-semibold text-slate-400 uppercase px-4 py-3">更新时间</th>
              <th className="text-left text-[11px] font-semibold text-slate-400 uppercase px-4 py-3">执行日志</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && tasks.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-slate-400 text-[13px]">
                  <i className="ri-loader-4-line animate-spin mr-2" />加载中…
                </td>
              </tr>
            ) : !error && tasks.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-16 text-center">
                  <i className="ri-calendar-check-line text-3xl text-slate-300 block mb-2" />
                  <span className="text-[13px] text-slate-400">
                    {date === todayStr() ? '今日暂无任务，请先运行"任务规划"或等待 00:05 自动生成' : '该日期暂无任务'}
                  </span>
                </td>
              </tr>
            ) : (
              tasks.map((t) => (
                <tr key={t.id} className="hover:bg-slate-50/50">
                  <td className="px-4 py-3">
                    <span className="text-[11px] text-slate-400 font-mono">#{t.id}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-[13px] font-medium text-slate-700">{t.connection_name || `#${t.connection_id}`}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-[12px] text-slate-500">{t.schedule_name || '—'}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-[12px] font-mono text-slate-600">{formatDateTime(t.scheduled_at)}</span>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={t.status} />
                    {t.error_message && (
                      <div className="mt-1 text-[11px] text-red-500 max-w-[200px] truncate" title={t.error_message}>
                        {t.error_message}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-[11px] px-1.5 py-0.5 rounded ${
                      t.trigger_type === 'manual'
                        ? 'bg-blue-50 text-blue-600'
                        : 'bg-slate-100 text-slate-500'
                    }`}>
                      {t.trigger_type === 'manual' ? '手动' : '定时'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-[11px] text-slate-400">{formatDateTime(t.updated_at)}</span>
                  </td>
                  <td className="px-4 py-3">
                    {t.sync_log_id ? (
                      <span className="text-[11px] font-mono text-blue-600">#{t.sync_log_id}</span>
                    ) : (
                      <span className="text-[11px] text-slate-300">—</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-400">第 {page} / {pages} 页</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-3 py-1.5 text-[12px] font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              上一页
            </button>
            <button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page >= pages}
              className="px-3 py-1.5 text-[12px] font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
