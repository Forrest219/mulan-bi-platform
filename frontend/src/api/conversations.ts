/**
 * Conversations API client
 * 封装所有对话历史相关 API 调用
 */

export interface ConversationListItem {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail {
  id: string;
  title: string;
  updated_at: string;
  messages: ConversationMessageAPI[];
}

export interface ConversationMessageAPI {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export const conversationsApi = {
  list: (): Promise<ConversationListItem[]> =>
    fetch('/api/conversations', { credentials: 'include' }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),

  create: (title?: string): Promise<{ id: string; title: string; created_at: string; updated_at: string }> =>
    fetch('/api/conversations', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title ?? '新对话' }),
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),

  get: (id: string): Promise<ConversationDetail> =>
    fetch(`/api/conversations/${id}`, { credentials: 'include' }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),

  update: (id: string, title: string): Promise<{ id: string; title: string; updated_at: string }> =>
    fetch(`/api/conversations/${id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),

  delete: (id: string): Promise<void> =>
    fetch(`/api/conversations/${id}`, {
      method: 'DELETE',
      credentials: 'include',
    }).then((r) => {
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
    }),

  search: (q: string): Promise<ConversationListItem[]> =>
    fetch(`/api/conversations/search?q=${encodeURIComponent(q)}`, { credentials: 'include' }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),
};
