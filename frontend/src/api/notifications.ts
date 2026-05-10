export interface AppNotification {
  id: number;
  title: string;
  content: string;
  level: 'info' | 'warning' | 'error';
  is_read: boolean;
  read_at: string | null;
  link: string | null;
  created_at: string;
}

export async function getUnreadCount(): Promise<number> {
  const resp = await fetch('/api/notifications/unread-count', { credentials: 'include' });
  if (!resp.ok) return 0;
  const data = await resp.json();
  return data.unread_count ?? 0;
}

export async function listNotifications(
  page = 1,
  pageSize = 15,
  filters?: { is_read?: boolean; level?: string },
): Promise<{ items: AppNotification[]; total: number }> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (filters?.is_read !== undefined) params.set('is_read', String(filters.is_read));
  if (filters?.level) params.set('level', filters.level);
  const resp = await fetch(`/api/notifications?${params}`, {
    credentials: 'include',
  });
  if (!resp.ok) throw new Error('获取通知失败');
  return resp.json();
}

export async function markNotificationRead(id: number): Promise<void> {
  await fetch(`/api/notifications/${id}/read`, { method: 'PUT', credentials: 'include' });
}

export async function markAllNotificationsRead(): Promise<void> {
  await fetch('/api/notifications/batch-read', {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ all: true }),
  });
}

export async function deleteNotification(id: number): Promise<void> {
  await fetch(`/api/notifications/${id}`, { method: 'DELETE', credentials: 'include' });
}

export async function markNotificationUnread(id: number): Promise<void> {
  await fetch(`/api/notifications/${id}/unread`, { method: 'PUT', credentials: 'include' });
}
