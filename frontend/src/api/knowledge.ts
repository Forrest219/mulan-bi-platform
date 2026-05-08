const BASE = '/api/knowledge-base';

// ── Types ──────────────────────────────────────────────────────────────────────

export interface DocumentItem {
  id: number;
  title: string;
  content: string;
  format: string;
  category: string;
  tags: string[];
  status: string;
  chunk_count: number;
  last_embedded_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PagedResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ── Documents API ──────────────────────────────────────────────────────────────

export async function listDocuments(params: {
  page?: number;
  page_size?: number;
  category?: string;
}): Promise<PagedResult<DocumentItem>> {
  const q = new URLSearchParams();
  if (params.page) q.set('page', String(params.page));
  if (params.page_size) q.set('page_size', String(params.page_size));
  if (params.category) q.set('category', params.category);
  const res = await fetch(`${BASE}/documents?${q}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取文档列表失败');
  return res.json();
}

export async function createDocument(data: {
  title: string;
  content: string;
  format?: string;
  category?: string;
  tags?: string[];
}): Promise<{ id: number; message: string }> {
  const res = await fetch(`${BASE}/documents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      title: data.title,
      content: data.content,
      format: data.format ?? 'markdown',
      category: data.category ?? 'general',
      tags: data.tags ?? [],
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.message ?? '创建文档失败');
  }
  return res.json();
}

export async function deleteDocument(id: number): Promise<void> {
  const res = await fetch(`${BASE}/documents/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('删除文档失败');
}

// ── RAG 语义检索 ───────────────────────────────────────────────────────────────

export interface SearchResult {
  source_type: string;
  source_id: number;
  title: string;
  content_snippet: string;
  score: number;
}

export interface SearchResponse {
  results: SearchResult[];
  terms: { id: number; term: string; canonical_term: string; definition: string }[];
  query: string;
}

export async function searchKnowledge(q: string, top_k = 10): Promise<SearchResponse> {
  const params = new URLSearchParams({ q, top_k: String(top_k) });
  const res = await fetch(`${BASE}/search?${params}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('语义检索失败');
  return res.json();
}

// ── 术语表 ─────────────────────────────────────────────────────────────────────

export interface GlossaryItem {
  id: number;
  term: string;
  canonical_term: string;
  definition: string;
  category: string;
  synonyms: string[];
  formula: string | null;
  source: string;
  created_at: string;
}

export interface GlossaryListResponse {
  items: GlossaryItem[];
  total: number;
}

export async function listGlossary(params?: {
  keyword?: string;
  category?: string;
  page?: number;
  page_size?: number;
}): Promise<GlossaryListResponse> {
  const q = new URLSearchParams();
  if (params?.keyword) q.set('keyword', params.keyword);
  if (params?.category) q.set('category', params.category);
  if (params?.page) q.set('page', String(params.page));
  if (params?.page_size) q.set('page_size', String(params.page_size));
  const res = await fetch(`${BASE}/glossary?${q}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取术语列表失败');
  return res.json();
}

export async function createGlossary(data: {
  term: string;
  canonical_term: string;
  definition: string;
  category?: string;
  synonyms?: string[];
  formula?: string;
}): Promise<{ id: number; message: string }> {
  const q = new URLSearchParams({
    term: data.term,
    canonical_term: data.canonical_term,
    definition: data.definition,
    category: data.category ?? 'concept',
    synonyms: JSON.stringify(data.synonyms ?? []),
    ...(data.formula ? { formula: data.formula } : {}),
  });
  const res = await fetch(`${BASE}/glossary?${q}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err?.detail as { message?: string })?.message ?? '创建术语失败');
  }
  return res.json();
}

export async function deleteGlossary(id: number): Promise<void> {
  const res = await fetch(`${BASE}/glossary/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('删除术语失败');
}

