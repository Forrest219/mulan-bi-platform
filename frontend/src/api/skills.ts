const BASE = '/api/skills';

// ── Types ──────────────────────────────────────────────────────────────────────

export interface AgentSkill {
  id: string;
  skill_key: string;
  name: string;
  description: string | null;
  category: string;
  is_enabled: boolean;
  active_version: { version_number: string; updated_at: string } | null;
  updated_at: string;
  created_at: string;
}

export interface SkillVersion {
  id: string;
  skill_id: string;
  version_number: string;
  description: string;
  input_schema: Record<string, unknown>;
  endpoint_type: string;
  code_ref: string | null;
  change_notes: string | null;
  is_active: boolean;
  created_at: string;
  created_by_name: string | null;
}

export interface SkillDetail extends AgentSkill {
  versions: SkillVersion[];
}

export interface SchemaDiff {
  from_version: string;
  to_version: string;
  description_changed: boolean;
  schema_patch: Array<{ op: string; path: string; value?: unknown }>;
}

export interface SkillListParams {
  category?: string;
  is_enabled?: boolean;
  q?: string;
  page?: number;
  page_size?: number;
}

export interface SkillListResponse {
  items: AgentSkill[];
  total: number;
  page: number;
  page_size: number;
}

export interface CreateSkillPayload {
  skill_key: string;
  name: string;
  description?: string;
  category: string;
  initial_version: {
    description: string;
    input_schema: Record<string, unknown>;
    endpoint_type: string;
    code_ref?: string;
    change_notes?: string;
  };
}

export interface PublishVersionPayload {
  description: string;
  input_schema: Record<string, unknown>;
  endpoint_type: string;
  code_ref?: string;
  change_notes?: string;
}

// ── API 函数 ───────────────────────────────────────────────────────────────────

export async function listSkills(params: SkillListParams): Promise<SkillListResponse> {
  const q = new URLSearchParams();
  if (params.category) q.set('category', params.category);
  if (params.is_enabled !== undefined) q.set('is_enabled', String(params.is_enabled));
  if (params.q) q.set('q', params.q);
  if (params.page) q.set('page', String(params.page));
  if (params.page_size) q.set('page_size', String(params.page_size));
  const res = await fetch(`${BASE}?${q}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取技能列表失败');
  return res.json();
}

export async function getSkill(id: string): Promise<SkillDetail> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取技能详情失败');
  return res.json();
}

export async function createSkill(payload: CreateSkillPayload): Promise<AgentSkill> {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err?.detail as { message?: string })?.message ?? '创建技能失败');
  }
  return res.json();
}

export async function patchSkill(
  id: string,
  data: Partial<Pick<AgentSkill, 'name' | 'description' | 'category' | 'is_enabled'>>,
): Promise<AgentSkill> {
  const res = await fetch(`${BASE}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('更新技能失败');
  return res.json();
}

export async function publishVersion(
  skillId: string,
  payload: PublishVersionPayload,
): Promise<SkillVersion> {
  const res = await fetch(`${BASE}/${skillId}/versions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err?.detail as { message?: string })?.message ?? '发布版本失败');
  }
  return res.json();
}

export async function rollbackVersion(
  skillId: string,
  versionId: string,
): Promise<{ rolled_back_to: string }> {
  const res = await fetch(`${BASE}/${skillId}/rollback/${versionId}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('回滚版本失败');
  return res.json();
}

export async function getVersionDiff(
  skillId: string,
  vId1: string,
  vId2: string,
): Promise<SchemaDiff> {
  const res = await fetch(`${BASE}/${skillId}/versions/${vId1}/diff/${vId2}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('获取版本差异失败');
  return res.json();
}
