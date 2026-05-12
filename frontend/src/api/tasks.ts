import { API_BASE } from '../config';

async function apiError(res: Response, fallback: string): Promise<Error> {
  const statusMsg: Record<number, string> = {
    403: '权限不足，当前账号无访问权限',
    404: '接口不存在，请确认数据库迁移已执行',
    500: '服务器内部错误，请检查后端日志',
  };
  if (statusMsg[res.status]) return new Error(statusMsg[res.status]);
  try {
    const err = await res.json();
    return new Error(err.detail?.message || err.detail || fallback);
  } catch {
    return new Error(`${fallback}（HTTP ${res.status}）`);
  }
}

// Types
export interface TaskSchedule {
  id: number;
  schedule_key: string;
  task_name: string;
  task_label: string;
  description: string;
  schedule_expr: string;
  cron_expr: string | null;
  is_enabled: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  next_run_at: string | null;
}

export interface TaskRun {
  id: number;
  celery_task_id: string | null;
  task_name: string;
  task_label: string | null;
  trigger_type: 'beat' | 'manual' | 'api';
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  result_summary: Record<string, unknown> | null;
  error_message: string | null;
  retry_count: number;
  parent_run_id: number | null;
  triggered_by: number | null;
  created_at: string;
}

export interface TaskStats {
  date: string;
  total_runs: number;
  succeeded: number;
  failed: number;
  running: number;
  success_rate: number;
  avg_duration_ms: number;
  comparison: {
    total_runs_delta: number;
    success_rate_delta: number;
    failed_delta: number;
  };
}

export interface TaskRunsParams {
  page?: number;
  page_size?: number;
  status?: string;
  task_name?: string;
  trigger_type?: string;
  start_time?: string;
  end_time?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ─── 同步计划（BiSyncSchedule） ────────────────────────────────

export interface SyncSchedule {
  id: number;
  name: string;
  description: string | null;
  frequency_type: string;  // hourly / daily / weekly / monthly
  cron_expr: string;
  priority: number;
  execution_mode: string;  // parallel / sequential
  is_enabled: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  // 计算字段（API 返回）
  cron_description?: string;
  next_run_at?: string | null;
  connection_count?: number;
  connections?: TableauConnectionSimple[];
}

export interface TableauConnectionSimple {
  id: number;
  name: string;
  server_url: string;
  site: string;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  schedule_id: number | null;
  last_sync_at: string | null;
  sync_status: string;
}

export interface TaskQueueItem {
  type: 'past' | 'future';
  scheduled_time: string;
  finished_at?: string | null;
  schedule_name: string;
  schedule_id?: number;
  status: string;
  duration_ms?: number | null;
  run_id?: number;
  task_name?: string;
  connection_count?: number;
  priority?: number;
  execution_mode?: string;
}

export interface TaskQueueResponse {
  items: TaskQueueItem[];
  past_count: number;
  future_count: number;
  past_range: string;
  future_range: string;
}

export type SyncScheduleListResponse = PaginatedResponse<SyncSchedule>;

// API functions — follow the exact pattern from health-scan.ts

export async function fetchTaskSchedules(): Promise<{ items: TaskSchedule[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/tasks/schedules`, { credentials: 'include' });
  if (!res.ok) throw await apiError(res, '获取定时任务列表失败');
  return res.json();
}

export async function fetchTaskRuns(params?: TaskRunsParams): Promise<PaginatedResponse<TaskRun>> {
  const sp = new URLSearchParams();
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  if (params?.status) sp.set('status', params.status);
  if (params?.task_name) sp.set('task_name', params.task_name);
  if (params?.trigger_type) sp.set('trigger_type', params.trigger_type);
  if (params?.start_time) sp.set('start_time', params.start_time);
  if (params?.end_time) sp.set('end_time', params.end_time);
  const res = await fetch(`${API_BASE}/api/tasks/runs?${sp}`, { credentials: 'include' });
  if (!res.ok) throw await apiError(res, '获取执行历史失败');
  return res.json();
}

export async function fetchTaskRunDetail(id: number): Promise<TaskRun> {
  const res = await fetch(`${API_BASE}/api/tasks/runs/${id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取执行详情失败');
  return res.json();
}

export async function fetchTaskStats(date?: string): Promise<TaskStats> {
  const sp = date ? `?date=${date}` : '';
  const res = await fetch(`${API_BASE}/api/tasks/stats${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取统计数据失败');
  return res.json();
}

export async function toggleSchedule(key: string, isEnabled: boolean): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/schedules/${key}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ is_enabled: isEnabled }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || '操作失败');
  }
}

export async function updateScheduleCron(key: string, cronExpr: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/schedules/${key}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ cron_expr: cronExpr }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || '保存失败');
  }
}

export async function triggerTask(taskName: string): Promise<{ celery_task_id: string }> {
  const res = await fetch(`${API_BASE}/api/tasks/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ task_name: taskName }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || '触发失败');
  }
  return res.json();
}

export async function parseCron(description: string): Promise<{ cron_expr: string; next_runs: string[] }> {
  const res = await fetch(`${API_BASE}/api/tasks/parse-cron`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ description }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || 'AI 解析失败');
  }
  return res.json();
}

export async function previewCron(cronExpr: string, n = 3): Promise<{ cron_expr: string; next_runs: string[] }> {
  const sp = new URLSearchParams({ cron_expr: cronExpr, n: String(n) });
  const res = await fetch(`${API_BASE}/api/tasks/preview-cron?${sp}`, { credentials: 'include' });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || 'Cron 预览失败');
  }
  return res.json();
}

// ─── 同步计划 API ───────────────────────────────────────────

export async function fetchSyncSchedules(params?: {
  page?: number; page_size?: number; enabled_only?: boolean;
}): Promise<SyncScheduleListResponse> {
  const sp = new URLSearchParams();
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  if (params?.enabled_only) sp.set('enabled_only', 'true');
  const res = await fetch(`${API_BASE}/api/tasks/sync-schedules?${sp}`, { credentials: 'include' });
  if (!res.ok) throw await apiError(res, '获取同步计划列表失败');
  return res.json();
}

export async function fetchSyncSchedule(id: number): Promise<SyncSchedule> {
  const res = await fetch(`${API_BASE}/api/tasks/sync-schedules/${id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取同步计划详情失败');
  return res.json();
}

export async function createSyncSchedule(data: {
  name: string; cron_expr: string; frequency_type: string;
  priority?: number; execution_mode?: string; description?: string;
}): Promise<SyncSchedule> {
  const res = await fetch(`${API_BASE}/api/tasks/sync-schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || '创建同步计划失败');
  }
  return res.json();
}

export async function updateSyncSchedule(
  id: number,
  data: Partial<{
    name: string; cron_expr: string; frequency_type: string;
    priority: number; execution_mode: string; description: string; is_enabled: boolean;
  }>,
): Promise<SyncSchedule> {
  const res = await fetch(`${API_BASE}/api/tasks/sync-schedules/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || '更新同步计划失败');
  }
  return res.json();
}

export async function deleteSyncSchedule(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/sync-schedules/${id}`, {
    method: 'DELETE', credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || '删除同步计划失败');
  }
}

export async function bindConnections(scheduleId: number, connectionIds: number[]): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/sync-schedules/${scheduleId}/bind`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ connection_ids: connectionIds }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || '绑定连接失败');
  }
}

export async function unbindConnections(scheduleId: number, connectionIds: number[]): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/sync-schedules/${scheduleId}/unbind`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ connection_ids: connectionIds }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || '解除绑定失败');
  }
}

export async function fetchTaskQueue(pastHours = 24, futureHours = 24): Promise<TaskQueueResponse> {
  const sp = new URLSearchParams({
    past_hours: String(pastHours),
    future_hours: String(futureHours),
  });
  const res = await fetch(`${API_BASE}/api/tasks/tasks/queue?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取任务队列失败');
  return res.json();
}

// ── Spec 43 同步任务清单 ──────────────────────────────────────────

export interface SyncTask {
  id: number;
  schedule_id: number | null;
  schedule_name: string;
  connection_id: number;
  connection_name: string;
  scheduled_at: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  trigger_type: 'scheduled' | 'manual';
  sync_log_id: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncTasksParams {
  schedule_id?: number;
  connection_id?: number;
  status?: string;
  date?: string;
  page?: number;
  page_size?: number;
}

export async function fetchSyncTasks(
  params?: SyncTasksParams,
): Promise<PaginatedResponse<SyncTask>> {
  const sp = new URLSearchParams();
  if (params?.schedule_id != null) sp.set('schedule_id', String(params.schedule_id));
  if (params?.connection_id != null) sp.set('connection_id', String(params.connection_id));
  if (params?.status) sp.set('status', params.status);
  if (params?.date) sp.set('date', params.date);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  const res = await fetch(`${API_BASE}/api/tasks/sync-tasks?${sp}`, { credentials: 'include' });
  if (!res.ok) throw await apiError(res, '获取任务清单失败');
  return res.json();
}
