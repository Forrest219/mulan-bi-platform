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

export interface RegisteredTool {
  skill_key: string;
  name: string;
  description: string;
  default_description?: string;
  input_schema: Record<string, unknown>;
  default_parameters_schema?: Record<string, unknown>;
  category: string;
  code_ref: string | null;
  configured: boolean;
  skill_id: string | null;
  active_version_id: string | null;
  active_version_number: string | null;
}

export interface RegisteredToolsResponse {
  tools: RegisteredTool[];
  total: number;
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

export interface PublishVersionResponse {
  id: string;
  skill_id: string;
  version_number: string;
  is_active: boolean;
  previous_active_version: string | null;
  created_at: string | null;
}

async function skillApiError(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => ({}));
  const detail = body?.detail;
  if (detail && typeof detail === 'object') {
    const code = typeof detail.code === 'string' ? detail.code : undefined;
    const message = typeof detail.message === 'string' ? detail.message : undefined;
    if (code && message) return new Error(`[${code}] ${message}`);
    if (message) return new Error(message);
    if (code) return new Error(`[${code}] ${fallback}`);
  }
  if (typeof detail === 'string') return new Error(detail);
  if (typeof body?.message === 'string') return new Error(body.message);
  return new Error(fallback);
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
  if (!res.ok) throw await skillApiError(res, '获取技能列表失败');
  return res.json();
}

export async function listRegisteredTools(): Promise<RegisteredToolsResponse> {
  const res = await fetch(`${BASE}/registered-tools`, { credentials: 'include' });
  if (!res.ok) throw await skillApiError(res, '获取已注册工具失败');
  return res.json();
}

export async function getSkill(id: string): Promise<SkillDetail> {
  const res = await fetch(`${BASE}/${id}`, { credentials: 'include' });
  if (!res.ok) throw await skillApiError(res, '获取技能详情失败');
  return res.json();
}

export async function createSkill(payload: CreateSkillPayload): Promise<AgentSkill> {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await skillApiError(res, '创建技能失败');
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
  if (!res.ok) throw await skillApiError(res, '更新技能失败');
  return res.json();
}

export async function publishVersion(
  skillId: string,
  payload: PublishVersionPayload,
): Promise<PublishVersionResponse> {
  const res = await fetch(`${BASE}/${skillId}/versions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await skillApiError(res, '发布版本失败');
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
  if (!res.ok) throw await skillApiError(res, '回滚版本失败');
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
  if (!res.ok) throw await skillApiError(res, '获取版本差异失败');
  return res.json();
}
