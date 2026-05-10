import { API_BASE } from '../config';

export interface TokenTodayStats {
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_trend_pct: number | null;
  prompt_trend_pct: number | null;
  completion_trend_pct: number | null;
}

export interface ModelTokenStats {
  model: string;
  provider: string;
  total_tokens: number;
  percentage: number;
}

export interface TopUser {
  user_id: number | null;
  username: string;
  total_tokens: number;
}

export interface TokenSummary {
  summary: TokenTodayStats;
  by_model: ModelTokenStats[];
  top_users: TopUser[];
}

export interface UserTokenStats {
  user_id: number | null;
  username: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
}

export interface DailyTrend {
  date: string;
  total_tokens: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
}

export async function getTokenSummary(
  startDate?: string,
  endDate?: string,
): Promise<TokenSummary> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const query = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`${API_BASE}/api/admin/token-stats/summary${query}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || '获取 Token 统计失败');
  }
  return res.json();
}

export async function getTokenTrend(
  startDate?: string,
  endDate?: string,
): Promise<DailyTrend[]> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const query = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`${API_BASE}/api/admin/token-stats/trend${query}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || '获取 Token 趋势失败');
  }
  return res.json();
}

export async function getUserTokenStats(
  startDate?: string,
  endDate?: string,
): Promise<{ users: UserTokenStats[] }> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const query = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`${API_BASE}/api/admin/token-stats/users${query}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || '获取用户 Token 明细失败');
  }
  return res.json();
}