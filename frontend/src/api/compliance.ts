import { API_BASE } from '../config';

// Types

export interface ComplianceRule {
  id: string;
  name: string;
  description: string;
  level: string;
  category: string;
  display_group: string;
  db_type: string;
  suggestion: string;
  status: 'enabled' | 'disabled';
  built_in: boolean;
  config_json: Record<string, unknown>;
}

export interface ComplianceRulesResponse {
  rules: ComplianceRule[];
  total: number;
  enabled_count: number;
  disabled_count: number;
}

// Display group metadata (6 groups, replaces 13 sr_* categories)

export const DISPLAY_GROUP_LABELS: Record<string, string> = {
  naming: '命名规范',
  field: '字段规范',
  comment: '注释规范',
  storage: '存储规范',
  performance: '性能规范',
  schema: '架构与元数据',
  other: '其他',
};

export const DISPLAY_GROUP_ICONS: Record<string, string> = {
  naming: 'ri-text',
  field: 'ri-code-s-slash-line',
  comment: 'ri-chat-3-line',
  storage: 'ri-server-line',
  performance: 'ri-speed-line',
  schema: 'ri-layout-line',
  other: 'ri-file-list-line',
};

// API functions

export async function listComplianceRules(): Promise<ComplianceRulesResponse> {
  const res = await fetch(`${API_BASE}/api/rules/`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('获取合规规则列表失败');
  return res.json();
}

export async function toggleComplianceRule(ruleId: string): Promise<{ rule_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/rules/${ruleId}/toggle`, {
    method: 'PUT',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || err.detail || '切换规则状态失败');
  }
  return res.json();
}

export interface CreateComplianceRuleInput {
  id: string;
  name: string;
  description: string;
  level: 'HIGH' | 'MEDIUM' | 'LOW';
  category: string;
  display_group?: string;
  db_type: string;
  suggestion?: string;
  scene_type?: string;
}

export interface UpdateComplianceRuleInput {
  name?: string;
  description?: string;
  level?: string;
  category?: string;
  display_group?: string;
  suggestion?: string;
  scene_type?: string;
  config_json?: Record<string, unknown>;
}

export async function createComplianceRule(data: CreateComplianceRuleInput): Promise<{ rule: ComplianceRule; message: string }> {
  const res = await fetch(`${API_BASE}/api/rules/`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || err.detail || '创建规则失败');
  }
  return res.json();
}

export async function updateComplianceRule(ruleId: string, data: UpdateComplianceRuleInput): Promise<{ rule: ComplianceRule; message: string }> {
  const res = await fetch(`${API_BASE}/api/rules/${ruleId}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || err.detail || '更新规则失败');
  }
  return res.json();
}

export async function deleteComplianceRule(ruleId: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/rules/${ruleId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || err.detail || '删除规则失败');
  }
  return res.json();
}
