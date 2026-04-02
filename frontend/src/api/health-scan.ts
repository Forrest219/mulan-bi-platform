import { API_BASE } from '../config';

// Types
export interface HealthScan {
  id: number;
  datasource_id: number;
  datasource_name: string;
  db_type: string;
  database_name: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  started_at: string | null;
  finished_at: string | null;
  total_tables: number;
  total_issues: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  health_score: number | null;
  error_message: string | null;
  triggered_by: number | null;
  created_at: string;
}

export interface HealthIssue {
  id: number;
  scan_id: number;
  severity: 'high' | 'medium' | 'low';
  object_type: 'table' | 'field';
  object_name: string;
  database_name: string;
  issue_type: string;
  description: string;
  suggestion: string;
}

// API functions

export async function triggerScan(datasource_id: number): Promise<{ scan_id: number; message: string }> {
  const res = await fetch(`${API_BASE}/api/governance/health/scan`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ datasource_id }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '发起扫描失败');
  }
  return res.json();
}

export async function listScans(params?: {
  datasource_id?: number;
  page?: number;
  page_size?: number;
}): Promise<{ scans: HealthScan[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams();
  if (params?.datasource_id) sp.set('datasource_id', String(params.datasource_id));
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  const res = await fetch(`${API_BASE}/api/governance/health/scans?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取扫描历史失败');
  return res.json();
}

export async function getScan(scanId: number): Promise<HealthScan> {
  const res = await fetch(`${API_BASE}/api/governance/health/scans/${scanId}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取扫描详情失败');
  return res.json();
}

export async function getScanIssues(scanId: number, params?: {
  severity?: string;
  page?: number;
  page_size?: number;
}): Promise<{ issues: HealthIssue[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams();
  if (params?.severity) sp.set('severity', params.severity);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  const res = await fetch(`${API_BASE}/api/governance/health/scans/${scanId}/issues?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取问题列表失败');
  return res.json();
}

export async function downloadScanReport(scanId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/governance/health/scans/${scanId}/report`, { credentials: 'include' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '导出报告失败');
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `health-report-${scanId}.html`;
  a.click();
  URL.revokeObjectURL(url);
}

export async function getHealthSummary(): Promise<{ scans: HealthScan[] }> {
  const res = await fetch(`${API_BASE}/api/governance/health/summary`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取健康总览失败');
  return res.json();
}
