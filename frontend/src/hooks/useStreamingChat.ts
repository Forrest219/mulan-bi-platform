/**
 * useStreamingChat — Gap-05 SSE Streaming Chat Hook
 * Updated to use POST /api/agent/stream (Spec 36 §5)
 *
 * spec §8.5 + §11 陷阱6：
 * - 状态完全隔离于 AskBar（AskBar 的 input/attachedFiles 不被 re-render 污染）
 * - useRef buffer + requestAnimationFrame batch flush（每 ~16ms 一次，不是 per-token）
 * - fetch + ReadableStream 消费 text/event-stream
 * - AbortController 支持 stopStreaming()
 */
import { useState, useRef, useCallback } from 'react';
import { streamAgent } from '../api/agent';

export interface StreamingMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isError?: boolean;
  metadata?: { sources_count: number; top_sources: string[] };
  traceId?: string;
  thinking?: string;        // ReAct reasoning text
  toolsUsed?: string[];     // tools called
  toolCalls?: Array<{ tool: string; params: Record<string, unknown> }>;
  toolResults?: Array<{ tool: string; summary: string }>;
}

export interface UseStreamingChatReturn {
  messages: StreamingMessage[];
  isStreaming: boolean;
  sendMessage: (question: string, connectionId?: number, conversationId?: string | null) => Promise<void>;
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
    async (question: string, connectionId?: number, conversationId?: string | null) => {
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

      abortRef.current = new AbortController();

      try {
        const stream = streamAgent(
          { question, connection_id: connectionId, conversation_id: conversationId },
          abortRef.current.signal
        );
        const reader = stream.getReader();
        let done = false;

        while (!done) {
          const { done: streamDone, value } = await reader.read();
          if (streamDone) break;
          const event = value;

          if (event.type === 'metadata') {
            // Store conversation_id / run_id in metadata
            const id = streamingIdRef.current;
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? { ...m, metadata: { sources_count: 0, top_sources: [] } }
                    : m,
                ),
              );
            }
          } else if (event.type === 'thinking') {
            // Accumulate thinking text
            const id = streamingIdRef.current;
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id ? { ...m, thinking: (m.thinking ?? '') + event.content } : m,
                ),
              );
            }
          } else if (event.type === 'tool_call') {
            const id = streamingIdRef.current;
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? {
                        ...m,
                        toolCalls: [...(m.toolCalls ?? []), { tool: event.tool, params: event.params }],
                        toolsUsed: [...(m.toolsUsed ?? []), event.tool],
                      }
                    : m,
                ),
              );
            }
          } else if (event.type === 'tool_result') {
            const id = streamingIdRef.current;
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? { ...m, toolResults: [...(m.toolResults ?? []), { tool: event.tool, summary: event.summary }] }
                    : m,
                ),
              );
            }
          } else if (event.type === 'token') {
            bufferRef.current += event.content;
          } else if (event.type === 'done') {
            const id = streamingIdRef.current;
            if (id) {
              const traceId = event.trace_id;
              setMessages((prev) =>
                prev.map((m) => (m.id === id ? { ...m, traceId } : m)),
              );
            }
            done = true;
          } else if (event.type === 'error') {
            bufferRef.current += `\n\n⚠️ ${event.message}`;
            done = true;
          }

          // Register rAF（幂等：若已有待执行 rAF 则跳过）
          if (bufferRef.current && rafRef.current === null) {
            rafRef.current = requestAnimationFrame(flushBuffer);
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          const errId = streamingIdRef.current;
          if (errId) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === errId
                  ? { ...m, content: '连接中断，请重试。', isError: true }
                  : m,
              ),
            );
          }
        }
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
