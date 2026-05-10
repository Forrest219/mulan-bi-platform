import { useState, useEffect } from 'react';
import { fetchTaskQueue, type TaskQueueItem, type TaskQueueResponse } from '../../../api/tasks';

const STATUS_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  succeeded: { bg: 'bg-emerald-100', text: 'text-emerald-700', label: '成功' },
  failed: { bg: 'bg-red-100', text: 'text-red-700', label: '失败' },
  running: { bg: 'bg-blue-100', text: 'text-blue-700', label: '运行中' },
  pending: { bg: 'bg-slate-100', text: 'text-slate-500', label: '待执行' },
  cancelled: { bg: 'bg-amber-100', text: 'text-amber-700', label: '已取消' },
};

const RANGE_OPTIONS = [
  { label: '过去 24h / 未来 24h', past: 24, future: 24 },
  { label: '过去 7 天 / 未来 24h', past: 168, future: 24 },
  { label: '过去 24h / 未来 7 天', past: 24, future: 168 },
];

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDateOnly(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.bg} ${cfg.text}`}>
      {cfg.label}
    </span>
  );
}

export default function TaskQueueTab() {
  const [rangeIdx, setRangeIdx] = useState(0);
  const [data, setData] = useState<TaskQueueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    const opt = RANGE_OPTIONS[rangeIdx];
    setLoading(true);
    try {
      const result = await fetchTaskQueue(opt.past, opt.future);
      setData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  /* eslint-disable react-hooks/exhaustive-deps -- load intentionally stable for rangeIdx change */
  useEffect(() => { load(); }, [rangeIdx]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const pastItems = data?.items.filter(i => i.type === 'past') || [];
  const futureItems = data?.items.filter(i => i.type === 'future') || [];

  // Group future items by day for timeline display
  const groupedFuture: Record<string, TaskQueueItem[]> = {};
  for (const item of futureItems) {
    const day = formatDateOnly(item.scheduled_time);
    if (!groupedFuture[day]) groupedFuture[day] = [];
    groupedFuture[day].push(item);
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-semibold text-slate-700">执行队列</h2>
        <div className="flex gap-1">
          {RANGE_OPTIONS.map((opt, idx) => (
            <button
              key={idx}
              onClick={() => setRangeIdx(idx)}
              className={`px-3 py-1.5 text-[12px] rounded-lg transition-colors ${
                rangeIdx === idx
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      {data && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: '历史执行', value: data.past_count, color: 'text-slate-700' },
            { label: '历史成功率', value: data.past_count > 0
              ? `${Math.round((pastItems.filter(i => i.status === 'succeeded').length / pastItems.length) * 100)}%`
              : '—', color: 'text-emerald-600' },
            { label: '未来计划', value: data.future_count, color: 'text-slate-700' },
            { label: '失败任务', value: pastItems.filter(i => i.status === 'failed').length, color: 'text-red-600' },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-white rounded-xl border border-slate-200 px-4 py-3">
              <p className="text-[11px] text-slate-400 mb-1">{label}</p>
              <p className={`text-[20px] font-semibold ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {loading ? (
        <div className="bg-white rounded-xl border border-slate-200 py-16 text-center text-[13px] text-slate-400">加载中…</div>
      ) : error ? (
        <div className="bg-white rounded-xl border border-slate-200 py-8 text-center text-[13px] text-red-500">{error}</div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {/* 历史记录 */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center justify-between">
                <h3 className="text-[12px] font-semibold text-slate-700">历史执行</h3>
                <span className="text-[11px] text-slate-400">{data?.past_range}</span>
              </div>
            </div>
            <div className="overflow-y-auto max-h-[520px]">
              {pastItems.length === 0 ? (
                <p className="text-[13px] text-slate-400 text-center py-10">暂无历史执行记录</p>
              ) : (
                <table className="w-full">
                  <thead className="sticky top-0 bg-white">
                    <tr className="border-b border-slate-100">
                      {['执行时间', '计划', '状态', '耗时'].map(h => (
                        <th key={h} className="px-3 py-2 text-left text-[11px] font-medium text-slate-400">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pastItems.map((item, idx) => (
                      <tr key={idx} className="border-b border-slate-50 hover:bg-slate-50/50">
                        <td className="px-3 py-2 text-[12px] text-slate-600">{formatDateTime(item.scheduled_time)}</td>
                        <td className="px-3 py-2 text-[12px] text-slate-700 font-medium">{item.schedule_name}</td>
                        <td className="px-3 py-2"><StatusBadge status={item.status} /></td>
                        <td className="px-3 py-2 text-[12px] text-slate-500">{formatDuration(item.duration_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* 未来计划 */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center justify-between">
                <h3 className="text-[12px] font-semibold text-slate-700">未来计划</h3>
                <span className="text-[11px] text-slate-400">{data?.future_range}</span>
              </div>
            </div>
            <div className="overflow-y-auto max-h-[520px]">
              {futureItems.length === 0 ? (
                <p className="text-[13px] text-slate-400 text-center py-10">暂无未来计划</p>
              ) : (
                <table className="w-full">
                  <thead className="sticky top-0 bg-white">
                    <tr className="border-b border-slate-100">
                      {['预计时间', '计划', '连接数', '模式', '优先级'].map(h => (
                        <th key={h} className="px-3 py-2 text-left text-[11px] font-medium text-slate-400">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {futureItems.map((item, idx) => (
                      <tr key={idx} className="border-b border-slate-50 hover:bg-slate-50/50 border-l-2 border-l-dashed border-l-slate-200">
                        <td className="px-3 py-2 text-[12px] text-slate-500">{formatDateTime(item.scheduled_time)}</td>
                        <td className="px-3 py-2 text-[12px] text-slate-700 font-medium">{item.schedule_name}</td>
                        <td className="px-3 py-2 text-[12px] text-slate-600">{item.connection_count ?? '—'}</td>
                        <td className="px-3 py-2 text-[12px] text-slate-500">
                          {item.execution_mode === 'parallel' ? '并行' : '顺序'}
                        </td>
                        <td className="px-3 py-2 text-[12px] text-slate-500">{item.priority ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
