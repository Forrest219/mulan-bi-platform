import { API_BASE } from '../config';

export type MetricType = 'atomic' | 'derived' | 'ratio';
export type AggregationType = 'SUM' | 'AVG' | 'COUNT' | 'COUNT_DISTINCT' | 'MAX' | 'MIN' | 'none';
export type ResultType = 'float' | 'integer' | 'percentage' | 'currency';
export type SensitivityLevel = 'public' | 'internal' | 'confidential' | 'restricted';
export type LineageStatus = 'unknown' | 'resolved' | 'manual';

export interface MetricItem {
  id: string;
  name: string;
  name_zh: string;
  metric_type: MetricType;
  business_domain: string;
  is_active: boolean;
  lineage_status: LineageStatus;
  sensitivity_level: SensitivityLevel;
  datasource_id: number;
  table_name: string;
  column_name: string;
  formula: string;
  aggregation_type: AggregationType;
  result_type: ResultType;
  unit: string;
  precision: number;
  created_at: string;
  updated_at: string;
}

export interface MetricsListResponse {
  items: MetricItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateMetricInput {
  name: string;
  name_zh?: string;
  metric_type: MetricType;
  business_domain?: string;
  description?: string;
  formula?: string;
  aggregation_type?: AggregationType;
  result_type?: ResultType;
  unit?: string;
  precision?: number;
  datasource_id: number;
  table_name: string;
  column_name: string;
  sensitivity_level?: SensitivityLevel;
}

export type UpdateMetricInput = Partial<CreateMetricInput>;

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) q.set(k, String(v));
  }
  return q.toString();
}

export async function listMetrics(params: {
  page?: number;
  page_size?: number;
  search?: string;
  metric_type?: string;
  is_active?: boolean;
}): Promise<MetricsListResponse> {
  const qs = buildQuery({
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
    search: params.search ?? '',
    metric_type: params.metric_type ?? '',
    is_active: params.is_active ?? '',
  });
  const res = await fetch(`${API_BASE}/api/metrics?${qs}`, { credentials: 'include' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || '获取指标列表失败');
  }
  return res.json();
}

export async function createMetric(data: CreateMetricInput): Promise<MetricItem> {
  const res = await fetch(`${API_BASE}/api/metrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    if (res.status === 409 && (err as { error_code?: string }).error_code === 'MC_001') {
      throw new Error('指标名已存在，请更换');
    }
    throw new Error((err as { message?: string }).message || '创建指标失败');
  }
  return res.json();
}

export async function updateMetric(id: string, data: UpdateMetricInput): Promise<MetricItem> {
  const res = await fetch(`${API_BASE}/api/metrics/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '更新指标失败');
  }
  return res.json();
}

export async function deleteMetric(id: string): Promise<{ id: string; is_active: boolean }> {
  const res = await fetch(`${API_BASE}/api/metrics/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '下线指标失败');
  }
  return res.json();
}

export async function submitReviewMetric(id: string): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/api/metrics/${id}/submit-review`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '提交审核失败');
  }
  return res.json();
}

export async function approveMetric(id: string): Promise<{ reviewed_by: string; reviewed_at: string }> {
  const res = await fetch(`${API_BASE}/api/metrics/${id}/approve`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '审批失败');
  }
  return res.json();
}

export async function publishMetric(id: string): Promise<{ published_at: string }> {
  const res = await fetch(`${API_BASE}/api/metrics/${id}/publish`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    if ((err as { error_code?: string }).error_code === 'MC_002') {
      throw new Error('血缘关系未解析，无法发布');
    }
    throw new Error((err as { message?: string }).message || '发布失败');
  }
  return res.json();
}

// =============================================================================
// 指标详情
// =============================================================================

export interface MetricDetail {
  id: string;
  tenant_id: string;
  name: string;
  name_zh: string | null;
  metric_type: MetricType;
  business_domain: string | null;
  description: string | null;
  formula: string | null;
  formula_template: string | null;
  aggregation_type: AggregationType | null;
  result_type: ResultType | null;
  unit: string | null;
  precision: number;
  datasource_id: number;
  table_name: string;
  column_name: string;
  filters: Record<string, unknown> | null;
  is_active: boolean;
  lineage_status: LineageStatus;
  sensitivity_level: SensitivityLevel;
  created_by: number;
  reviewed_by: number | null;
  reviewed_at: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export async function getMetricDetail(id: string): Promise<MetricDetail> {
  const res = await fetch(`${API_BASE}/api/metrics/${id}`, { credentials: 'include' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '获取指标详情失败');
  }
  return res.json();
}

// =============================================================================
// 血缘查询
// =============================================================================

export interface LineageRecord {
  id: string;
  datasource_id: number;
  table_name: string;
  column_name: string;
  column_type: string | null;
  relationship_type: string;
  hop_number: number;
  transformation_logic: string | null;
  created_at: string | null;
}

export interface LineageResponse {
  metric_id: string;
  lineage_status: string;
  records: LineageRecord[];
}

export async function getMetricLineage(id: string): Promise<LineageResponse> {
  const res = await fetch(`${API_BASE}/api/metrics/${id}/lineage`, { credentials: 'include' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '获取指标血缘失败');
  }
  return res.json();
}

export async function resolveLineage(
  id: string,
  manualOverride: boolean = false,
  manualRecords?: Record<string, unknown>[],
): Promise<{ lineage_count: number; lineage_status: string }> {
  const params = new URLSearchParams({ manual_override: String(manualOverride) });
  const res = await fetch(`${API_BASE}/api/metrics/${id}/lineage/resolve?${params}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: manualRecords ? JSON.stringify(manualRecords) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '触发血缘解析失败');
  }
  return res.json();
}

// =============================================================================
// 一致性校验
// =============================================================================

export interface ConsistencyCheckResult {
  id: string;
  tenant_id: string;
  metric_id: string;
  metric_name: string;
  datasource_id_a: number;
  datasource_id_b: number;
  value_a: number | null;
  value_b: number | null;
  difference: number | null;
  difference_pct: number | null;
  tolerance_pct: number;
  check_status: 'pass' | 'warning' | 'fail';
  checked_at: string | null;
  created_at: string | null;
}

export async function runConsistencyCheck(params: {
  metric_id: string;
  datasource_id_a: number;
  datasource_id_b: number;
  tolerance_pct?: number;
}): Promise<ConsistencyCheckResult> {
  const res = await fetch(`${API_BASE}/api/metrics/consistency-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '一致性校验失败');
  }
  return res.json();
}

export interface ConsistencyChecksListResponse {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  items: ConsistencyCheckResult[];
}

export async function listConsistencyChecks(params: {
  metric_id?: string;
  check_status?: string;
  page?: number;
  page_size?: number;
}): Promise<ConsistencyChecksListResponse> {
  const qs = buildQuery({
    metric_id: params.metric_id,
    check_status: params.check_status,
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
  });
  const res = await fetch(`${API_BASE}/api/metrics/consistency-checks?${qs}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '获取一致性校验记录失败');
  }
  return res.json();
}

// =============================================================================
// 异常记录
// =============================================================================

export interface AnomalyRecord {
  id: string;
  metric_id: string;
  datasource_id: number;
  detection_method: string;
  metric_value: number;
  expected_value: number;
  deviation_score: number;
  deviation_threshold: number;
  detected_at: string | null;
  status: string;
  resolved_by: number | null;
  resolved_at: string | null;
  resolution_note: string | null;
  created_at: string | null;
}

export interface AnomaliesListResponse {
  metric_id: string;
  total: number;
  page: number;
  page_size: number;
  pages: number;
  items: AnomalyRecord[];
}

export async function listMetricAnomalies(
  metricId: string,
  params?: { status?: string; page?: number; page_size?: number },
): Promise<AnomaliesListResponse> {
  const qs = buildQuery({
    status: params?.status,
    page: params?.page ?? 1,
    page_size: params?.page_size ?? 20,
  });
  const res = await fetch(`${API_BASE}/api/metrics/${metricId}/anomalies?${qs}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message || '获取异常记录失败');
  }
  return res.json();
}
