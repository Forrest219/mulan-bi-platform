const API_BASE = '';

export interface TableauConnection {
  id: number;
  name: string;
  server_url: string;
  site: string;
  api_version: string;
  token_name: string;
  owner_id: number;
  is_active: boolean;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  last_test_at: string | null;
  last_test_success: boolean | null;
  last_test_message: string | null;
  last_sync_at: string | null;
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
  datasources?: TableauAssetDatasource[];
}

export interface TableauAssetDatasource {
  id: number;
  asset_id: number;
  datasource_name: string;
  datasource_type: string | null;
}

export interface ProjectNode {
  name: string;
  children: Record<string, { type: string; count: number }>;
}

// Connections API

export async function listConnections(): Promise<{ connections: TableauConnection[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to fetch connections');
  return res.json();
}

export async function createConnection(data: {
  name: string;
  server_url: string;
  site: string;
  api_version?: string;
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
    const err = await res.json();
    throw new Error(err.detail || 'Failed to create connection');
  }
  return res.json();
}

export async function updateConnection(id: number, data: Partial<{
  name: string;
  server_url: string;
  site: string;
  api_version: string;
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
    const err = await res.json();
    throw new Error(err.detail || 'Failed to update connection');
  }
  return res.json();
}

export async function deleteConnection(id: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Failed to delete connection');
  }
  return res.json();
}

export async function testConnection(id: number): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${id}/test`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '测试请求失败' }));
    throw new Error(err.detail || '测试连接失败');
  }
  return res.json();
}

export async function syncConnection(id: number): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/api/tableau/connections/${id}/sync`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '同步请求失败' }));
    throw new Error(err.detail || '同步失败');
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
  if (!res.ok) throw new Error('Failed to fetch assets');
  return res.json();
}

export async function getAsset(id: number): Promise<TableauAsset> {
  const res = await fetch(`${API_BASE}/api/tableau/assets/${id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to fetch asset');
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
  if (!res.ok) throw new Error('Failed to search assets');
  return res.json();
}

export async function getProjects(connection_id: number): Promise<{ projects: ProjectNode[] }> {
  const res = await fetch(`${API_BASE}/api/tableau/projects?connection_id=${connection_id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to fetch projects');
  return res.json();
}
