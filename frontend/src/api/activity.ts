import { API_BASE } from '../config';

export interface ActivityLog {
  id: number;
  op_time: string;
  operator: string;
  operator_id: number | null;
  operation_type: string;
  target: string;
  status: string;
  details: any;
  ip_address: string | null;
  user_agent: string | null;
  trace_id: string | null;
}

export interface ActivityLogsParams {
  page?: number;
  page_size?: number;
  operation_type?: string;
  start_time?: string;
  end_time?: string;
  user_id?: number;
}

export interface ActivityLogsResponse {
  logs: ActivityLog[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ActivityStatsResponse {
  total_users: number;
  active_users: number;
  tag_counts: Record<string, number>;
  active_rate: number;
  operation_stats?: Record<string, any>;
}

export interface ActivityTypesResponse {
  types: string[];
}

function buildSearchParams(params: ActivityLogsParams): URLSearchParams {
  const sp = new URLSearchParams();
  if (params.page) sp.set('page', String(params.page));
  if (params.page_size) sp.set('page_size', String(params.page_size));
  if (params.operation_type) sp.set('operation_type', params.operation_type);
  if (params.start_time) sp.set('start_time', params.start_time);
  if (params.end_time) sp.set('end_time', params.end_time);
  if (params.user_id) sp.set('user_id', String(params.user_id));
  return sp;
}

export async function getActivityLogs(params: ActivityLogsParams = {}): Promise<ActivityLogsResponse> {
  const sp = buildSearchParams(params);
  const resp = await fetch(`${API_BASE}/api/activity/logs?${sp.toString()}`, {
    credentials: 'include',
  });
  if (!resp.ok) throw new Error(`获取操作日志失败: ${resp.status}`);
  return resp.json();
}

export async function getActivityTypes(): Promise<string[]> {
  const resp = await fetch(`${API_BASE}/api/activity/types`, { credentials: 'include' });
  if (!resp.ok) throw new Error(`获取操作类型失败: ${resp.status}`);
  const data: ActivityTypesResponse = await resp.json();
  return data.types;
}

export async function getActivityStats(userId?: number): Promise<ActivityStatsResponse> {
  const sp = userId ? `?user_id=${userId}` : '';
  const resp = await fetch(`${API_BASE}/api/activity/stats${sp}`, { credentials: 'include' });
  if (!resp.ok) throw new Error(`获取活动统计失败: ${resp.status}`);
  return resp.json();
}

export async function exportActivityLogs(params: Omit<ActivityLogsParams, 'page' | 'page_size'> = {}): Promise<void> {
  const sp = buildSearchParams(params);
  const resp = await fetch(`${API_BASE}/api/activity/logs/export?${sp.toString()}`, {
    credentials: 'include',
  });
  if (!resp.ok) throw new Error(`导出失败: ${resp.status}`);

  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const disposition = resp.headers.get('Content-Disposition') || '';
  const filenameMatch = disposition.match(/filename\*?=['"]?(?:UTF-8'')?([^;\n]+)/i);
  a.download = filenameMatch ? decodeURIComponent(filenameMatch[1]) : `activity-logs-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}