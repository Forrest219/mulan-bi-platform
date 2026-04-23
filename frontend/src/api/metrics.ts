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
