import { API_BASE } from '../config';

// Types
export type SemanticStatus = 'draft' | 'ai_generated' | 'pending_review' | 'reviewed' | 'approved' | 'rejected' | 'published';
export type SensitivityLevel = 'low' | 'medium' | 'high' | 'confidential';
export type PublishStatus = 'pending' | 'success' | 'failed' | 'rolled_back';

export interface SemanticDatasource {
  id: number;
  connection_id: number;
  tableau_datasource_id: string;
  field_registry_id: number | null;
  semantic_name: string | null;
  semantic_name_zh: string | null;
  semantic_description: string | null;
  metric_definition: string | null;
  dimension_definition: string | null;
  sensitivity_level: SensitivityLevel | null;
  status: SemanticStatus;
  source: string;
  is_core_field: boolean;
  published_to_tableau: boolean;
  published_at: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  created_by: number;
  created_at: string;
  updated_at: string;
}

export interface SemanticField {
  id: number;
  connection_id: number;
  tableau_field_id: string;
  field_registry_id: number | null;
  semantic_name: string | null;
  semantic_name_zh: string | null;
  semantic_definition: string | null;
  metric_definition: string | null;
  dimension_definition: string | null;
  unit: string | null;
  enum_desc_json: string | null;
  tags_json: string | null;
  synonyms_json: string | null;
  sensitivity_level: SensitivityLevel | null;
  is_core_field: boolean;
  status: SemanticStatus;
  source: string;
  published_to_tableau: boolean;
  published_at: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  created_by: number;
  created_at: string;
  updated_at: string;
}

export interface PublishLog {
  id: number;
  connection_id: number;
  object_type: 'datasource' | 'field';
  object_id: number;
  operator: number;
  tableau_object_id: string;
  status: PublishStatus;
  diff_json: string | null;
  payload_json: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface SemanticVersion {
  id: number;
  entity_type: 'datasource' | 'field';
  entity_id: number;
  version_num: number;
  snapshot_json: string;
  changed_by: number;
  changed_at: string;
  change_summary: string | null;
}

// Datasources API

export async function listDatasourceSemantics(params: {
  connection_id: number;
  status?: SemanticStatus;
  page?: number;
  page_size?: number;
}): Promise<{ items: SemanticDatasource[]; total: number; page: number; page_size: number; pages: number }> {
  const sp = new URLSearchParams({
    connection_id: String(params.connection_id),
    ...(params.status && { status: params.status }),
    ...(params.page && { page: String(params.page) }),
    ...(params.page_size && { page_size: String(params.page_size) }),
  });
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取数据源语义失败');
  return res.json();
}

export async function getDatasourceSemantics(id: number): Promise<SemanticDatasource> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources/${id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取数据源语义失败');
  return res.json();
}

export async function createDatasourceSemantics(data: {
  connection_id: number;
  tableau_datasource_id: string;
  field_registry_id?: number;
  semantic_name?: string;
  semantic_name_zh?: string;
  semantic_description?: string;
  metric_definition?: string;
  dimension_definition?: string;
  sensitivity_level?: SensitivityLevel;
  is_core_field?: boolean;
}): Promise<{ item: SemanticDatasource; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '创建数据源语义失败');
  }
  return res.json();
}

export async function updateDatasourceSemantics(id: number, data: Partial<{
  semantic_name: string;
  semantic_name_zh: string;
  semantic_description: string;
  metric_definition: string;
  dimension_definition: string;
  sensitivity_level: SensitivityLevel;
  is_core_field: boolean;
}>): Promise<{ item: SemanticDatasource; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '更新数据源语义失败');
  }
  return res.json();
}

export async function submitDatasourceForReview(id: number): Promise<{ item: SemanticDatasource; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources/${id}/submit-review`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '提交审核失败');
  }
  return res.json();
}

export async function approveDatasource(id: number): Promise<{ item: SemanticDatasource; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources/${id}/approve`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '审批失败');
  }
  return res.json();
}

export async function rejectDatasource(id: number): Promise<{ item: SemanticDatasource; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources/${id}/reject`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '驳回失败');
  }
  return res.json();
}

export async function getDatasourceVersions(id: number): Promise<{ versions: SemanticVersion[] }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources/${id}/versions`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取版本历史失败');
  return res.json();
}

export async function rollbackDatasource(id: number, versionId: number): Promise<{ item: SemanticDatasource; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources/${id}/rollback/${versionId}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '回滚失败');
  }
  return res.json();
}

export async function generateDatasourceAI(id: number, data?: {
  description?: string;
  name_zh?: string;
}): Promise<{ item: SemanticDatasource; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/datasources/${id}/generate-ai`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data || {}),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'AI 生成失败');
  }
  return res.json();
}

// Fields API

export async function listFieldSemantics(params: {
  connection_id: number;
  ds_id?: number;
  status?: SemanticStatus;
  page?: number;
  page_size?: number;
}): Promise<{ items: SemanticField[]; total: number; page: number; page_size: number; pages: number }> {
  const sp = new URLSearchParams({
    connection_id: String(params.connection_id),
    ...(params.ds_id && { ds_id: String(params.ds_id) }),
    ...(params.status && { status: params.status }),
    ...(params.page && { page: String(params.page) }),
    ...(params.page_size && { page_size: String(params.page_size) }),
  });
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取字段语义失败');
  return res.json();
}

export async function getFieldSemantics(id: number): Promise<SemanticField> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields/${id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取字段语义失败');
  return res.json();
}

export async function createFieldSemantics(data: {
  connection_id: number;
  tableau_field_id: string;
  field_registry_id?: number;
  semantic_name?: string;
  semantic_name_zh?: string;
  semantic_definition?: string;
  metric_definition?: string;
  dimension_definition?: string;
  unit?: string;
  enum_desc_json?: string;
  tags_json?: string;
  synonyms_json?: string;
  sensitivity_level?: SensitivityLevel;
  is_core_field?: boolean;
}): Promise<{ item: SemanticField; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '创建字段语义失败');
  }
  return res.json();
}

export async function updateFieldSemantics(id: number, data: Partial<{
  semantic_name: string;
  semantic_name_zh: string;
  semantic_definition: string;
  metric_definition: string;
  dimension_definition: string;
  unit: string;
  enum_desc_json: string;
  tags_json: string;
  synonyms_json: string;
  sensitivity_level: SensitivityLevel;
  is_core_field: boolean;
}>): Promise<{ item: SemanticField; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '更新字段语义失败');
  }
  return res.json();
}

export async function submitFieldForReview(id: number): Promise<{ item: SemanticField; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields/${id}/submit-review`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '提交审核失败');
  }
  return res.json();
}

export async function approveField(id: number): Promise<{ item: SemanticField; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields/${id}/approve`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '审批失败');
  }
  return res.json();
}

export async function rejectField(id: number): Promise<{ item: SemanticField; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields/${id}/reject`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '驳回失败');
  }
  return res.json();
}

export async function getFieldVersions(id: number): Promise<{ versions: SemanticVersion[] }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields/${id}/versions`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取版本历史失败');
  return res.json();
}

export async function rollbackField(id: number, versionId: number): Promise<{ item: SemanticField; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields/${id}/rollback/${versionId}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '回滚失败');
  }
  return res.json();
}

export async function generateFieldAI(id: number, data?: {
  field_name?: string;
  data_type?: string;
  role?: string;
  formula?: string;
  enum_values?: string[];
}): Promise<{ item: SemanticField; message: string }> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/fields/${id}/generate-ai`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data || {}),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'AI 生成失败');
  }
  return res.json();
}

// Publish API

export interface DiffPreview {
  object_type: 'datasource' | 'field';
  object_id: number;
  tableau_id: string;
  tableau_current: Record<string, any>;
  mulan_pending: Record<string, any>;
  diff: Record<string, { tableau: any; mulan: any }>;
  sensitivity_level: SensitivityLevel | null;
  can_publish: boolean;
}

export async function previewDatasourceDiff(connectionId: number, dsId: number): Promise<DiffPreview> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish/diff`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ connection_id: connectionId, object_type: 'datasource', object_id: dsId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '差异预览失败');
  }
  return res.json();
}

export async function previewFieldDiff(connectionId: number, fieldId: number): Promise<DiffPreview> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish/diff`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ connection_id: connectionId, object_type: 'field', object_id: fieldId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '差异预览失败');
  }
  return res.json();
}

export async function publishDatasource(connectionId: number, dsId: number, simulate = false): Promise<any> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish/datasource`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ connection_id: connectionId, ds_id: dsId, simulate }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '发布数据源失败');
  }
  return res.json();
}

export async function publishFields(connectionId: number, fieldIds: number[], simulate = false): Promise<any> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish/fields`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ connection_id: connectionId, field_ids: fieldIds, simulate }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '发布字段失败');
  }
  return res.json();
}

export async function retryPublish(logId: number, connectionId: number): Promise<any> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish/retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ log_id: logId, connection_id: connectionId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '重试发布失败');
  }
  return res.json();
}

export async function rollbackPublish(logId: number, connectionId: number): Promise<any> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ log_id: logId, connection_id: connectionId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '回滚发布失败');
  }
  return res.json();
}

// Publish Logs API (Spec 19)

export interface PublishLogListParams {
  page?: number;
  page_size?: number;
  connection_id?: number;
  object_type?: 'datasource' | 'field';
  status?: string;
  operator_id?: number;
  start_date?: string;
  end_date?: string;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

export interface PublishLogOperator {
  id: number;
  username: string;
  display_name: string;
}

export interface PublishLogDiffSummary {
  changed_fields: string[];
  total_changes: number;
  is_rollback?: boolean;
}

export interface PublishLogListItem {
  id: number;
  connection_id: number;
  connection_name: string | null;
  object_type: 'datasource' | 'field';
  object_id: number;
  object_name: string | null;
  tableau_object_id: string | null;
  status: 'pending' | 'success' | 'failed' | 'rolled_back' | 'not_supported';
  response_summary: string | null;
  operator: PublishLogOperator | null;
  diff_summary: PublishLogDiffSummary;
  created_at: string;
}

export interface PublishLogDetail extends PublishLogListItem {
  target_system: string;
  publish_payload: Record<string, unknown> | null;
  diff: Record<string, { tableau: string | null; mulan: string | null }> | null;
  rollback_diff: Record<string, string> | null;
  can_rollback: boolean;
  related_logs: Array<{
    id: number;
    status: string;
    created_at: string;
  }>;
}

export async function listPublishLogs(params?: PublishLogListParams): Promise<{
  items: PublishLogListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}> {
  const sp = new URLSearchParams();
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  if (params?.connection_id) sp.set('connection_id', String(params.connection_id));
  if (params?.object_type) sp.set('object_type', params.object_type);
  if (params?.status) sp.set('status', params.status);
  if (params?.operator_id) sp.set('operator_id', String(params.operator_id));
  if (params?.start_date) sp.set('start_date', params.start_date);
  if (params?.end_date) sp.set('end_date', params.end_date);
  if (params?.sort_by) sp.set('sort_by', params.sort_by);
  if (params?.sort_order) sp.set('sort_order', params.sort_order);

  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish-logs?${sp}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取发布日志失败');
  return res.json();
}

export async function getPublishLogDetail(logId: number): Promise<PublishLogDetail> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish-logs/${logId}`, { credentials: 'include' });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '获取发布日志详情失败');
  }
  return res.json();
}

// Sync API

export async function syncFields(connectionId: number, tableauDatasourceId: string, assetId?: number, force = false): Promise<{
  message: string;
  connection_id: number;
  tableau_datasource_id: string;
  asset_id: number;
  status: string;
  synced: number;
  skipped: number;
  errors: string[];
}> {
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/connections/${connectionId}/sync-fields`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ tableau_datasource_id: tableauDatasourceId, asset_id: assetId, force }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '同步字段失败');
  }
  return res.json();
}

// Status badge helper
export function getStatusBadge(status: SemanticStatus): { text: string; className: string } {
  const map: Record<SemanticStatus, { text: string; className: string }> = {
    draft: { text: '草稿', className: 'bg-slate-100 text-slate-600' },
    ai_generated: { text: 'AI 已生成', className: 'bg-violet-50 text-violet-600' },
    pending_review: { text: '待审核', className: 'bg-amber-50 text-amber-600' },
    reviewed: { text: '待审核', className: 'bg-amber-50 text-amber-600' },
    approved: { text: '已审核', className: 'bg-emerald-50 text-emerald-600' },
    rejected: { text: '已驳回', className: 'bg-red-50 text-red-600' },
    published: { text: '已发布', className: 'bg-blue-50 text-blue-600' },
  };
  return map[status] || { text: status, className: 'bg-slate-100 text-slate-600' };
}

export function getSensitivityBadge(level: SensitivityLevel | null): { text: string; className: string } {
  if (!level) return { text: '-', className: 'bg-slate-50 text-slate-400' };
  const map: Record<SensitivityLevel, { text: string; className: string }> = {
    low: { text: '低', className: 'bg-emerald-50 text-emerald-600' },
    medium: { text: '中', className: 'bg-blue-50 text-blue-600' },
    high: { text: '高', className: 'bg-amber-50 text-amber-600' },
    confidential: { text: '机密', className: 'bg-red-50 text-red-600' },
  };
  return map[level] || { text: level, className: 'bg-slate-100 text-slate-600' };
}