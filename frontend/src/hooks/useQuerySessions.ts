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
import { listQuerySessions, deleteQuerySession, type QuerySession } from '../api/query';

export interface UseQuerySessionsReturn {
  sessions: QuerySession[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
  /** 软删除指定会话，成功后自动刷新列表 */
  removeSession: (sessionId: string) => Promise<void>;
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

  const removeSession = useCallback(async (sessionId: string) => {
    try {
      await deleteQuerySession(sessionId);
      // 乐观删除：立即从列表移除，避免等待网络刷新
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除会话失败');
    }
  }, []);

  return { sessions, loading, error, refresh, removeSession };
}
