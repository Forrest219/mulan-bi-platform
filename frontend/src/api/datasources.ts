import { API_BASE } from '../config';

export interface DataSource {
  id: number;
  name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  owner_id: number;
  is_active: boolean;
  extra_config: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateDataSourceInput {
  name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  password: string;
  extra_config?: Record<string, unknown>;
}

export interface UpdateDataSourceInput {
  name?: string;
  db_type?: string;
  host?: string;
  port?: number;
  database_name?: string;
  username?: string;
  password?: string;
  extra_config?: Record<string, unknown>;
  is_active?: boolean;
}

export async function listDataSources(): Promise<{ datasources: DataSource[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/datasources`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取数据源列表失败');
  return res.json();
}

export async function getDataSource(id: number): Promise<DataSource> {
  const res = await fetch(`${API_BASE}/api/datasources/${id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取数据源失败');
  return res.json();
}

export async function createDataSource(data: CreateDataSourceInput): Promise<{ datasource: DataSource; message: string }> {
  const res = await fetch(`${API_BASE}/api/datasources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '创建失败');
  }
  return res.json();
}

export async function updateDataSource(id: number, data: UpdateDataSourceInput): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/datasources/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '更新失败');
  }
  return res.json();
}

export async function deleteDataSource(id: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/datasources/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '删除失败');
  }
  return res.json();
}

export async function testDataSource(id: number): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/api/datasources/${id}/test`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '测试连接失败');
  }
  return res.json();
}

export const DB_TYPE_OPTIONS = [
  { value: 'mysql', label: 'MySQL' },
  { value: 'sqlserver', label: 'SQL Server' },
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'hive', label: 'Hive' },
  { value: 'starrocks', label: 'StarRocks' },
  { value: 'doris', label: 'Doris' },
];

export const DB_TYPE_PORT_DEFAULTS: Record<string, number> = {
  mysql: 3306,
  sqlserver: 1433,
  postgresql: 5432,
  hive: 10000,
  starrocks: 9030,
  doris: 9030,
};
