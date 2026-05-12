import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import {
  fetchTaskStats,
  fetchTaskSchedules,
  fetchTaskRuns,
  toggleSchedule,
  updateScheduleCron,
  triggerTask,
  parseCron,
  previewCron,
  type TaskStats,
  type TaskSchedule,
  type TaskRun,
  type TaskRunsParams,
} from '../../../api/tasks';

const SyncSchedulesTab = lazy(() => import('./SyncSchedulesTab'));
const SyncTasksTab    = lazy(() => import('./SyncTasksTab'));
const TaskQueueTab    = lazy(() => import('./TaskQueueTab'));

function formatDuration(ms: number | null): string {
  if (ms === null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { className: string; label: string }> = {
    succeeded: { className: 'bg-emerald-100 text-emerald-700', label: '成功' },
    running: { className: 'bg-blue-100 text-blue-700', label: '运行中' },
    failed: { className: 'bg-red-100 text-red-700', label: '失败' },
    pending: { className: 'bg-slate-100 text-slate-500', label: '等待中' },
    cancelled: { className: 'bg-amber-100 text-amber-700', label: '已取消' },
  };
  const { className, label } = map[status] || { className: 'bg-slate-100 text-slate-500', label: status };
  return <span className={`text-xs px-2 py-0.5 rounded-full ${className}`}>{label}</span>;
}

function EnabledBadge({ enabled }: { enabled: boolean }) {
  return enabled ? (
    <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">已启用</span>
  ) : (
    <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">已禁用</span>
  );
}

function TriggerBadge({ type }: { type: string }) {
  const map: Record<string, { className: string; label: string }> = {
    beat: { className: 'bg-slate-100 text-slate-600', label: '定时' },
    manual: { className: 'bg-blue-100 text-blue-600', label: '手动' },
    api: { className: 'bg-purple-100 text-purple-600', label: 'API' },
  };
  const { className, label } = map[type] || { className: 'bg-slate-100 text-slate-600', label: type };
  return <span className={`text-xs px-2 py-0.5 rounded-full ${className}`}>{label}</span>;
}

function DeltaIndicator({ value, suffix = '' }: { value: number; suffix?: string }) {
  if (value > 0) {
    return <span className="text-xs text-emerald-600">{'↑'} {value}{suffix}</span>;
  }
  if (value < 0) {
    return <span className="text-xs text-red-600">{'↓'} {Math.abs(value)}{suffix}</span>;
  }
  return <span className="text-xs text-slate-400">{'—'}</span>;
}

function CronEditModal({
  schedule,
  onClose,
  onSaved,
}: {
  schedule: TaskSchedule;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [description, setDescription] = useState('');
  const [parsing, setParsing] = useState(false);
  const [cronExpr, setCronExpr] = useState<string | null>(schedule.cron_expr ?? null);
  const [nextRuns, setNextRuns] = useState<string[]>([]);
  const [parseError, setParseError] = useState('');
  const [saving, setSaving] = useState(false);

  // Pre-populate next runs if schedule already has a cron_expr
  useEffect(() => {
    if (schedule.cron_expr) {
      previewCron(schedule.cron_expr, 6)
        .then((r) => setNextRuns(r.next_runs))
        .catch(() => {});
    }
  }, [schedule.cron_expr]);

  async function handleParse() {
    if (!description.trim()) return;
    setParsing(true);
    setParseError('');
    setNextRuns([]);
    setCronExpr(null);
    try {
      const result = await parseCron(description.trim());
      setCronExpr(result.cron_expr);
      // Fetch 6 runs for a richer confirmation view
      const preview = await previewCron(result.cron_expr, 6);
      setNextRuns(preview.next_runs);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'AI 解析失败');
    } finally {
      setParsing(false);
    }
  }

  async function handleSave() {
    if (!cronExpr) return;
    setSaving(true);
    setParseError('');
    try {
      await updateScheduleCron(schedule.schedule_key, cronExpr);
      onSaved();
    } catch (e) {
      setParseError(e instanceof Error ? e.message : '保存失败');
      setSaving(false);
    }
  }

  const confirmed = cronExpr !== null && nextRuns.length > 0;

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-base font-semibold text-slate-800">修改调度周期</h3>
            <p className="text-xs text-slate-400 mt-0.5">{schedule.task_label}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <i className="ri-close-line text-xl" />
          </button>
        </div>

        {/* Natural language input */}
        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-600 mb-1.5">用自然语言描述执行周期</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleParse()}
              placeholder="例如：每天凌晨三点、每6小时一次"
              className="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20"
            />
            <button
              onClick={handleParse}
              disabled={parsing || !description.trim()}
              className="px-4 py-2 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5 whitespace-nowrap"
            >
              {parsing ? (
                <i className="ri-loader-4-line animate-spin" />
              ) : (
                <i className="ri-sparkling-line" />
              )}
              AI 解析
            </button>
          </div>
        </div>

        {/* Confirmation: next run times */}
        {nextRuns.length > 0 && (
          <div className="mb-4 border border-slate-200 rounded-xl overflow-hidden">
            <div className="bg-slate-50 px-4 py-2.5 flex items-center justify-between">
              <span className="text-xs font-medium text-slate-600">解析结果 — 请确认以下执行时间是否正确</span>
              <i className="ri-calendar-check-line text-slate-400" />
            </div>
            <div className="divide-y divide-slate-100">
              {nextRuns.map((t, i) => {
                const d = new Date(t);
                const dateStr = `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
                const timeStr = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
                return (
                  <div key={i} className="px-4 py-2 flex items-center gap-3">
                    <span className="text-xs text-slate-400 w-4">{i + 1}</span>
                    <span className="text-sm font-mono text-slate-700">{dateStr}</span>
                    <span className="text-sm font-mono text-blue-600 font-medium">{timeStr}</span>
                  </div>
                );
              })}
            </div>
            {/* Cron expression as footnote */}
            {cronExpr && (
              <div className="px-4 py-2 bg-slate-50 border-t border-slate-100 flex items-center gap-1.5">
                <i className="ri-code-line text-slate-400 text-xs" />
                <code className="text-xs text-slate-400 font-mono">{cronExpr}</code>
              </div>
            )}
          </div>
        )}

        {/* Error */}
        {parseError && (
          <div className="mb-4 text-xs text-red-600 bg-red-50 rounded-lg p-3">
            {parseError}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !confirmed}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? '保存中...' : '确认保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminTasksPage() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<TaskStats | null>(null);
  const [schedules, setSchedules] = useState<TaskSchedule[]>([]);
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsPages, setRunsPages] = useState(0);
  const [activeTab, setActiveTab] = useState<'schedules' | 'history' | 'sync' | 'tasks' | 'queue'>('schedules');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [taskFilter, setTaskFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string>('');
  const [togglingKey, setTogglingKey] = useState<string | null>(null);
  const [triggeringKey, setTriggeringKey] = useState<string | null>(null);
  const [cronModalSchedule, setCronModalSchedule] = useState<TaskSchedule | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const params: TaskRunsParams = { page, page_size: 20 };
      if (statusFilter !== 'all') params.status = statusFilter;
      if (taskFilter) params.task_name = taskFilter;
      const data = await fetchTaskRuns(params);
      setRuns(data.items);
      setRunsTotal(data.total);
      setRunsPages(data.pages);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : '加载执行历史失败';
      setError(message);
    }
  }, [page, statusFilter, taskFilter]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  async function loadData() {
    try {
      setLoading(true);
      const [statsData, schedulesData, runsData] = await Promise.all([
        fetchTaskStats(),
        fetchTaskSchedules(),
        fetchTaskRuns({ page: 1, page_size: 20 }),
      ]);
      setStats(statsData);
      setSchedules(schedulesData.items);
      setRuns(runsData.items);
      setRunsTotal(runsData.total);
      setRunsPages(runsData.pages);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : '加载数据失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  // Collect unique task names from schedules for the filter dropdown
  const taskNames = Array.from(new Set(schedules.map((s) => s.task_name)));

  async function handleToggle(schedule: TaskSchedule) {
    setTogglingKey(schedule.schedule_key);
    setError('');
    try {
      await toggleSchedule(schedule.schedule_key, !schedule.is_enabled);
      await loadData();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : '切换任务状态失败';
      setError(message);
    } finally {
      setTogglingKey(null);
    }
  }

  async function handleTrigger(schedule: TaskSchedule) {
    setTriggeringKey(schedule.schedule_key);
    setError('');
    try {
      await triggerTask(schedule.task_name);
      await loadData();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : '触发任务失败';
      setError(message);
    } finally {
      setTriggeringKey(null);
    }
  }

  async function handleCronSaved() {
    setCronModalSchedule(null);
    await loadData();
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <span className="text-slate-400 text-[13px]">加载中…</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页头 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-task-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">任务管理</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">管理平台定时任务、同步计划与执行队列</p>
        </div>
      </div>

      {/* Tab strip */}
      <div className="bg-white border-b border-slate-100 px-8">
        <div className="flex gap-1 py-2">
          {([
            ['schedules', '平台任务'],
            ['history',   '执行历史'],
            ['sync',      '同步计划'],
            ['tasks',     '任务清单'],
            ['queue',     '执行队列'],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors ${
                activeTab === key
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto">
      {/* Error banner */}
      {error && (
        <div className="bg-red-50 text-red-700 border border-red-200 rounded-lg p-3 mb-4 text-[12px] flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">
            <i className="ri-close-line" />
          </button>
        </div>
      )}

      {/* KPI Stats row */}
      {stats && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          {/* 今日执行 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-blue-100 rounded-lg">
                <i className="ri-play-circle-line text-blue-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{stats.total_runs}</div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">今日执行</span>
                  <DeltaIndicator value={stats.comparison.total_runs_delta} />
                </div>
              </div>
            </div>
          </div>

          {/* 成功率 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-emerald-100 rounded-lg">
                <i className="ri-checkbox-circle-line text-emerald-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{stats.success_rate}%</div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">成功率</span>
                  <DeltaIndicator value={stats.comparison.success_rate_delta} suffix="%" />
                </div>
              </div>
            </div>
          </div>

          {/* 失败任务 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-red-100 rounded-lg">
                <i className="ri-error-warning-line text-red-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{stats.failed}</div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">失败任务</span>
                  <DeltaIndicator value={stats.comparison.failed_delta} />
                </div>
              </div>
            </div>
          </div>

          {/* 平均耗时 */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 flex items-center justify-center bg-amber-100 rounded-lg">
                <i className="ri-timer-line text-amber-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-800">{formatDuration(stats.avg_duration_ms)}</div>
                <div className="text-xs text-slate-500">平均耗时</div>
              </div>
            </div>
          </div>
        </div>
      )}


      {/* Tab 1: Schedules table */}
      {activeTab === 'schedules' && (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">任务名称</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">调度周期</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">状态</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">上次执行</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">上次状态</th>
                <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">下次执行</th>
                <th className="text-right text-xs font-semibold text-slate-500 uppercase px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {schedules.map((schedule) => (
                <tr key={schedule.id} className="hover:bg-slate-50/50">
                  <td className="px-4 py-3">
                    <div>
                      <div className="text-sm font-medium text-slate-700">{schedule.task_label}</div>
                      <div className="text-xs text-slate-400">{schedule.task_name}</div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div>
                        <div className="text-xs text-slate-500">{schedule.schedule_expr}</div>
                        {schedule.cron_expr && (
                          <code className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-mono">
                            {schedule.cron_expr}
                          </code>
                        )}
                      </div>
                      <button
                        onClick={() => setCronModalSchedule(schedule)}
                        className="text-slate-300 hover:text-blue-500 flex-shrink-0"
                        title="编辑调度周期"
                      >
                        <i className="ri-pencil-line text-sm" />
                      </button>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <EnabledBadge enabled={schedule.is_enabled} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-slate-500">{formatDateTime(schedule.last_run_at)}</span>
                  </td>
                  <td className="px-4 py-3">
                    {schedule.last_run_status ? (
                      <StatusBadge status={schedule.last_run_status} />
                    ) : (
                      <span className="text-xs text-slate-400">{'—'}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-slate-500">{formatDateTime(schedule.next_run_at)}</span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      disabled={togglingKey === schedule.schedule_key}
                      onClick={() => handleToggle(schedule)}
                      className={`text-xs mr-2 ${
                        togglingKey === schedule.schedule_key
                          ? 'text-slate-400 cursor-not-allowed'
                          : schedule.is_enabled
                            ? 'text-amber-600 hover:text-amber-700'
                            : 'text-blue-600 hover:text-blue-700'
                      }`}
                    >
                      {togglingKey === schedule.schedule_key
                        ? '...'
                        : schedule.is_enabled
                          ? '禁用'
                          : '启用'}
                    </button>
                    <button
                      disabled={triggeringKey === schedule.schedule_key}
                      onClick={() => handleTrigger(schedule)}
                      className={`text-xs ${
                        triggeringKey === schedule.schedule_key
                          ? 'text-slate-400 cursor-not-allowed'
                          : 'text-blue-600 hover:text-blue-700'
                      }`}
                    >
                      {triggeringKey === schedule.schedule_key ? '...' : '触发'}
                    </button>
                  </td>
                </tr>
              ))}
              {schedules.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-slate-400">
                    <i className="ri-calendar-schedule-line text-3xl mb-2 block" />
                    暂无定时任务
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 2: Runs table with filters */}
      {activeTab === 'history' && (
        <>
          {/* Filters */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 mb-4">
            <div className="flex items-center gap-4">
              {/* Status pills */}
              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-500">状态：</span>
                <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
                  {([
                    ['all', '全部'],
                    ['running', '运行中'],
                    ['succeeded', '成功'],
                    ['failed', '失败'],
                  ] as const).map(([value, label]) => (
                    <button
                      key={value}
                      onClick={() => { setStatusFilter(value); setPage(1); }}
                      className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                        statusFilter === value
                          ? 'bg-white text-slate-700 shadow-sm'
                          : 'text-slate-500 hover:text-slate-700'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Task name dropdown */}
              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-500">任务：</span>
                <select
                  value={taskFilter}
                  onChange={(e) => { setTaskFilter(e.target.value); setPage(1); }}
                  className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:border-blue-500"
                >
                  <option value="">全部任务</option>
                  {taskNames.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </div>

              {/* Total count */}
              <span className="ml-auto text-xs text-slate-400">共 {runsTotal} 条记录</span>
            </div>
          </div>

          {/* Table */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3 w-16">ID</th>
                  <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">任务</th>
                  <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">触发</th>
                  <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">状态</th>
                  <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">开始时间</th>
                  <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">耗时</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {runs.map((run) => (
                  <tr key={run.id} className="hover:bg-slate-50/50">
                    <td className="px-4 py-3">
                      <span className="text-xs text-slate-400 font-mono">#{run.id}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium text-slate-700">{run.task_label || run.task_name}</div>
                    </td>
                    <td className="px-4 py-3">
                      <TriggerBadge type={run.trigger_type} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs text-slate-500">{formatTime(run.started_at)}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs text-slate-500">{formatDuration(run.duration_ms)}</span>
                    </td>
                  </tr>
                ))}
                {runs.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-400">
                      <i className="ri-history-line text-3xl mb-2 block" />
                      暂无执行记录
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {runsPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <span className="text-xs text-slate-400">第 {page} / {runsPages} 页</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  上一页
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(runsPages, p + 1))}
                  disabled={page >= runsPages}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Tab 3: 同步计划 */}
      {activeTab === 'sync' && (
        <Suspense fallback={<div className="bg-white rounded-xl border border-slate-200 py-16 text-center text-[13px] text-slate-400">加载中…</div>}>
          <SyncSchedulesTab />
        </Suspense>
      )}

      {/* Tab 4: 任务清单 */}
      {activeTab === 'tasks' && (
        <Suspense fallback={<div className="bg-white rounded-xl border border-slate-200 py-16 text-center text-[13px] text-slate-400">加载中…</div>}>
          <SyncTasksTab />
        </Suspense>
      )}

      {/* Tab 5: 执行队列 */}
      {activeTab === 'queue' && (
        <Suspense fallback={<div className="bg-white rounded-xl border border-slate-200 py-16 text-center text-[13px] text-slate-400">加载中…</div>}>
          <TaskQueueTab />
        </Suspense>
      )}

      {/* Cron edit modal */}
      {cronModalSchedule && (
        <CronEditModal
          schedule={cronModalSchedule}
          onClose={() => setCronModalSchedule(null)}
          onSaved={handleCronSaved}
        />
      )}
        </div>
      </div>
    </div>
  );
}
