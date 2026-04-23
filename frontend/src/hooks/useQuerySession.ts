/**
 * useQuerySession — 管理当前问数会话状态
 *
 * 职责：
 *   - 维护 session_id、messages、loading、error
 *   - 提供 sendMessage(req) 方法：POST /api/query/ask，追加消息到列表
 *   - 提供 loadSession(session_id)：从历史记录恢复消息
 *   - 提供 resetSession()：新建会话（清空 session_id + 消息列表）
 *
 * 设计约束（CLAUDE.md 陷阱1）：
 *   内部计时/幂等值用 useRef，不用 useState，避免无限重渲染
 */
import { useState, useCallback, useRef } from 'react';
import { askQueryStream, listQueryMessages, type AskQueryRequest, type QueryApiError } from '../api/query';

export interface QuerySessionMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isError?: boolean;
  /** P2-2：预留流式输出标记，streaming 期间为 true */
  isStreaming?: boolean;
}

export interface UseQuerySessionReturn {
  sessionId: string | null;
  messages: QuerySessionMessage[];
  loading: boolean;
  error: string | null;
  /** 发送一条消息（用户输入），追加到列表并请求 AI 回复 */
  sendMessage: (req: AskQueryRequest) => Promise<void>;
  /** 从历史记录加载会话消息 */
  loadSession: (sessionId: string) => Promise<void>;
  /** 重置为新会话 */
  resetSession: () => void;
  /** 清除当前错误状态 */
  clearError: () => void;
}

export function useQuerySession(): UseQuerySessionReturn {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<QuerySessionMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ref：避免 sendMessage useCallback 依赖 sessionId state 导致无限重渲染
  const sessionIdRef = useRef<string | null>(null);
  sessionIdRef.current = sessionId;

  // P0-1：用 ref 做并发保护，避免 React 批处理窗口内读到旧 loading state
  const loadingRef = useRef(false);

  /**
   * 将错误码映射为用户友好文案（WARN-3 差异化文案）。
   * Q_PERM_002 → 权限不足提示
   * Q_JWT_001  → 账号未绑定提示
   * 其他       → 原始 message 透传
   */
  const _resolveErrorMessage = (code: string, message: string): string => {
    if (code === 'Q_PERM_002') return '您暂无该数据的访问权限';
    if (code === 'Q_JWT_001') return '您的账号尚未完成身份绑定，请联系管理员';
    return message;
  };

  // streamingMsgIdRef：记录当前正在流式追加的 assistant 消息 id，用于 onToken 定向追加
  const streamingMsgIdRef = useRef<string | null>(null);
  // abortControllerRef：用于外部取消流式请求
  const abortControllerRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async (req: AskQueryRequest) => {
    if (loadingRef.current) return;

    const userMsgId = crypto.randomUUID();
    const userMsg: QuerySessionMessage = {
      id: userMsgId,
      role: 'user',
      content: req.message,
    };

    // 乐观写入用户消息
    setMessages((prev) => [...prev, userMsg]);
    loadingRef.current = true;
    setLoading(true);
    setError(null);

    // 注入当前 session_id（若已存在）
    const reqWithSession: AskQueryRequest = sessionIdRef.current
      ? { ...req, session_id: sessionIdRef.current }
      : req;

    // 预插入一条空的 assistant 消息（isStreaming: true），token 到达时追加 content
    const assistantMsgId = crypto.randomUUID();
    streamingMsgIdRef.current = assistantMsgId;
    const placeholderMsg: QuerySessionMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      isStreaming: true,
    };
    setMessages((prev) => [...prev, placeholderMsg]);

    // 创建 AbortController 用于外部取消（如 resetSession 时）
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      await askQueryStream(
        reqWithSession,
        // onToken：追加字符到当前 assistant 消息
        (chunk) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: m.content + chunk, isStreaming: true }
                : m,
            ),
          );
        },
        // onDone：更新 session_id，标记 isStreaming: false
        (result) => {
          if (result.session_id && result.session_id !== sessionIdRef.current) {
            setSessionId(result.session_id);
            sessionIdRef.current = result.session_id;
          }
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: result.answer, isStreaming: false }
                : m,
            ),
          );
          streamingMsgIdRef.current = null;
          loadingRef.current = false;
          setLoading(false);
        },
        // onError：渲染错误气泡（差异化文案，WARN-3）
        (code, message) => {
          const errorContent = _resolveErrorMessage(code, message);
          // 将占位 assistant 消息替换为错误气泡
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: errorContent, isStreaming: false, isError: true }
                : m,
            ),
          );
          setError(errorContent);
          streamingMsgIdRef.current = null;
          loadingRef.current = false;
          setLoading(false);
        },
        abortController.signal,
      );
    } catch (err) {
      if (err instanceof DOMException &&
          (err.name === 'AbortError' || err.name === 'TimeoutError')) {
        const msg = '请求超时，请稍后重试';
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: msg, isStreaming: false, isError: true }
              : m,
          ),
        );
        setError(msg);
        streamingMsgIdRef.current = null;
        loadingRef.current = false;
        setLoading(false);
      }
    }

    // askQueryStream 是 Promise<void>，onDone/onError 内部已重置 loading 状态，
    // 此处仅做兜底（防止未触发任何回调时 loading 永远为 true）
    if (loadingRef.current) {
      loadingRef.current = false;
      setLoading(false);
    }
  }, []);

  const loadSession = useCallback(async (sid: string) => {
    setLoading(true);
    setError(null);
    try {
      const rawMessages = await listQueryMessages(sid);
      const mapped: QuerySessionMessage[] = rawMessages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
      }));
      setMessages(mapped);
      setSessionId(sid);
      sessionIdRef.current = sid;
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载会话失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const resetSession = useCallback(() => {
    // 取消正在进行中的流式请求
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    streamingMsgIdRef.current = null;
    loadingRef.current = false;
    setSessionId(null);
    sessionIdRef.current = null;
    setMessages([]);
    setError(null);
    setLoading(false);
  }, []);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  return {
    sessionId,
    messages,
    loading,
    error,
    sendMessage,
    loadSession,
    resetSession,
    clearError,
  };
}
