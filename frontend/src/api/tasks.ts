import { API_BASE } from '../config';

// Types
export interface TaskSchedule {
  id: number;
  schedule_key: string;
  task_name: string;
  task_label: string;
  description: string;
  schedule_expr: string;
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

// API functions — follow the exact pattern from health-scan.ts

export async function fetchTaskSchedules(): Promise<{ items: TaskSchedule[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/tasks/schedules`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取定时任务列表失败');
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
  if (!res.ok) throw new Error('获取执行历史失败');
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
