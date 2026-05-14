import { API_BASE } from '../config';

export type ExplorerTableType = 'table' | 'view';
export type ExplorerTableTypeFilter = ExplorerTableType | 'all';
export type ExplorerSemanticRole = 'identifier' | 'time' | 'measure' | 'flag' | 'dimension';
export type ExplorerPermissionMode = 'connection_owner_summary';
export type ExplorerPermissionLevel = 'read_only';

export interface DataExplorerErrorBody {
  error_code?: string;
  message?: string;
  detail?: unknown;
}

export class DataExplorerApiError extends Error {
  errorCode?: string;
  detail?: unknown;
  status: number;

  constructor(status: number, body: DataExplorerErrorBody, fallbackMessage: string) {
    super(body.message || fallbackMessage);
    this.name = 'DataExplorerApiError';
    this.status = status;
    this.errorCode = body.error_code;
    this.detail = body.detail;
  }
}

export interface DataExplorerConnection {
  id: number;
  name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string | null;
  owner_id: number;
  is_active: boolean;
  last_tested_at: string | null;
  last_test_success: boolean | null;
  explorer_supported: boolean;
  unsupported_reason: string | null;
}

export interface DataExplorerConnectionDetail {
  id: number;
  name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string | null;
  username: string;
  is_active: boolean;
  last_tested_at: string | null;
  last_test_success: boolean | null;
}

export interface DataExplorerCapabilities {
  schemas: boolean;
  tables: boolean;
  columns: boolean;
  preview: boolean;
  permissions: ExplorerPermissionLevel;
}

export interface DataExplorerConnectionSummary {
  schema_count: number | null;
  table_count: number | null;
  view_count: number | null;
}

export interface DataExplorerConnectionOverview {
  connection: DataExplorerConnectionDetail;
  capabilities: DataExplorerCapabilities;
  summary: DataExplorerConnectionSummary;
}

export interface DataExplorerSchema {
  name: string;
  table_count: number | null;
  view_count: number | null;
}

export interface DataExplorerTable {
  schema: string;
  name: string;
  type: ExplorerTableType;
  comment: string | null;
  row_count: number | null;
  row_count_estimate?: number | null;
  column_count: number | null;
  table_ref: string;
}

export interface DataExplorerTableOverview {
  resource_id: string;
  schema: string;
  name: string;
  type: ExplorerTableType;
  comment: string | null;
  primary_key: string[];
  column_count: number | null;
  indexes_count: number | null;
  foreign_keys_count: number | null;
  row_count_estimate: number | null;
  data_size_bytes: number | null;
  index_size_bytes: number | null;
  total_size_bytes: number | null;
  created_at: string | null;
  table_updated_at: string | null;
  preview_available: boolean;
}

export interface DataExplorerColumn {
  name: string;
  data_type: string;
  nullable: boolean | null;
  default: string | null;
  comment: string | null;
  is_primary_key: boolean;
  is_indexed: boolean;
  semantic_role: ExplorerSemanticRole;
}

export interface DataExplorerPreviewColumn {
  name: string;
  data_type: string;
}

export interface DataExplorerPreview {
  columns: DataExplorerPreviewColumn[];
  rows: unknown[][];
  limit: number;
  truncated: boolean;
  execution_time_ms: number;
  redaction_applied: boolean;
}

export interface DataExplorerPermissions {
  resource_id: string;
  mode: ExplorerPermissionMode;
  current_user: {
    id: number;
    role: string;
    is_owner: boolean;
  };
  connection: {
    owner_id: number;
    owner_name: string | null;
  };
  effective_actions: {
    view_metadata: boolean;
    preview_rows: boolean;
    export: boolean;
    grant: boolean;
  };
  explanation: string[];
}

export interface DataExplorerTablesParams {
  schema?: string;
  q?: string;
  type?: ExplorerTableTypeFilter;
  limit?: number;
  offset?: number;
}

export interface DataExplorerPaginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

function buildQueryString(params: object): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

async function readJson<T>(res: Response, fallbackMessage: string): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new DataExplorerApiError(res.status, body as DataExplorerErrorBody, fallbackMessage);
  }
  return body as T;
}

function utf8ToBase64Url(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

export function encodeExplorerTableRef(schema: string, table: string): string {
  if (!schema || !table) {
    throw new Error('schema and table are required to build table_ref');
  }
  return utf8ToBase64Url(`${schema}\0${table}`);
}

export async function listDataExplorerConnections(): Promise<{ items: DataExplorerConnection[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/data-explorer/connections`, { credentials: 'include' });
  return readJson(res, '获取 Data Explorer 连接失败');
}

export async function getDataExplorerConnectionOverview(connectionId: number): Promise<DataExplorerConnectionOverview> {
  const res = await fetch(`${API_BASE}/api/data-explorer/connections/${connectionId}/overview`, { credentials: 'include' });
  return readJson(res, '获取连接概览失败');
}

export async function listDataExplorerSchemas(connectionId: number): Promise<{ items: DataExplorerSchema[] }> {
  const res = await fetch(`${API_BASE}/api/data-explorer/connections/${connectionId}/schemas`, { credentials: 'include' });
  return readJson(res, '获取 schema 列表失败');
}

export async function listDataExplorerTables(
  connectionId: number,
  params: DataExplorerTablesParams = {},
): Promise<DataExplorerPaginated<DataExplorerTable>> {
  const qs = buildQueryString(params);
  const res = await fetch(`${API_BASE}/api/data-explorer/connections/${connectionId}/tables${qs}`, { credentials: 'include' });
  return readJson(res, '获取 table 列表失败');
}

export async function getDataExplorerTableOverview(
  connectionId: number,
  tableRef: string,
): Promise<DataExplorerTableOverview> {
  const res = await fetch(`${API_BASE}/api/data-explorer/connections/${connectionId}/tables/${tableRef}/overview`, { credentials: 'include' });
  return readJson(res, '获取表概览失败');
}

export async function listDataExplorerColumns(
  connectionId: number,
  tableRef: string,
): Promise<{ items: DataExplorerColumn[] }> {
  const res = await fetch(`${API_BASE}/api/data-explorer/connections/${connectionId}/tables/${tableRef}/columns`, { credentials: 'include' });
  return readJson(res, '获取字段列表失败');
}

export async function getDataExplorerPreview(
  connectionId: number,
  tableRef: string,
  params: { limit?: number } = {},
): Promise<DataExplorerPreview> {
  const qs = buildQueryString({ limit: params.limit });
  const res = await fetch(`${API_BASE}/api/data-explorer/connections/${connectionId}/tables/${tableRef}/preview${qs}`, { credentials: 'include' });
  return readJson(res, '获取数据预览失败');
}

export async function getDataExplorerPermissions(
  connectionId: number,
  tableRef: string,
): Promise<DataExplorerPermissions> {
  const res = await fetch(`${API_BASE}/api/data-explorer/connections/${connectionId}/tables/${tableRef}/permissions`, { credentials: 'include' });
  return readJson(res, '获取权限摘要失败');
}
