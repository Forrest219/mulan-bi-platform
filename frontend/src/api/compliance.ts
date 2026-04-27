import { API_BASE } from '../config';

// Types

export interface ComplianceRule {
  id: string;
  name: string;
  description: string;
  level: string;
  category: string;
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

// Category metadata for display

export const CATEGORY_LABELS: Record<string, string> = {
  sr_layer_naming: '分层命名',
  sr_type_alignment: '字段类型对齐',
  sr_public_fields: '公共字段',
  sr_field_naming: '字段命名',
  sr_comment: '注释规范',
  sr_database_whitelist: '数据库白名单',
  sr_table_naming: '表名规范',
  sr_view_naming: '视图命名',
};

export const CATEGORY_ICONS: Record<string, string> = {
  sr_layer_naming: 'ri-stack-line',
  sr_type_alignment: 'ri-code-s-slash-line',
  sr_public_fields: 'ri-grid-line',
  sr_field_naming: 'ri-text',
  sr_comment: 'ri-chat-3-line',
  sr_database_whitelist: 'ri-database-2-line',
  sr_table_naming: 'ri-table-line',
  sr_view_naming: 'ri-eye-line',
};

// API functions

export async function listComplianceRules(): Promise<ComplianceRulesResponse> {
  const res = await fetch(`${API_BASE}/api/rules/?db_type=StarRocks`, {
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
