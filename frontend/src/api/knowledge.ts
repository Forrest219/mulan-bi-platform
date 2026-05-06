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
  const q = new URLSearchParams({
    title: data.title,
    content: data.content,
    format: data.format ?? 'markdown',
    category: data.category ?? 'general',
    tags: JSON.stringify(data.tags ?? []),
  });
  const res = await fetch(`${BASE}/documents?${q}`, {
    method: 'POST',
    credentials: 'include',
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
