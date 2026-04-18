/**
 * useStreamingChat — Gap-05 SSE Streaming Chat Hook
 *
 * spec §8.5 + §11 陷阱6：
 * - 状态完全隔离于 AskBar（AskBar 的 input/attachedFiles 不被 re-render 污染）
 * - useRef buffer + requestAnimationFrame batch flush（每 ~16ms 一次，不是 per-token）
 * - fetch + ReadableStream 消费 text/event-stream
 * - AbortController 支持 stopStreaming()
 */
import { useState, useRef, useCallback } from 'react';

export interface StreamingMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
}

export interface UseStreamingChatReturn {
  messages: StreamingMessage[];
  isStreaming: boolean;
  sendMessage: (question: string, connectionId?: number) => Promise<void>;
  stopStreaming: () => void;
  /** abort — 包装 stopStreaming，供 AskBar 停止按钮使用 */
  abort: () => void;
  clearMessages: () => void;
}

export function useStreamingChat(): UseStreamingChatReturn {
  const [messages, setMessages] = useState<StreamingMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  // refs — 这些不触发 re-render，是 §11 陷阱6 的关键：
  // buffer 积累 token，rAF 每帧批量 flush，避免每 token setState
  const bufferRef = useRef('');
  const rafRef = useRef<number | null>(null);
  const streamingIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  /**
   * flushBuffer — rAF 回调：将 bufferRef 中积累的文本 append 到 assistant 消息
   * 每帧最多调用一次（约 16ms），批量合并多个 token，大幅减少 setState 次数
   */
  const flushBuffer = useCallback(() => {
    const buffered = bufferRef.current;
    bufferRef.current = '';
    rafRef.current = null;
    if (buffered && streamingIdRef.current) {
      const id = streamingIdRef.current;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, content: m.content + buffered } : m,
        ),
      );
    }
  }, []);

  /**
   * sendMessage — 发起 SSE 流式请求
   *
   * 1. 乐观写入 user 消息 + 空 assistant 消息（isStreaming=true）
   * 2. fetch GET /api/chat/stream?q=...
   * 3. ReadableStream 逐块解析 SSE，token 写入 bufferRef
   * 4. 若 bufferRef 有内容且无待执行 rAF，注册 rAF
   * 5. done/error 事件：flush 剩余 buffer，标记 isStreaming=false
   */
  const sendMessage = useCallback(
    async (question: string, connectionId?: number) => {
      const userMsg: StreamingMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content: question,
      };
      const assistantId = crypto.randomUUID();
      const assistantMsg: StreamingMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        isStreaming: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);
      streamingIdRef.current = assistantId;
      bufferRef.current = '';

      const params = new URLSearchParams({ q: question });
      if (connectionId != null) params.set('connection_id', String(connectionId));

      abortRef.current = new AbortController();

      try {
        const response = await fetch(`/api/chat/stream?${params.toString()}`, {
          signal: abortRef.current.signal,
          // credentials: 'include' 确保 cookie-based auth 正常传递
          credentials: 'include',
        });

        if (!response.body) {
          throw new Error('Response body is null — SSE not supported');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let done = false;

        while (!done) {
          const { done: streamDone, value } = await reader.read();
          if (streamDone) break;

          const text = decoder.decode(value, { stream: true });
          // SSE 可能一次 chunk 包含多行，按 \n 拆分逐行处理
          const lines = text.split('\n');

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;

            try {
              const parsed: { token?: string; done?: boolean; error?: string } =
                JSON.parse(jsonStr);

              if (parsed.done) {
                done = true;
                break;
              }

              if (parsed.error) {
                bufferRef.current += `\n\n⚠️ ${parsed.error}`;
              } else if (parsed.token) {
                bufferRef.current += parsed.token;
              }

              // 注册 rAF（幂等：若已有待执行 rAF 则跳过）
              if (bufferRef.current && rafRef.current === null) {
                rafRef.current = requestAnimationFrame(flushBuffer);
              }
            } catch {
              // 忽略非 JSON 行（SSE 注释、空行等）
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          // 网络错误：将错误信息写入 buffer
          bufferRef.current += '\n\n⚠️ 连接中断，请重试。';
        }
        // AbortError 是用户主动 stop，静默处理
      } finally {
        // 取消待执行的 rAF（避免在 finally 后 flushBuffer 访问已失效 state）
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }

        // 同步 flush 剩余 buffer（不走 rAF，直接 setState）
        const remaining = bufferRef.current;
        bufferRef.current = '';
        const finalId = streamingIdRef.current;

        if (finalId) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === finalId
                ? { ...m, content: m.content + remaining, isStreaming: false }
                : m,
            ),
          );
        }

        setIsStreaming(false);
        streamingIdRef.current = null;
      }
    },
    [flushBuffer],
  );

  /** stopStreaming — 中止当前 SSE 连接 */
  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  /** abort — 包装 stopStreaming，供 AskBar 停止按钮使用（SESSION.md 约束：不修改 stopStreaming 实现） */
  const abort = useCallback(() => {
    stopStreaming();
  }, [stopStreaming]);

  /** clearMessages — 清空消息列表（新对话） */
  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, isStreaming, sendMessage, stopStreaming, abort, clearMessages };
}
