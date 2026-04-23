/**
 * useQuerySessions — 历史会话列表获取与刷新
 *
 * 返回：
 *   sessions    — 会话列表
 *   loading     — 首次加载中
 *   error       — 错误信息（null = 无错误）
 *   refresh()   — 手动刷新
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { listQuerySessions, type QuerySession } from '../api/query';

export interface UseQuerySessionsReturn {
  sessions: QuerySession[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useQuerySessions(): UseQuerySessionsReturn {
  const [sessions, setSessions] = useState<QuerySession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 用 ref 避免 fetch 并发 state 竞争
  const abortRef = useRef<AbortController | null>(null);

  const fetchSessions = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setLoading(true);
    setError(null);

    try {
      const data = await listQuerySessions();
      if (ctrl.signal.aborted) return;
      setSessions(data);
    } catch (err) {
      if (ctrl.signal.aborted) return;
      setError(err instanceof Error ? err.message : '加载会话列表失败');
    } finally {
      if (!ctrl.signal.aborted) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void fetchSessions();
    return () => {
      abortRef.current?.abort();
    };
  }, [fetchSessions]);

  const refresh = useCallback(() => {
    void fetchSessions();
  }, [fetchSessions]);

  return { sessions, loading, error, refresh };
}
