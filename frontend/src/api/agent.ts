/**
 * Data Agent API client
 * Spec 36 §5: POST /api/agent/stream, GET /api/agent/conversations,
 * GET /api/agent/conversations/{id}/messages
 */

// ─── Types ───────────────────────────────────────────────────────────────────

export interface AgentConversationItem {
  id: string;
  title: string | null;
  connection_id: number | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface AgentMessageItem {
  id: number;
  role: string;
  content: string;
  response_type: string | null;
  tools_used: string[] | null;
  trace_id: string | null;
  steps_count: number | null;
  execution_time_ms: number | null;
  created_at: string;
}

export interface AgentStreamRequest {
  question: string;
  conversation_id?: string | null;
  connection_id?: number | null;
}

/** SSE event types from POST /api/agent/stream */
export type AgentStreamEvent =
  | { type: 'metadata'; conversation_id: string; run_id: string }
  | { type: 'thinking'; content: string }
  | { type: 'tool_call'; tool: string; params: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; summary: string }
  | { type: 'token'; content: string }
  | { type: 'done'; answer: string; trace_id: string; run_id: string; tools_used: string[]; response_type: string; response_data: unknown; steps_count: number; execution_time_ms: number }
  | { type: 'error'; error_code: string; message: string };

// ─── SSE Stream ──────────────────────────────────────────────────────────────

/**
 * POST /api/agent/stream
 * Returns a ReadableStream of SSE events from the Data Agent.
 */
export function streamAgent(
  req: AgentStreamRequest,
  signal: AbortSignal
): ReadableStream<AgentStreamEvent> {
  return new ReadableStream({
    async start(controller) {
      try {
        const response = await fetch('/api/agent/stream', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: req.question,
            conversation_id: req.conversation_id ?? null,
            connection_id: req.connection_id ?? null,
          }),
          signal,
        });

        if (!response.ok || !response.body) {
          controller.enqueue({
            type: 'error',
            error_code: `HTTP_${response.status}`,
            message: `请求失败: HTTP ${response.status}`,
          } as AgentStreamEvent);
          controller.close();
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          // SSE events are separated by double newlines
          const parts = buffer.split('\n\n');
          buffer = parts.pop() ?? '';

          for (const part of parts) {
            const line = part.trim();
            if (!line.startsWith('data: ')) continue;
            const jsonStr = line.slice(6).trim();
            if (!jsonStr || jsonStr === '[DONE]') continue;

            try {
              const raw = JSON.parse(jsonStr) as Record<string, unknown>;

              if (raw['type'] === 'metadata') {
                controller.enqueue({
                  type: 'metadata',
                  conversation_id: raw['conversation_id'] as string,
                  run_id: raw['run_id'] as string,
                });
              } else if (raw['type'] === 'thinking') {
                controller.enqueue({
                  type: 'thinking',
                  content: raw['content'] as string,
                });
              } else if (raw['type'] === 'tool_call') {
                controller.enqueue({
                  type: 'tool_call',
                  tool: raw['tool'] as string,
                  params: (raw['params'] ?? {}) as Record<string, unknown>,
                });
              } else if (raw['type'] === 'tool_result') {
                controller.enqueue({
                  type: 'tool_result',
                  tool: raw['tool'] as string,
                  summary: raw['summary'] as string,
                });
              } else if (raw['type'] === 'token') {
                controller.enqueue({
                  type: 'token',
                  content: raw['content'] as string,
                });
              } else if (raw['type'] === 'done') {
                controller.enqueue({
                  type: 'done',
                  answer: raw['answer'] as string ?? '',
                  trace_id: raw['trace_id'] as string ?? '',
                  run_id: raw['run_id'] as string ?? '',
                  tools_used: (raw['tools_used'] as string[]) ?? [],
                  response_type: raw['response_type'] as string ?? 'text',
                  response_data: raw['response_data'] as unknown,
                  steps_count: (raw['steps_count'] as number) ?? 0,
                  execution_time_ms: (raw['execution_time_ms'] as number) ?? 0,
                });
              } else if (raw['type'] === 'error') {
                controller.enqueue({
                  type: 'error',
                  error_code: raw['error_code'] as string ?? 'AGENT_ERROR',
                  message: raw['message'] as string ?? '未知错误',
                });
              }
            } catch {
              // Ignore non-JSON lines
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          controller.enqueue({
            type: 'error',
            error_code: 'STREAM_ERROR',
            message: err.message,
          } as AgentStreamEvent);
        }
      } finally {
        controller.close();
      }
    },
  });
}

// ─── Conversations API ────────────────────────────────────────────────────────

export const agentConversationsApi = {
  /**
   * GET /api/agent/conversations
   */
  list: (): Promise<AgentConversationItem[]> =>
    fetch('/api/agent/conversations', { credentials: 'include' }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),

  /**
   * GET /api/agent/conversations/{id}/messages
   */
  getMessages: (conversationId: string): Promise<AgentMessageItem[]> =>
    fetch(`/api/agent/conversations/${conversationId}/messages`, {
      credentials: 'include',
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),

  /**
   * DELETE /api/agent/conversations/{id} — 归档会话（Spec 36 §5）
   */
  deleteConversation: (conversationId: string): Promise<void> =>
    fetch(`/api/agent/conversations/${conversationId}`, {
      method: 'DELETE',
      credentials: 'include',
    }).then((r) => {
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
    }),
};

// ─── Admin API ────────────────────────────────────────────────────────────────
// Spec 36 §5: GET /api/admin/agent/stats, GET /api/admin/agent/runs,
//             GET /api/admin/agent/runs/{run_id}/steps

export interface AgentToolCount {
  name: string;
  count: number;
}

export interface AgentFeedbackSummary {
  up: number;
  down: number;
}

export interface AgentStats {
  total_runs: number;
  success_rate: number;
  failed_count: number;
  avg_execution_time_ms: number | null;
  p95_execution_time_ms: number | null;
  runs_today: number;
  top_tools: AgentToolCount[];
  feedback_summary: AgentFeedbackSummary;
}

export interface AgentRun {
  id: string;
  user_id: number;
  question: string;
  /** Run status returned by admin API: running / completed / failed (legacy error may still appear in old data). */
  status: string;
  execution_time_ms: number | null;
  tools_used: string[] | null;
  created_at: string | null;
}

export interface AgentRunsResponse {
  items: AgentRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface AgentStep {
  id: number;
  run_id: string;
  step_number: number;
  step_type: string;
  tool_name: string | null;
  tool_params: Record<string, unknown> | null;
  tool_result_summary: string | null;
  content: string | null;
  execution_time_ms: number | null;
  created_at: string | null;
}

// ─── Tool Discovery Types ───────────────────────────────────────────────────

export interface AgentToolMetadata {
  name: string;
  description: string;
  parameters_schema: Record<string, unknown>;
  category: string;
  version: string;
  dependencies: string[];
  tags: string[];
}

// ─── Session Monitoring Types ───────────────────────────────────────────────

export interface AgentSessionItem {
  id: string;
  user_id: number;
  title: string | null;
  connection_id: number | null;
  status: string;
  message_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface AgentSessionsResponse {
  items: AgentSessionItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AgentSessionMessage {
  id: number;
  role: string;
  content: string;
  response_type: string | null;
  tools_used: string[] | null;
  trace_id: string | null;
  steps_count: number | null;
  execution_time_ms: number | null;
  created_at: string | null;
}

export interface AgentSessionDetail {
  id: string;
  user_id: number;
  title: string | null;
  connection_id: number | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  messages: AgentSessionMessage[];
  runs: AgentRun[];
}

export const agentAdminApi = {
  /**
   * GET /api/admin/agent/stats
   */
  getStats: (): Promise<AgentStats> =>
    fetch('/api/admin/agent/stats', { credentials: 'include' }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),

  /**
   * GET /api/admin/agent/runs?limit=&offset=&status=
   * status filter uses running / completed / failed; backend also accepts legacy error.
   */
  getRuns: (params: {
    limit: number;
    offset: number;
    /** Optional status filter: running / completed / failed. Legacy error remains backend-compatible. */
    status?: string;
  }): Promise<AgentRunsResponse> => {
    const query = new URLSearchParams({
      limit: String(params.limit),
      offset: String(params.offset),
      ...(params.status ? { status: params.status } : {}),
    });
    return fetch(`/api/admin/agent/runs?${query}`, {
      credentials: 'include',
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });
  },

  /**
   * GET /api/admin/agent/runs/{run_id}/steps
   */
  getRunSteps: (runId: string): Promise<AgentStep[]> =>
    fetch(`/api/admin/agent/runs/${runId}/steps`, {
      credentials: 'include',
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),

  /**
   * GET /api/agent/tools — 工具动态发现
   */
  getTools: (category?: string): Promise<AgentToolMetadata[]> => {
    const query = category ? `?category=${encodeURIComponent(category)}` : '';
    return fetch(`/api/agent/tools${query}`, {
      credentials: 'include',
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });
  },

  /**
   * GET /api/admin/agent/sessions — 会话列表
   */
  getSessions: (params: {
    limit: number;
    offset: number;
    status?: string;
  }): Promise<AgentSessionsResponse> => {
    const query = new URLSearchParams({
      limit: String(params.limit),
      offset: String(params.offset),
      ...(params.status ? { status: params.status } : {}),
    });
    return fetch(`/api/admin/agent/sessions?${query}`, {
      credentials: 'include',
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });
  },

  /**
   * GET /api/admin/agent/sessions/{id} — 会话详情
   */
  getSessionDetail: (sessionId: string): Promise<AgentSessionDetail> =>
    fetch(`/api/admin/agent/sessions/${sessionId}`, {
      credentials: 'include',
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }),
};
