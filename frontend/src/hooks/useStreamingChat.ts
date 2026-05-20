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
import type {
  AgentExplainability,
  AgentMode,
  ExplainabilityPhase,
  ExplainabilityStatus,
  FallbackExplain,
} from '../api/agent';

export interface TableData {
  fields: string[];
  rows: (string | number | null)[][];
  col_types: ('numeric' | 'string')[];
  table_display?: TableDisplay;
}

export type TableDisplayAlign = 'left' | 'right' | 'center';
export type TableDisplayFormat = 'plain' | 'number' | 'integer' | 'percent' | 'date';

export interface TableDisplayColumn {
  key?: string;
  label?: string;
  semantic_type?: 'dimension' | 'metric' | 'derived_metric' | 'rank' | 'period' | 'flag' | 'text' | string;
  value_type?: 'string' | 'number' | 'percent' | 'date' | 'boolean' | string;
  align?: TableDisplayAlign;
  format?: TableDisplayFormat;
}

export interface TableDisplay {
  columns?: TableDisplayColumn[];
}

export interface ChartData {
  chart_type: 'bar' | 'line' | 'pie';
  x_field: string | null;
  y_fields: string[];
  series_field: string | null;
  data: Record<string, string | number | null>[];
}

export interface StreamingMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isError?: boolean;
  metadata?: { sources_count: number; top_sources: string[] };
  traceId?: string;           // run_id — Spec 36 §5.2 done event
  executionTimeMs?: number;   // Spec 36 §5.2 done event execution_time_ms
  thinking?: string;         // ReAct reasoning text
  toolsUsed?: string[];      // tools called
  toolCalls?: Array<{ tool: string; params: Record<string, unknown> }>;
  toolResults?: Array<{ tool: string; summary: string }>;
  /** conversation_id returned by metadata event; trumps any locally-generated ID */
  conversationId?: string;
  /** response_type from done event (e.g. 'text', 'table', 'chart') */
  responseType?: string;
  /** Structured response_data from done event — rendered by AgentStructuredResponse */
  responseData?: unknown;
  /** Structured table data from table_data event — rendered as QueryResultTable */
  tableData?: TableData;
  /** Structured chart data from chart_data event — rendered as QueryResultChart */
  chartData?: ChartData;
  /** steps_count from done event */
  stepsCount?: number;
  /** ISO timestamp of when the message was created locally */
  timestamp?: string;
  /** error_code when isError=true — used by MessageBubble to pick icon */
  errorCode?: string;
  /** user-readable error hint from backend — shown as secondary text */
  errorHint?: string;
  /** Structured user-visible analysis process for P0 Explainability UI */
  explainability?: AgentExplainability;
  explainabilityEvents?: Array<{
    phase: ExplainabilityPhase;
    status: ExplainabilityStatus;
    payload: unknown;
    receivedAt: string;
  }>;
  fallback?: FallbackExplain;
}

function ensureExplainability(current?: AgentExplainability, meta?: { runId?: string; traceId?: string; mode?: AgentMode }): AgentExplainability {
  return {
    schema_version: current?.schema_version ?? 'p0.1',
    run_id: current?.run_id ?? meta?.runId,
    trace_id: current?.trace_id ?? meta?.traceId,
    mode: current?.mode ?? meta?.mode,
    phases: { ...(current?.phases ?? {}) },
  };
}

function mergeExplainabilityPhase(
  current: AgentExplainability | undefined,
  phase: ExplainabilityPhase,
  payload: unknown,
): AgentExplainability {
  const base = ensureExplainability(current);
  return {
    ...base,
    phases: {
      ...base.phases,
      [phase]: payload as AgentExplainability['phases'][ExplainabilityPhase],
    },
  };
}

function appendToolCallStep(current: AgentExplainability | undefined, tool: string, params: Record<string, unknown>): AgentExplainability {
  const base = ensureExplainability(current);
  const steps = base.phases.execution?.steps ?? [];
  return {
    ...base,
    phases: {
      ...base.phases,
      execution: {
        status: 'running',
        steps: [
          ...steps,
          {
            step_id: `tool-call-${steps.length + 1}`,
            step_number: steps.length + 1,
            phase: 'execution',
            status: 'running',
            title: `执行 ${tool}`,
            tool_name: tool,
            params_preview: params,
          },
        ],
      },
    },
  };
}

function appendToolResultStep(current: AgentExplainability | undefined, tool: string, summary: string): AgentExplainability {
  const base = ensureExplainability(current);
  const steps = base.phases.execution?.steps ?? [];
  const lastPendingIndex = [...steps].reverse().findIndex((step) => step.tool_name === tool && step.status === 'running');
  if (lastPendingIndex >= 0) {
    const index = steps.length - 1 - lastPendingIndex;
    const nextSteps = steps.map((step, idx) => idx === index ? { ...step, status: 'success' as const, result_preview: summary } : step);
    return { ...base, phases: { ...base.phases, execution: { status: 'completed', steps: nextSteps } } };
  }
  return {
    ...base,
    phases: {
      ...base.phases,
      execution: {
        status: 'completed',
        steps: [
          ...steps,
          {
            step_id: `tool-result-${steps.length + 1}`,
            step_number: steps.length + 1,
            phase: 'execution',
            status: 'success',
            title: `${tool} 返回结果`,
            tool_name: tool,
            result_preview: summary,
          },
        ],
      },
    },
  };
}

export function tableDataFromStructuredPayload(
  payload: unknown,
  responseType?: string,
): TableData | undefined {
  if (responseType !== undefined && responseType !== 'table' && responseType !== 'query_result') return undefined;
  if (!payload || typeof payload !== 'object') return undefined;
  const data = payload as { fields?: unknown; rows?: unknown; col_types?: unknown; table_display?: unknown };
  if (!Array.isArray(data.fields) || !Array.isArray(data.rows) || data.fields.length === 0 || data.rows.length === 0) {
    return undefined;
  }
  const fields = data.fields.map((field) => String(field));
  const rows = data.rows.filter(Array.isArray) as (string | number | null)[][];
  if (rows.length === 0) return undefined;
  const col_types = parseColTypes(data.col_types, fields, rows);
  const table_display = parseTableDisplay(data.table_display);
  return { fields, rows, col_types, ...(table_display ? { table_display } : {}) };
}

function parseColTypes(
  value: unknown,
  fields: string[],
  rows: (string | number | null)[][],
): ('numeric' | 'string')[] {
  if (Array.isArray(value) && value.length === fields.length) {
    return value.map((item) => item === 'numeric' ? 'numeric' : 'string');
  }
  return fields.map((_, i) => {
    const sample = rows.slice(0, 5).map((row) => row[i]).filter((cell) => cell != null && cell !== '');
    return sample.length > 0 && sample.every((cell) => typeof cell === 'number') ? 'numeric' : 'string';
  });
}

function parseTableDisplay(value: unknown): TableDisplay | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const columns = (value as { columns?: unknown }).columns;
  if (!Array.isArray(columns)) return undefined;
  return {
    columns: columns
      .filter((column): column is Record<string, unknown> => !!column && typeof column === 'object')
      .map((column) => ({
        key: typeof column.key === 'string' ? column.key : undefined,
        label: typeof column.label === 'string' ? column.label : undefined,
        semantic_type: typeof column.semantic_type === 'string' ? column.semantic_type : undefined,
        value_type: typeof column.value_type === 'string' ? column.value_type : undefined,
        align: column.align === 'left' || column.align === 'right' || column.align === 'center'
          ? column.align
          : undefined,
        format: column.format === 'plain' || column.format === 'number' || column.format === 'integer' || column.format === 'percent' || column.format === 'date'
          ? column.format
          : undefined,
      })),
  };
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
      const now = new Date().toISOString();
      const userMsg: StreamingMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content: question,
        timestamp: now,
      };
      const assistantId = crypto.randomUUID();
      const assistantMsg: StreamingMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        isStreaming: true,
        timestamp: now,
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
            // conversation_id is returned here; sources metadata comes in the done event
            const id = streamingIdRef.current;
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? {
                        ...m,
                        conversationId: event.conversation_id,
                        traceId: event.run_id,
                        explainability: ensureExplainability(m.explainability, {
                          runId: event.run_id,
                          traceId: event.trace_id,
                          mode: event.mode,
                        }),
                      }
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
                        explainability: appendToolCallStep(m.explainability, event.tool, event.params),
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
                    ? {
                        ...m,
                        toolResults: [...(m.toolResults ?? []), { tool: event.tool, summary: event.summary }],
                        explainability: appendToolResultStep(m.explainability, event.tool, event.summary),
                      }
                    : m,
                ),
              );
            }
          } else if (event.type === 'explainability') {
            const id = streamingIdRef.current;
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? {
                        ...m,
                        explainability: event.explainability ?? mergeExplainabilityPhase(m.explainability, event.phase, event.payload),
                        explainabilityEvents: [
                          ...(m.explainabilityEvents ?? []),
                          {
                            phase: event.phase,
                            status: event.status,
                            payload: event.payload,
                            receivedAt: new Date().toISOString(),
                          },
                        ],
                        fallback: event.phase === 'fallback' ? event.payload as FallbackExplain : m.fallback,
                      }
                    : m,
                ),
              );
            }
          } else if (event.type === 'table_data') {
            const id = streamingIdRef.current;
            const tableData = tableDataFromStructuredPayload(event);
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? {
                        ...m,
                        tableData: tableData ?? m.tableData,
                      }
                    : m,
                ),
              );
            }
          } else if (event.type === 'chart_data') {
            const id = streamingIdRef.current;
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? { ...m, chartData: { chart_type: event.chart_type, x_field: event.x_field, y_fields: event.y_fields, series_field: event.series_field, data: event.data } }
                    : m,
                ),
              );
            }
          } else if (event.type === 'token') {
            bufferRef.current += event.content;
          } else if (event.type === 'done') {
            const id = streamingIdRef.current;
            const tableData = tableDataFromStructuredPayload(event.response_data, event.response_type);
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? {
                        ...m,
                        traceId: event.run_id,
                        executionTimeMs: event.execution_time_ms,
                        responseType: event.response_type,
                        responseData: event.response_data,
                        tableData: tableData ?? m.tableData,
                        stepsCount: event.steps_count,
                        metadata: { sources_count: event.sources_count, top_sources: event.top_sources },
                        explainability: event.explainability ?? m.explainability,
                        fallback: event.fallback ?? event.explainability?.phases.fallback ?? m.fallback,
                      }
                    : m,
                ),
              );
            }
            done = true;
          } else if (event.type === 'error') {
            const id = streamingIdRef.current;
            if (id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? {
                        ...m,
                        isError: true,
                        errorCode: event.error_code,
                        errorHint: event.user_hint,
                        explainability: event.explainability ?? m.explainability,
                        fallback: event.fallback ?? event.explainability?.phases.fallback ?? m.fallback,
                      }
                    : m,
                ),
              );
            }
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
