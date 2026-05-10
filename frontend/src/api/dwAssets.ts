import { API_BASE } from '../config';

// ============================================================
// 数据类型定义
// ============================================================

export interface DwDatabaseItem {
  datasource_id: number;
  name: string;
  db_type: string;
  host: string;
  table_count: number;
  total_storage_bytes: number;
  database_count: number;
  databases: string[];
  last_synced_at: string | null;
  sync_status: string | null;
}

export interface DwAssetTable {
  id: number;
  asset_uid: string;
  datasource_id: number;
  database_name: string;
  schema_name: string;
  table_name: string;
  business_name: string | null;
  description: string | null;
  table_type: string;
  domain: string | null;
  layer: string | null;
  tags: string[];
  row_count_estimate: number | null;
  storage_bytes: number | null;
  partition_key: string | null;
  partition_count: number | null;
  heat_score: number;
  query_count_7d: number;
  field_count: number;
  synced_at: string;
}

export interface DwAssetTableDetail {
  id: number;
  asset_uid: string;
  datasource: {
    id: number;
    name: string;
    db_type: string;
  };
  database_name: string;
  schema_name: string;
  table_name: string;
  business_name: string | null;
  description: string | null;
  table_comment: string | null;
  domain: string | null;
  layer: string | null;
  tags: string[];
  row_count_estimate: number | null;
  storage_bytes: number | null;
  partition_key: string | null;
  partition_count: number | null;
  last_partition_name: string | null;
  heat_score: number;
  lineage_summary: {
    upstream_count: number;
    downstream_count: number;
  };
  synced_at: string;
}

export interface DwAssetColumn {
  id: number;
  column_name: string;
  ordinal_position: number;
  data_type: string;
  normalized_type: string | null;
  is_nullable: boolean | null;
  is_primary_key: boolean;
  is_partition_key: boolean;
  is_business_key: boolean;
  column_comment: string | null;
  business_name: string | null;
  description: string | null;
  sensitivity_level: string;
  sample_values: unknown[];
}

export interface DwAssetPartition {
  id: number;
  partition_name: string;
  partition_value: string | null;
  row_count_estimate: number | null;
  storage_bytes: number | null;
  visible_version: string | null;
  updated_at: string;
}

export interface DwLineageNode {
  id: string;
  type: string;
  label: string;
  table_id: number;
  layer: string | null;
  heat_score: number;
}

export interface DwLineageEdge {
  id: string;
  source: string;
  target: string;
  relation_type: string;
  confidence: number;
}

export interface DwLineageData {
  nodes: DwLineageNode[];
  edges: DwLineageEdge[];
  center: string;
  depth: number;
}

export interface DwPreviewData {
  columns: { name: string; data_type: string }[];
  rows: Record<string, unknown>[];
  limit: number;
  truncated: boolean;
  masked_columns: string[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ============================================================
// 筛选参数类型
// ============================================================

export interface DwTablesParams {
  datasource_id?: number;
  database_name?: string;
  schema_name?: string;
  q?: string;
  domain?: string | string[];
  layer?: string;
  table_type?: string;
  sort?: string;
  page?: number;
  page_size?: number;
}

export interface DwColumnsParams {
  q?: string;
  sensitivity_level?: string;
  page?: number;
  page_size?: number;
}

export interface DwPartitionsParams {
  page?: number;
  page_size?: number;
}

export interface DwLineageParams {
  depth?: number;
  direction?: 'upstream' | 'downstream' | 'both';
  level?: 'table' | 'column';
}

// ============================================================
// 常量
// ============================================================

export const DW_LAYER_OPTIONS = [
  { value: '', label: '全部分层' },
  { value: 'ods', label: 'ODS' },
  { value: 'dim', label: 'DIM' },
  { value: 'dwd', label: 'DWD' },
  { value: 'dws', label: 'DWS' },
  { value: 'ads', label: 'ADS' },
  { value: 'other', label: '其他' },
];

export const DW_TABLE_TYPE_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'BASE TABLE', label: '基表' },
  { value: 'VIEW', label: '视图' },
  { value: 'MATERIALIZED_VIEW', label: '物化视图' },
];

export const DW_SORT_OPTIONS = [
  { value: 'heat_score', label: '热度排序' },
  { value: 'updated_at', label: '更新时间' },
  { value: 'table_name', label: '表名排序' },
];

// ============================================================
// API 函数
// ============================================================

function buildQueryString(params: object): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item !== undefined && item !== null && item !== '') {
          parts.push(`${k}=${encodeURIComponent(String(item))}`);
        }
      }
    } else {
      parts.push(`${k}=${encodeURIComponent(String(v))}`);
    }
  }
  return parts.length === 0 ? '' : '?' + parts.join('&');
}

/** 获取可浏览的数据源/库列表 */
export async function listDwDatabases(params?: { db_type?: string; q?: string }): Promise<{ items: DwDatabaseItem[]; total: number }> {
  const qs = buildQueryString(params || {});
  const res = await fetch(`${API_BASE}/api/assets/dw/databases${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取数据源列表失败');
  return res.json();
}

/** 获取数仓表清单（分页过滤） */
export async function listDwTables(params?: DwTablesParams): Promise<PaginatedResponse<DwAssetTable>> {
  const qs = buildQueryString(params || {});
  const res = await fetch(`${API_BASE}/api/assets/dw/tables${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取数仓资产列表失败');
  return res.json();
}

/** 获取表详情 */
export async function getDwTableDetail(tableId: number): Promise<DwAssetTableDetail> {
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取数仓表详情失败');
  return res.json();
}

/** 获取字段元数据 */
export async function listDwColumns(tableId: number, params?: DwColumnsParams): Promise<PaginatedResponse<DwAssetColumn>> {
  const qs = buildQueryString(params || {});
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/columns${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取字段列表失败');
  return res.json();
}

/** 获取分区信息 */
export async function listDwPartitions(tableId: number, params?: DwPartitionsParams): Promise<PaginatedResponse<DwAssetPartition>> {
  const qs = buildQueryString(params || {});
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/partitions${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取分区信息失败');
  return res.json();
}

/** 获取血缘拓扑 */
export async function getDwLineage(tableId: number, params?: DwLineageParams): Promise<DwLineageData> {
  const qs = buildQueryString(params || {});
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/lineage${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取血缘信息失败');
  return res.json();
}

/** 获取数据预览 */
export async function getDwPreview(tableId: number, params?: { limit?: number; columns?: string }): Promise<DwPreviewData> {
  const qs = buildQueryString(params || {});
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/preview${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取数据预览失败');
  return res.json();
}

/** 生成 Data Agent 上下文 */
export async function createAgentContext(tableId: number, data: { intent: string; selected_columns?: string[] }): Promise<{ context: unknown; event_id: string }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/agent-context`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('生成 Agent 上下文失败');
  return res.json();
}

// ============================================================
// 写操作 API
// ============================================================

/** 搜索表/字段（autocomplete） */
export async function searchDwAssets(params: { q: string; scope?: string; datasource_id?: number; limit?: number }): Promise<{ items: unknown[]; total: number }> {
  const qs = buildQueryString(params);
  const res = await fetch(`${API_BASE}/api/assets/dw/search${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('搜索数仓资产失败');
  return res.json();
}

/** 更新表的治理字段（业务名、描述、主题域、标签） */
export async function updateDwTable(tableId: number, data: {
  business_name?: string;
  description?: string;
  domain?: string;
  layer?: string;
  tags?: string[];
}): Promise<{ message: string; table: DwAssetTableDetail }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('更新数仓表信息失败');
  return res.json();
}

/** 更新单个字段的治理信息 */
export async function updateDwColumn(tableId: number, columnId: number, data: {
  business_name?: string;
  description?: string;
  sensitivity_level?: string;
  is_business_key?: boolean;
}): Promise<{ message: string; column: DwAssetColumn }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/columns/${columnId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('更新字段信息失败');
  return res.json();
}

/** 批量更新字段治理信息 */
export async function batchUpdateDwColumns(tableId: number, items: Array<{
  column_id: number;
  business_name?: string;
  description?: string;
  sensitivity_level?: string;
}>): Promise<{ message: string; updated_count: number }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/columns`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ items }),
  });
  if (!res.ok) throw new Error('批量更新字段信息失败');
  return res.json();
}

/** 新增手工血缘 */
export async function createDwLineage(tableId: number, data: {
  lineage_type: string;
  source_table_id: number;
  target_table_id?: number;
  relation_type: string;
  transformation_logic?: string;
}): Promise<{ message: string; edge: unknown }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/lineage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('创建血缘关系失败');
  return res.json();
}

/** 删除手工血缘 */
export async function deleteDwLineage(tableId: number, edgeId: number): Promise<{ message: string; success: boolean }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/lineage/${edgeId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('删除血缘关系失败');
  return res.json();
}

/** 触发元数据同步 */
export async function triggerDwSync(datasourceId: number, data: {
  mode: string;
  include_partitions: boolean;
}): Promise<{ sync_run_id: number; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/datasources/${datasourceId}/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('触发同步失败');
  return res.json();
}

/** 获取同步历史 */
export async function listDwSyncRuns(params?: {
  datasource_id?: number;
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<{ id: number; datasource_id: number; trigger_type: string; status: string; started_at: string; finished_at: string | null; tables_found: number; tables_upserted: number; columns_upserted: number; error_message: string | null }>> {
  const qs = buildQueryString(params || {});
  const res = await fetch(`${API_BASE}/api/assets/dw/sync-runs${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取同步历史失败');
  return res.json();
}

export interface DomainValueItem {
  l1: string;
  l2_list: string[];
  description?: string | null;
}

/** 主题域层级配置项 */
export interface DwDomainTaxonomyItem {
  id: number;
  l1: string;
  l2: string | null;
  description?: string | null;
  display_order: number;
}

/** 获取主题域层级配置列表（仅 admin/data_admin） */
export async function listDwDomainTaxonomy(): Promise<{ items: DwDomainTaxonomyItem[] }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/domain-taxonomy`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取主题域配置失败');
  return res.json();
}

/** 新增主题域配置 */
export async function createDwDomainTaxonomy(data: { l1: string; l2?: string | null }): Promise<DwDomainTaxonomyItem> {
  const res = await fetch(`${API_BASE}/api/assets/dw/domain-taxonomy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('创建主题域失败');
  return res.json();
}

/** 删除主题域配置 */
export async function deleteDwDomainTaxonomy(taxonomyId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/api/assets/dw/domain-taxonomy/${taxonomyId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('删除主题域失败');
}

/** 获取 LLM 治理建议（business_name / description） */
export async function getDwTableSuggestions(tableId: number): Promise<{ business_name: string | null; description: string | null }> {
  const res = await fetch(`${API_BASE}/api/assets/dw/tables/${tableId}/suggestions`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取 AI 建议失败');
  return res.json();
}

/** 获取已使用的 domain 值，用于构造级联选择器 */
export async function fetchDomainValues(datasource_id?: number): Promise<{ items: DomainValueItem[]; values: string[] }> {
  const qs = datasource_id ? `?datasource_id=${datasource_id}` : '';
  const res = await fetch(`${API_BASE}/api/assets/dw/domain-values${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取主题域列表失败');
  return res.json();
}
