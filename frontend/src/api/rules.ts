const BASE = '/api/admin/rules';

export interface RuleItem {
  id: number;
  rule_id: string;
  name: string;
  level: string;
  category: string;
  display_group?: string;
  description: string;
  suggestion: string;
  db_type: string;
  scene_type: string;
  built_in: boolean;
  status: 'enabled' | 'disabled';
  is_custom: boolean;
  config_json?: Record<string, unknown>;
}

export interface RulesListResponse {
  rules: RuleItem[];
  total: number;
  enabled_count: number;
  disabled_count: number;
}

export interface DryRunViolation {
  level: string;
  message: string;
  suggestion: string;
}

export interface DryRunResult {
  code: string;
  message: string;
  trace_id: string;
  data: {
    rule_id: string;
    ddl_text: string;
    hit: boolean;
    violations: DryRunViolation[];
  };
}

export async function listRules(params?: {
  category?: string;
  level?: string;
  db_type?: string;
  scene_type?: string;
  status?: string;
}): Promise<RulesListResponse> {
  const q = new URLSearchParams();
  if (params?.category) q.set('category', params.category);
  if (params?.level) q.set('level', params.level);
  if (params?.db_type) q.set('db_type', params.db_type);
  if (params?.scene_type) q.set('scene_type', params.scene_type);
  if (params?.status) q.set('status', params.status);
  const res = await fetch(`${BASE}/?${q}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取规则列表失败');
  return res.json();
}

export async function toggleRule(ruleId: string): Promise<{ rule_id: string; status: string; message: string }> {
  const res = await fetch(`${BASE}/${encodeURIComponent(ruleId)}/toggle`, {
    method: 'PUT',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err?.detail as { message?: string })?.message ?? '切换规则状态失败');
  }
  return res.json();
}

export interface CreateRulePayload {
  id: string;
  name: string;
  level: string;
  category: string;
  description: string;
  suggestion: string;
  db_type: string;
  scene_type?: string;
  display_group?: string;
}

export async function createRule(payload: CreateRulePayload): Promise<{ rule: RuleItem; message: string }> {
  const res = await fetch(`${BASE}/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err?.detail === 'string' ? err.detail : '创建规则失败');
  }
  return res.json();
}

export async function deleteRule(ruleId: string): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/${encodeURIComponent(ruleId)}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err?.detail as { message?: string })?.message ?? '删除规则失败');
  }
  return res.json();
}

export async function dryRunRule(payload: {
  rule: Record<string, unknown>;
  ddl_text: string;
  db_type?: string;
}): Promise<DryRunResult> {
  const res = await fetch(`${BASE}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err?.detail === 'string' ? err.detail : '干运行失败');
  }
  return res.json();
}
