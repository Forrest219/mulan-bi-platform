import { API_BASE } from '../config';

// ── 枚举类型 ──────────────────────────────────────────────────

export type Dimension = 'completeness' | 'accuracy' | 'timeliness' | 'validity' | 'uniqueness' | 'consistency';
export type SignalLevel = 'GREEN' | 'P1' | 'P0';
export type RuleType = 'null_rate' | 'uniqueness' | 'range_check' | 'freshness' | 'regex' | 'custom_sql' | 'volume_anomaly' | 'table_count_compare';
export type CycleStatus = 'pending' | 'running' | 'completed' | 'partial' | 'failed';
export type CycleScope = 'full' | 'hourly_light';
export type LlmTrigger = 'p0_triggered' | 'p1_triggered' | 'user_request' | 'rule_suggest';

// ── 维度-规则兼容矩阵 ────────────────────────────────────────

export const DIMENSION_RULE_COMPATIBILITY: Record<Dimension, RuleType[]> = {
  completeness: ['null_rate', 'custom_sql', 'volume_anomaly'],
  accuracy: ['range_check', 'custom_sql'],
  timeliness: ['freshness', 'custom_sql'],
  validity: ['regex', 'range_check', 'custom_sql'],
  uniqueness: ['uniqueness', 'custom_sql'],
  consistency: ['custom_sql', 'table_count_compare'],
};

export const DIMENSION_LABELS: Record<Dimension, string> = {
  completeness: '完整性',
  accuracy: '准确性',
  timeliness: '时效性',
  validity: '有效性',
  uniqueness: '唯一性',
  consistency: '一致性',
};

export const RULE_TYPE_LABELS: Record<RuleType, string> = {
  null_rate: '空值率',
  uniqueness: '唯一性',
  range_check: '范围检查',
  freshness: '时效性',
  regex: '正则校验',
  custom_sql: '自定义 SQL',
  volume_anomaly: '数据量异常',
  table_count_compare: '表行数对比',
};

export const SIGNAL_CONFIG: Record<SignalLevel, { label: string; bg: string; text: string; border: string; dot: string }> = {
  GREEN: { label: '正常', bg: 'bg-emerald-50', text: 'text-emerald-600', border: 'border-emerald-200', dot: 'bg-emerald-500' },
  P1: { label: '需关注', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200', dot: 'bg-amber-500' },
  P0: { label: '严重', bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200', dot: 'bg-red-500' },
};

export const TRIGGER_LABELS: Record<LlmTrigger, string> = {
  p0_triggered: 'P0 触发',
  p1_triggered: 'P1 触发',
  user_request: '用户请求',
  rule_suggest: '规则建议',
};

// ── 核心实体类型 ──────────────────────────────────────────────

export interface DqcAsset {
  id: number;
  datasource_id: number;
  schema_name: string;
  table_name: string;
  display_name: string | null;
  description: string | null;
  dimension_weights: Record<string, number>;
  signal_thresholds: Record<string, number>;
  profile_json: Record<string, unknown> | null;
  status: string;
  owner_id: number;
  created_by: number;
  created_at: string | null;
  updated_at: string | null;
  datasource_name: string | null;
  current_signal: SignalLevel | null;
  current_confidence_score: number | null;
  dimension_snapshot: Record<string, { score: number | null; signal: string | null }> | null;
  current_snapshot: {
    cycle_id: string | null;
    confidence_score: number;
    signal: string;
    dimension_scores: Record<string, number>;
    dimension_signals: Record<string, string>;
    computed_at: string | null;
  } | null;
  last_computed_at: string | null;
  rules_count: number;
  active_rules_count: number;
}

export interface DqcAssetDetail extends DqcAsset {
  profile: { row_count: number; columns_count: number; profiled_at: string } | null;
  recent_trend: Array<{ date: string | null; confidence_score: number }>;
  rules_total: number;
  rules_active: number;
}

export interface DqcRule {
  id: number;
  asset_id: number;
  name: string;
  description: string | null;
  dimension: Dimension;
  rule_type: RuleType;
  rule_config: Record<string, unknown>;
  is_active: boolean;
  is_system_suggested: boolean;
  suggested_by_llm_analysis_id: number | null;
  template_id: number | null;
  is_modified_by_user: boolean;
  template_default_config?: Record<string, unknown>;
  created_by: number;
  updated_by: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DqcCycle {
  id: string;
  trigger_type: string;
  status: CycleStatus;
  scope: CycleScope;
  started_at: string | null;
  completed_at: string | null;
  assets_total: number;
  assets_processed: number;
  assets_failed: number;
  rules_executed: number;
  p0_count: number;
  p1_count: number;
  triggered_by: number | null;
  error_message: string | null;
  created_at: string | null;
}

export interface DqcDimensionScore {
  id: number;
  cycle_id: string | null;
  asset_id: number;
  dimension: Dimension;
  score: number;
  signal: SignalLevel;
  prev_score: number | null;
  drift_24h: number | null;
  drift_vs_7d_avg: number | null;
  rules_total: number;
  rules_passed: number;
  rules_failed: number;
  computed_at: string | null;
}

export interface DqcSnapshot {
  id: number;
  cycle_id: string | null;
  asset_id: number;
  confidence_score: number;
  signal: SignalLevel;
  prev_signal: string | null;
  dimension_scores: Record<string, number>;
  dimension_signals: Record<string, string>;
  computed_at: string | null;
}

export interface DqcLlmAnalysis {
  id: number;
  cycle_id: string | null;
  asset_id: number;
  trigger: LlmTrigger;
  signal: SignalLevel | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number | null;
  root_cause: string | null;
  fix_suggestion: string | null;
  fix_sql: string | null;
  confidence: string | null;
  suggested_rules: unknown[] | null;
  status: string;
  error_message: string | null;
  created_at: string | null;
}

export interface DqcDashboard {
  summary: {
    total_assets: number;
    assets_green: number;
    assets_p1: number;
    assets_p0: number;
    avg_confidence_score: number;
    last_cycle_at: string | null;
    last_cycle_id: string | null;
  };
  signal_distribution: Record<string, number>;
  dimension_avg: Record<string, number>;
  top_failing_assets: Array<{
    asset_id: number;
    display_name: string;
    signal: string;
    confidence_score: number;
    top_failed_dimension: string;
  }>;
  recent_signal_changes: Array<{
    asset_id: number;
    display_name: string;
    prev_signal: string;
    current_signal: string;
    changed_at: string;
  }>;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ── 规则模板类型 ─────────────────────────────────────────────

export interface DqcRuleTemplate {
  id: number;
  name: string;
  description: string | null;
  dimension: Dimension;
  rule_type: RuleType;
  default_config: Record<string, unknown>;
  match_condition: Record<string, unknown>;
  severity: string;
  enabled: boolean;
  is_builtin: boolean;
  is_modified_by_user: boolean;
  created_by: number | null;
  updated_by: number | null;
  created_at: string | null;
  updated_at: string | null;
  derived_rules_count?: number;
  unmodified_rules_count?: number;
}

export interface CreateTemplateInput {
  name: string;
  description?: string;
  dimension: string;
  rule_type: string;
  default_config?: Record<string, unknown>;
  match_condition?: Record<string, unknown>;
  severity?: string;
  enabled?: boolean;
}

export interface UpdateTemplateInput {
  name?: string;
  description?: string;
  default_config?: Record<string, unknown>;
  match_condition?: Record<string, unknown>;
  severity?: string;
  enabled?: boolean;
}

// ── 请求类型 ──────────────────────────────────────────────────

export interface CreateAssetInput {
  datasource_id: number;
  schema_name: string;
  table_name: string;
  display_name?: string;
  description?: string;
  dimension_weights?: Record<string, number>;
  signal_thresholds?: Record<string, number>;
  auto_suggest_rules?: boolean;
}

export interface UpdateAssetInput {
  display_name?: string;
  description?: string;
  dimension_weights?: Record<string, number>;
  signal_thresholds?: Record<string, number>;
  status?: string;
}

export interface CreateRuleInput {
  name: string;
  description?: string;
  dimension: string;
  rule_type: string;
  rule_config?: Record<string, unknown>;
  is_active?: boolean;
}

export interface UpdateRuleInput {
  name?: string;
  description?: string;
  rule_config?: Record<string, unknown>;
  is_active?: boolean;
}

// ── 内部工具函数 ──────────────────────────────────────────────

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') q.set(k, String(v));
  }
  return q.toString();
}

async function handleResponse<T>(res: Response, fallbackMsg: string): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const code = (err as { error_code?: string }).error_code;
    if (res.status === 409 && code === 'DQC_002') {
      throw new Error('该表已在监控中');
    }
    throw new Error((err as { message?: string }).message || fallbackMsg);
  }
  return res.json();
}

// ── Dashboard ─────────────────────────────────────────────────

export async function fetchDashboard(): Promise<DqcDashboard> {
  const res = await fetch(`${API_BASE}/api/dqc/dashboard`, { credentials: 'include' });
  return handleResponse(res, '获取数据质量概览失败');
}

// ── 资产 CRUD ─────────────────────────────────────────────────

export async function listAssets(params: {
  datasource_id?: number;
  status?: string;
  signal?: string;
  page?: number;
  page_size?: number;
} = {}): Promise<PaginatedResponse<DqcAsset>> {
  const qs = buildQuery({
    datasource_id: params.datasource_id,
    status: params.status,
    signal: params.signal,
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
  });
  const res = await fetch(`${API_BASE}/api/dqc/assets?${qs}`, { credentials: 'include' });
  return handleResponse(res, '获取监控资产列表失败');
}

export async function getAsset(id: number): Promise<DqcAssetDetail> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/${id}`, { credentials: 'include' });
  return handleResponse(res, '获取资产详情失败');
}

export async function createAsset(data: CreateAssetInput): Promise<{ asset: DqcAsset; profiling_task_id: string | null; message: string }> {
  const res = await fetch(`${API_BASE}/api/dqc/assets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleResponse(res, '添加监控失败');
}

export async function updateAsset(id: number, data: UpdateAssetInput): Promise<DqcAsset> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleResponse(res, '更新资产失败');
}

export async function deleteAsset(id: number): Promise<{ message: string; asset_id: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  return handleResponse(res, '删除监控失败');
}

// ── 规则 CRUD ─────────────────────────────────────────────────

export async function listRules(assetId: number, params: {
  dimension?: string;
  is_active?: boolean;
  is_system_suggested?: boolean;
} = {}): Promise<{ items: DqcRule[]; total: number }> {
  const qs = buildQuery({
    dimension: params.dimension,
    is_active: params.is_active,
    is_system_suggested: params.is_system_suggested,
  });
  const res = await fetch(`${API_BASE}/api/dqc/assets/${assetId}/rules?${qs}`, { credentials: 'include' });
  return handleResponse(res, '获取规则列表失败');
}

export async function createRule(assetId: number, data: CreateRuleInput): Promise<DqcRule> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/${assetId}/rules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleResponse(res, '创建规则失败');
}

export async function updateRule(assetId: number, ruleId: number, data: UpdateRuleInput): Promise<DqcRule> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/${assetId}/rules/${ruleId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleResponse(res, '更新规则失败');
}

export async function deleteRule(assetId: number, ruleId: number): Promise<{ message: string; rule_id: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/${assetId}/rules/${ruleId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  return handleResponse(res, '删除规则失败');
}

export async function suggestRules(assetId: number, params?: {
  dimensions?: string[];
  max_rules?: number;
}): Promise<{ analysis_id: number | null; suggested_rules: unknown[]; message: string }> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/${assetId}/rules/suggest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(params ?? {}),
  });
  return handleResponse(res, '获取规则建议失败');
}

// ── 评分 / 快照 / 分析 ───────────────────────────────────────

export async function listScores(assetId: number, params: {
  dimension?: string;
  start?: string;
  end?: string;
  limit?: number;
} = {}): Promise<{ items: DqcDimensionScore[]; total: number }> {
  const qs = buildQuery({ dimension: params.dimension, start: params.start, end: params.end, limit: params.limit ?? 100 });
  const res = await fetch(`${API_BASE}/api/dqc/assets/${assetId}/scores?${qs}`, { credentials: 'include' });
  return handleResponse(res, '获取评分数据失败');
}

export async function listSnapshots(assetId: number, params: {
  start?: string;
  end?: string;
  limit?: number;
} = {}): Promise<{ items: DqcSnapshot[]; total: number }> {
  const qs = buildQuery({ start: params.start, end: params.end, limit: params.limit ?? 30 });
  const res = await fetch(`${API_BASE}/api/dqc/assets/${assetId}/snapshots?${qs}`, { credentials: 'include' });
  return handleResponse(res, '获取快照数据失败');
}

export async function listAnalyses(assetId: number, params: {
  trigger?: string;
  limit?: number;
} = {}): Promise<{ items: DqcLlmAnalysis[]; total: number }> {
  const qs = buildQuery({ trigger: params.trigger, limit: params.limit ?? 20 });
  const res = await fetch(`${API_BASE}/api/dqc/assets/${assetId}/analyses?${qs}`, { credentials: 'include' });
  return handleResponse(res, '获取分析记录失败');
}

// ── 周期 ──────────────────────────────────────────────────────

export async function runCycle(data: {
  scope?: CycleScope;
  asset_ids?: number[];
} = {}): Promise<{ task_id?: string; task_ids?: string[]; message: string }> {
  const res = await fetch(`${API_BASE}/api/dqc/cycles/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleResponse(res, '触发扫描失败');
}

export async function listCycles(params: {
  status?: string;
  scope?: string;
  start?: string;
  end?: string;
  page?: number;
  page_size?: number;
} = {}): Promise<PaginatedResponse<DqcCycle>> {
  const qs = buildQuery({
    status: params.status,
    scope: params.scope,
    start: params.start,
    end: params.end,
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
  });
  const res = await fetch(`${API_BASE}/api/dqc/cycles?${qs}`, { credentials: 'include' });
  return handleResponse(res, '获取执行周期列表失败');
}

// ── 规则模板 CRUD ────────────────────────────────────────────

export async function listTemplates(params: {
  enabled?: boolean;
} = {}): Promise<{ items: DqcRuleTemplate[]; total: number }> {
  const qs = buildQuery({ enabled: params.enabled });
  const res = await fetch(`${API_BASE}/api/dqc/templates?${qs}`, { credentials: 'include' });
  return handleResponse(res, '获取规则模板列表失败');
}

export async function getTemplate(id: number): Promise<DqcRuleTemplate> {
  const res = await fetch(`${API_BASE}/api/dqc/templates/${id}`, { credentials: 'include' });
  return handleResponse(res, '获取模板详情失败');
}

export async function createTemplate(data: CreateTemplateInput): Promise<DqcRuleTemplate> {
  const res = await fetch(`${API_BASE}/api/dqc/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleResponse(res, '创建模板失败');
}

export async function updateTemplate(id: number, data: UpdateTemplateInput): Promise<{ template: DqcRuleTemplate; propagated_count: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/templates/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleResponse(res, '更新模板失败');
}

export async function deleteTemplate(id: number): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/dqc/templates/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  return handleResponse(res, '删除模板失败');
}

export async function applyTemplate(id: number): Promise<{ applied_assets: number; rules_created: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/templates/${id}/apply`, {
    method: 'POST',
    credentials: 'include',
  });
  return handleResponse(res, '应用模板失败');
}

export interface AiParseResult {
  name: string;
  default_config: Record<string, unknown>;
  match_condition: Record<string, unknown>;
  severity: string;
  reasoning: string;
}

export async function aiParseTemplateConfig(description: string, ruleType?: string): Promise<AiParseResult> {
  const res = await fetch(`${API_BASE}/api/dqc/templates/ai-parse`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description, rule_type: ruleType }),
  });
  return handleResponse(res, 'AI 解析失败');
}
