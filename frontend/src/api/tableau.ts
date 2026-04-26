import { API_BASE } from '../config';

export interface TableauConnection {
  id: number;
  name: string;
  server_url: string;
  site: string;
  api_version: string;
  connection_type: 'mcp' | 'tsc';
  token_name: string;
  owner_id: number;
  is_active: boolean;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  last_test_at: string | null;
  last_test_success: boolean | null;
  last_test_message: string | null;
  last_sync_at: string | null;
  last_sync_duration_sec: number | null;
  sync_status: 'idle' | 'running' | 'failed';
  next_sync_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TableauAsset {
  id: number;
  connection_id: number;
  asset_type: 'workbook' | 'dashboard' | 'view' | 'datasource';
  tableau_id: string;
  name: string;
  project_name: string | null;
  description: string | null;
  owner_name: string | null;
  thumbnail_url: string | null;
  content_url: string | null;
  is_deleted: boolean;
  synced_at: string;
  // Phase 2a: hierarchy
  parent_workbook_id: string | null;
  parent_workbook_name: string | null;
  tags: string[] | null;
  sheet_type: string | null;
  created_on_server: string | null;
  updated_on_server: string | null;
  view_count: number | null;
  // AI
  ai_summary: string | null;
  ai_summary_generated_at: string | null;
  ai_explain: string | null;
  ai_explain_at: string | null;
  // Health
  health_score: number | null;
  field_count: number | null;
  is_certified: boolean | null;
  // Detail enrichment
  datasources?: TableauAssetDatasource[];
  server_url?: string;
}

export interface TableauAssetDatasource {
  id: number;
  asset_id: number;
  datasource_name: string;
  datasource_type: string | null;
}

export interface TableauSyncLog {
  id: number;
  connection_id: number;
  trigger_type: 'manual' | 'scheduled';
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'success' | 'partial' | 'failed';
  workbooks_synced: number;
  views_synced: number;
  dashboards_synced: number;
  datasources_synced: number;
  assets_deleted: number;
  error_message: string | null;
  duration_sec: number | null;
}

export interface ProjectNode {
  name: string;
  children: Record<string, { type: string; count: number }>;
}

export function extractErrorMessage(err: unknown, fallback: string): string {
  if (!err || typeof err !== 'object') return fallback;
  const e = err as Record<string, unknown>;
  if (typeof e.detail === 'string') return e.detail;
  if (e.detail && typeof e.detail === 'object') {
    const d = e.detail as Record<string, unknown>;
    if (typeof d.message === 'string') return d.message;
  }
  return fallback;
}

// Connections API

export async function listConnections(includeInactive = false): Promise<{ connections: TableauConnection[]; total: number }> {
  const sp = new URLSearchParams({ include_inactive: String(includeInactive) });
  const res = await fetch(`${API_BASE}/api/tableau/connections?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取连接列表失败');
  return res.json();
}

export async function createConnection(data: {
  name: string;
  server_url: string;
  site: string;
  api_version?: string;
  connection_type?: 'mcp' | 'tsc';
  token_name: string;
  token_value: string;
}): Promise<{ connection: TableauConnection; message: string }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(extractErrorMessage(err, '创建连接失败'));
  }
  return res.json();
}

export async function updateConnection(id: number, data: Partial<{
  name: string;
  server_url: string;
  site: string;
  api_version: string;
  connection_type: 'mcp' | 'tsc';
  token_name: string;
  token_value: string;
  is_active: boolean;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
}>): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(extractErrorMessage(err, '更新连接失败'));
  }
  return res.json();
}

export async function deleteConnection(id: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(extractErrorMessage(err, '删除连接失败'));
  }
  return res.json();
}

export async function testConnection(id: number): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${id}/test`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(extractErrorMessage(err, '测试连接失败'));
  }
  return res.json();
}

export async function syncConnection(id: number): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${id}/sync`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(extractErrorMessage(err, '同步失败'));
  }
  return res.json();
}

// Assets API

export async function listAssets(params: {
  connection_id: number;
  asset_type?: string;
  page?: number;
  page_size?: number;
}): Promise<{ assets: TableauAsset[]; total: number; page: number; page_size: number; pages: number }> {
  const sp = new URLSearchParams({
    connection_id: String(params.connection_id),
    ...(params.asset_type && { asset_type: params.asset_type }),
    ...(params.page && { page: String(params.page) }),
    ...(params.page_size && { page_size: String(params.page_size) }),
  });
  const res = await fetch(`${API_BASE}/api/tableau/assets?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取资产列表失败');
  return res.json();
}

export async function getAsset(id: number): Promise<TableauAsset> {
  const res = await fetch(`${API_BASE}/api/tableau/assets/${id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取资产详情失败');
  return res.json();
}

export async function searchAssets(params: {
  q: string;
  connection_id?: number;
  asset_type?: string;
  page?: number;
  page_size?: number;
}): Promise<{ assets: TableauAsset[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams({
    q: params.q,
    ...(params.connection_id && { connection_id: String(params.connection_id) }),
    ...(params.asset_type && { asset_type: params.asset_type }),
    ...(params.page && { page: String(params.page) }),
    ...(params.page_size && { page_size: String(params.page_size) }),
  });
  const res = await fetch(`${API_BASE}/api/tableau/assets/search?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('搜索资产失败');
  return res.json();
}

export async function getProjects(connection_id: number): Promise<{ projects: ProjectNode[] }> {
  const res = await fetch(`${API_BASE}/api/tableau/projects?connection_id=${connection_id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取项目列表失败');
  return res.json();
}

// Sync Logs API (Phase 2a)

export async function listSyncLogs(connId: number, params?: {
  page?: number;
  page_size?: number;
}): Promise<{ logs: TableauSyncLog[]; total: number; page: number; page_size: number; pages: number }> {
  const sp = new URLSearchParams({
    ...(params?.page && { page: String(params.page) }),
    ...(params?.page_size && { page_size: String(params.page_size) }),
  });
  const res = await fetch(`${API_BASE}/api/tableau/connections/${connId}/sync-logs?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取同步日志列表失败');
  return res.json();
}

export async function getSyncLog(connId: number, logId: number): Promise<TableauSyncLog> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${connId}/sync-logs/${logId}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取同步日志详情失败');
  return res.json();
}

export async function getSyncStatus(connId: number): Promise<{
  status: string;
  last_sync_at: string | null;
  last_sync_duration_sec: number | null;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  next_sync_at: string | null;
}> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${connId}/sync-status`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取同步状态失败');
  return res.json();
}

// Asset Hierarchy API (Phase 2a)

export async function getAssetChildren(assetId: number): Promise<{ children: TableauAsset[] }> {
  const res = await fetch(`${API_BASE}/api/tableau/assets/${assetId}/children`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取子资产失败');
  return res.json();
}

export async function getAssetParent(assetId: number): Promise<{ parent: TableauAsset | null }> {
  const res = await fetch(`${API_BASE}/api/tableau/assets/${assetId}/parent`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取父资产失败');
  return res.json();
}

// Deep AI Explain API (Phase 2a)

export async function explainAsset(assetId: number, refresh = false): Promise<{
  explain: string | null;
  cached: boolean;
  generated_at: string | null;
  error?: string;
  field_semantics?: { field: string; caption: string; role: string; data_type: string; meaning: string }[];
}> {
  const res = await fetch(`${API_BASE}/api/tableau/assets/${assetId}/explain`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) throw new Error('AI 解释生成失败');
  return res.json();
}

// Health Score API (Phase 2b)

export interface HealthCheck {
  key: string;
  label: string;
  weight: number;
  passed: boolean;
  detail: string;
}

export interface AssetHealth {
  score: number;
  level: 'excellent' | 'good' | 'warning' | 'poor';
  checks: HealthCheck[];
}

export interface HealthOverview {
  connection_id: number;
  connection_name: string;
  total_assets: number;
  avg_score: number;
  avg_level: string;
  level_distribution: { excellent: number; good: number; warning: number; poor: number };
  top_issues: { check: string; count: number }[];
  assets: { asset_id: number; name: string; asset_type: string; score: number; level: string }[];
}

export async function getAssetHealth(assetId: number): Promise<AssetHealth> {
  const res = await fetch(`${API_BASE}/api/tableau/assets/${assetId}/health`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取健康评分失败');
  return res.json();
}

export async function getConnectionHealthOverview(connId: number): Promise<HealthOverview> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${connId}/health-overview`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取健康概览失败');
  return res.json();
}
