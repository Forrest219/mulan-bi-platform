import { API_BASE } from '../config';

// ── 枚举类型 ──────────────────────────────────────────────────

export type Dimension = 'completeness' | 'accuracy' | 'timeliness' | 'validity' | 'uniqueness' | 'consistency' | 'ai_ready';
export type SignalLevel = 'GREEN' | 'P1' | 'P0';
export type RuleType =
  // L1
  | 'table_not_null' | 'null_rate' | 'uniqueness' | 'enum_check' | 'range_check'
  // L2
  | 'freshness' | 'arrival_check' | 'volume_anomaly' | 'schema_drift' | 'partition_completeness'
  // L3
  | 'table_count_compare' | 'fk_coverage' | 'amount_reconciliation' | 'detail_summary_consistency' | 'metric_drift'
  // L4
  | 'ai_table_description' | 'ai_field_comment' | 'ai_metric_definition'
  | 'default_time_field' | 'default_amount_field' | 'default_filter_condition'
  | 'sensitive_field' | 'deprecated_field' | 'sample_questions'
  // legacy
  | 'regex' | 'custom_sql';
export type CycleStatus = 'pending' | 'running' | 'completed' | 'partial' | 'failed';
export type CycleScope = 'full' | 'hourly_light';
export type LlmTrigger = 'p0_triggered' | 'p1_triggered' | 'user_request' | 'rule_suggest';

// ── 维度-规则兼容矩阵 ────────────────────────────────────────

export const DIMENSION_RULE_COMPATIBILITY: Record<Dimension, RuleType[]> = {
  completeness: ['null_rate', 'custom_sql', 'volume_anomaly'],
  accuracy: ['range_check', 'custom_sql', 'enum_check'],
  timeliness: ['freshness', 'custom_sql'],
  validity: ['regex', 'range_check', 'custom_sql'],
  uniqueness: ['uniqueness', 'custom_sql'],
  consistency: ['custom_sql', 'table_count_compare', 'schema_drift'],
  ai_ready: ['ai_field_comment', 'ai_table_description', 'ai_metric_definition', 'sensitive_field'],
};

export const DIMENSION_LABELS: Record<Dimension, string> = {
  completeness: '完整性',
  accuracy: '准确性',
  timeliness: '时效性',
  validity: '有效性',
  uniqueness: '唯一性',
  consistency: '一致性',
  ai_ready: 'AI 就绪',
};

export const RULE_TYPE_LABELS: Record<RuleType, string> = {
  // L1
  table_not_null: '表非空监控',
  null_rate: '字段空值率监控',
  uniqueness: '唯一性监控',
  enum_check: '值域合法性监控',
  range_check: '数值范围监控',
  // L2
  freshness: '新鲜度监控',
  arrival_check: '数据按时到达监控',
  volume_anomaly: '表行数异常监控',
  schema_drift: '表结构变更监控',
  partition_completeness: '分区完整性监控',
  // L3
  table_count_compare: '跨表数值比对',
  fk_coverage: '事实维表关联覆盖率',
  amount_reconciliation: '金额勾稽关系',
  detail_summary_consistency: '明细汇总一致性',
  metric_drift: '指标波动监控',
  // L4
  ai_table_description: '表业务说明完整性',
  ai_field_comment: '字段注释完整性',
  ai_metric_definition: '指标口径完整性',
  default_time_field: '默认时间字段声明',
  default_amount_field: '默认金额字段声明',
  default_filter_condition: '默认过滤条件声明',
  sensitive_field: '敏感字段标识',
  deprecated_field: '废弃字段标识',
  sample_questions: '样例问题完整性',
  // legacy
  regex: '正则校验',
  custom_sql: '自定义 SQL',
};

export const SIGNAL_CONFIG: Record<SignalLevel, { label: string; bg: string; text: string; border: string; dot: string }> = {
  GREEN: { label: '正常', bg: 'bg-emerald-50', text: 'text-emerald-600', border: 'border-emerald-200', dot: 'bg-emerald-500' },
  P1: { label: '需关注', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200', dot: 'bg-amber-500' },
  P0: { label: '严重', bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200', dot: 'bg-red-500' },
};

export const RULE_PACKAGE_LABELS: Record<string, string> = {
  L1: 'L1 基础质量',
  L2: 'L2 时效稳定',
  L3: 'L3 业务一致性',
  L4: 'L4 AI Ready',
};

export const RULE_PACKAGE_DESCRIPTIONS: Record<string, string> = {
  L1: '检查数据是否完整、唯一、合法',
  L2: '检查数据是否及时更新、结构是否稳定',
  L3: '检查跨表结果、业务勾稽和指标一致性',
  L4: '检查数据是否可被 AI 正确理解和安全使用',
};

export const RULE_PACKAGE_RULE_TYPES: Record<string, RuleType[]> = {
  L1: ['table_not_null', 'null_rate', 'uniqueness', 'enum_check', 'range_check'],
  L2: ['freshness', 'arrival_check', 'volume_anomaly', 'schema_drift', 'partition_completeness'],
  L3: ['table_count_compare', 'fk_coverage', 'amount_reconciliation', 'detail_summary_consistency', 'metric_drift'],
  L4: ['ai_table_description', 'ai_field_comment', 'ai_metric_definition', 'default_time_field', 'default_amount_field', 'default_filter_condition', 'sensitive_field', 'deprecated_field', 'sample_questions'],
};

export const RULE_TYPE_DIMENSION_MAP: Record<string, Dimension> = {
  table_not_null: 'completeness',
  null_rate: 'completeness',
  uniqueness: 'uniqueness',
  enum_check: 'validity',
  range_check: 'accuracy',
  freshness: 'timeliness',
  arrival_check: 'timeliness',
  volume_anomaly: 'completeness',
  schema_drift: 'validity',
  partition_completeness: 'completeness',
  table_count_compare: 'consistency',
  fk_coverage: 'consistency',
  amount_reconciliation: 'consistency',
  detail_summary_consistency: 'consistency',
  metric_drift: 'consistency',
  ai_table_description: 'ai_ready',
  ai_field_comment: 'ai_ready',
  ai_metric_definition: 'ai_ready',
  default_time_field: 'ai_ready',
  default_amount_field: 'ai_ready',
  default_filter_condition: 'ai_ready',
  sensitive_field: 'ai_ready',
  deprecated_field: 'ai_ready',
  sample_questions: 'ai_ready',
  regex: 'validity',
  custom_sql: 'completeness',
};

export const BLOCK_STRATEGY_LABELS: Record<string, string> = {
  blocking: '阻断',
  alert: '告警',
  record_only: '仅记录',
  block_ai: '阻断 AI 使用',
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
  rule_package?: string;
  block_strategy?: string;
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
  rule_package?: string;
  block_strategy?: string;
}

export interface UpdateTemplateInput {
  name?: string;
  description?: string;
  default_config?: Record<string, unknown>;
  match_condition?: Record<string, unknown>;
  severity?: string;
  enabled?: boolean;
  rule_package?: string;
  block_strategy?: string;
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
  datasource_ids?: number[];
  schema_names?: string[];
  status?: string;
  signal?: string;
  page?: number;
  page_size?: number;
} = {}): Promise<PaginatedResponse<DqcAsset>> {
  const q = new URLSearchParams();
  (params.datasource_ids ?? []).forEach(id => q.append('datasource_ids', String(id)));
  (params.schema_names ?? []).forEach(s => q.append('schema_names', s));
  if (params.status) q.set('status', params.status);
  if (params.signal) q.set('signal', params.signal);
  q.set('page', String(params.page ?? 1));
  q.set('page_size', String(params.page_size ?? 20));
  const res = await fetch(`${API_BASE}/api/dqc/assets?${q}`, { credentials: 'include' });
  return handleResponse(res, '获取监控资产列表失败');
}

export async function listAssetSchemas(datasourceIds: number[] = []): Promise<string[]> {
  const q = new URLSearchParams();
  datasourceIds.forEach(id => q.append('datasource_ids', String(id)));
  const res = await fetch(`${API_BASE}/api/dqc/assets/schemas?${q}`, { credentials: 'include' });
  const data = await handleResponse<{ schemas: string[] }>(res, '获取 Schema 列表失败');
  return data.schemas;
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

export interface TemplateCoverageItem {
  asset_id: number;
  schema_name: string;
  table_name: string;
  display_name: string;
  datasource_name: string | null;
  status: string;
  enabled: boolean;
}

export async function getTemplateCoverage(id: number): Promise<{ items: TemplateCoverageItem[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/templates/${id}/coverage`, { credentials: 'include' });
  return handleResponse(res, '获取覆盖范围失败');
}

export async function toggleTemplateCoverage(
  id: number, asset_id: number, enabled: boolean
): Promise<{ message: string; rule_id?: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/templates/${id}/coverage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ asset_id, enabled }),
  });
  return handleResponse(res, '操作失败');
}

export async function batchToggleTemplateCoverage(
  id: number, add: number[], remove: number[]
): Promise<{ added: number; removed: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/templates/${id}/coverage/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ add, remove }),
  });
  return handleResponse(res, '批量操作失败');
}

// ── AI 创建规则 ──────────────────────────────────────────────

export interface AiRuleDraft {
  template_id: number;
  capability_name: string;
  rule_package: string;
  dimension: string;
  suggested_name: string;
  suggested_description: string;
  target_table: string;
  target_column?: string;
  severity: string;
  default_config: Record<string, unknown>;
}

export async function generateRuleFromDescription(description: string): Promise<AiRuleDraft> {
  const res = await fetch(`${API_BASE}/api/dqc/rules/ai-generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ description }),
  });
  return handleResponse(res, 'AI 分析失败，请重试');
}

// ── 第二层：派生规则 ────────────────────────────────────────────────
export interface DqcDerivedRule {
  id: number;
  template_id: number;
  template_name: string;
  rule_name: string;
  table_name: string;
  column_name?: string;
  object_type: 'table' | 'column' | 'metric' | 'metadata';
  rule_config: Record<string, unknown>;
  severity: string;
  action: string;
  ai_ready_enabled: boolean;
  enabled: boolean;
  owner?: string;
  generated_by: 'system' | 'user' | 'ai';
  created_at: string;
  updated_at: string;
}

export async function listDerivedRules(params: {
  template_id?: number;
  table_name?: string;
  enabled?: boolean;
  page?: number;
  page_size?: number;
} = {}): Promise<PaginatedResponse<DqcDerivedRule>> {
  const q = buildQuery(params);
  const res = await fetch(`${API_BASE}/api/dqc/derived-rules${q}`, { credentials: 'include' });
  return handleResponse<PaginatedResponse<DqcDerivedRule>>(res, '获取检查规则失败');
}

export async function updateDerivedRule(
  id: number,
  data: Partial<Pick<DqcDerivedRule, 'rule_config' | 'severity' | 'action' | 'enabled' | 'owner'>>,
): Promise<DqcDerivedRule> {
  const res = await fetch(`${API_BASE}/api/dqc/derived-rules/${id}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return handleResponse<DqcDerivedRule>(res, '更新检查规则失败');
}

// ── 第三层：检查记录 ────────────────────────────────────────────────
export type CheckStatus = 'PASS' | 'FAIL' | 'WARNING' | 'SKIPPED' | 'ERROR';

export interface DqcCheckResult {
  id: number;
  rule_id: number;
  rule_name: string;
  template_id?: number;
  template_name?: string;
  rule_package?: string;
  table_name: string;
  column_name?: string;
  check_time: string;
  status: CheckStatus;
  actual_value?: number;
  threshold_value?: number;
  total_count?: number;
  error_count?: number;
  message?: string;
  suggestion?: string;
  affect_ai_ready: boolean;
}

export const CHECK_STATUS_CONFIG: Record<CheckStatus, { label: string; bg: string; text: string }> = {
  PASS:    { label: '通过',   bg: 'bg-green-50',  text: 'text-green-700' },
  FAIL:    { label: '失败',   bg: 'bg-red-50',    text: 'text-red-700' },
  WARNING: { label: '警告',   bg: 'bg-amber-50',  text: 'text-amber-700' },
  SKIPPED: { label: '跳过',   bg: 'bg-slate-50',  text: 'text-slate-500' },
  ERROR:   { label: '执行错误', bg: 'bg-orange-50', text: 'text-orange-700' },
};

export async function listCheckResults(params: {
  rule_id?: number;
  template_id?: number;
  table_name?: string;
  status?: string;
  affect_ai_ready?: boolean;
  page?: number;
  page_size?: number;
} = {}): Promise<PaginatedResponse<DqcCheckResult>> {
  const q = buildQuery(params);
  const res = await fetch(`${API_BASE}/api/dqc/check-results${q}`, { credentials: 'include' });
  return handleResponse<PaginatedResponse<DqcCheckResult>>(res, '获取检查记录失败');
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

// ── 批量导入监控资产 ──────────────────────────────────────────────

export async function listDatasourceTables(
  datasourceId: number,
): Promise<{ items: { schema_name: string; table_name: string }[]; total: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/datasources/${datasourceId}/tables`, {
    credentials: 'include',
  });
  return handleResponse(res, '获取数据源表列表失败');
}

export async function batchImportAssets(request: {
  datasource_id: number;
  tables: { schema_name: string; table_name: string; display_name?: string }[];
  auto_suggest_rules: boolean;
}): Promise<{ created: number; skipped: number; total: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/batch-import`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  return handleResponse(res, '批量导入失败');
}

export async function batchDeleteAssets(assetIds: number[]): Promise<{ deleted: number; unauthorized: number }> {
  const res = await fetch(`${API_BASE}/api/dqc/assets/batch`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asset_ids: assetIds }),
  });
  return handleResponse(res, '批量停用失败');
}
