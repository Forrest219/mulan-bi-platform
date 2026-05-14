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
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface AgentMessageItem {
  id: number;
  role: string;
  content: string;
  response_type: string | null;
  response_data?: unknown;
  run_id?: string | null;
  explainability?: AgentExplainability | null;
  tools_used: string[] | null;
  trace_id: string | null;
  steps_count: number | null;
  execution_time_ms: number | null;
  sources_count: number | null;
  top_sources: string[] | null;
  created_at: string;
}

export type AgentMode = 'legacy_only' | 'agent_with_fallback' | 'agent_only' | 'dual_write';
export type ExplainabilityPhase = 'intent' | 'plan' | 'execution' | 'postprocess' | 'fallback';
export type ExplainabilityStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface IntentExplain {
  intent: 'query' | 'analysis' | 'report' | 'chart' | 'schema_inventory' | 'chat' | 'unsupported' | 'ambiguous';
  confidence?: number;
  strategy: 'router_guardrail' | 'context_aware' | 'keyword_match' | 'llm_classify' | 'deterministic' | 'fallback';
  guardrail: {
    decision: 'allow' | 'fallback' | 'reject';
    reason_code?: string;
    message?: string;
  };
  entities?: Array<{ type: 'metric' | 'dimension' | 'time_range' | 'datasource'; name: string; canonical?: string }>;
}

export interface PlanExplain {
  plan_id: string;
  datasource?: { connection_id?: number; name?: string; type?: string };
  semantic_operators: Array<{
    id: string;
    op: 'select' | 'filter' | 'aggregate' | 'group_by' | 'order_by' | 'limit' | 'compare' | 'trend' | 'chart' | string;
    label: string;
    fields?: string[];
    metrics?: string[];
    time_range?: string;
  }>;
  pushdown: {
    enabled: boolean;
    target: 'mcp' | 'tableau_vizql' | 'sql' | 'none';
    reason?: string;
    filters?: string[];
    aggregations?: string[];
  };
  query_plan_context?: {
    grain?: string;
    filters?: string[];
    metrics?: string[];
    dimensions?: string[];
    limit?: number;
  };
}

export interface ExecutionExplainStep {
  step_id: string;
  step_number: number;
  phase: ExplainabilityPhase;
  status: 'pending' | 'running' | 'success' | 'failed' | 'skipped';
  title: string;
  detail?: string;
  tool_name?: string;
  duration_ms?: number;
  params_preview?: Record<string, unknown>;
  result_preview?: string;
  error_code?: string;
}

export interface ExecutionExplain {
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  steps: ExecutionExplainStep[];
}

export interface PostprocessExplain {
  response_type: 'text' | 'table' | 'number' | 'chart' | 'error' | string;
  row_count?: number;
  displayed_row_count?: number;
  chart_generated?: boolean;
  field_substitutions?: Array<{ requested: string; used: string; reason?: string }>;
  formatting?: Array<'markdown_summary' | 'table_data' | 'chart_data' | 'source_footnote' | string>;
  warnings?: Array<{ code: string; message: string }>;
}

export interface FallbackExplain {
  occurred: boolean;
  chain: Array<{
    from: 'router_guardrail' | 'fast_mcp' | 'react_agent' | 'intent_strategy' | 'nlq' | string;
    to: 'fast_mcp' | 'react_agent' | 'nlq' | 'chat' | 'error' | string;
    reason_code: string;
    message: string;
  }>;
  final_source: 'agent' | 'fast_mcp' | 'nlq' | 'fallback' | 'error' | string;
  user_visible_message?: string;
}

export interface McpProxyRepairExplain {
  type?: string;
  path?: string;
  before?: unknown;
  after?: unknown;
  reason?: string;
}

export interface McpProxyExplain {
  chain_mode?: string;
  guardrail_decision?: 'allow' | 'repair' | 'reject' | string;
  guardrail_repairs?: McpProxyRepairExplain[];
  reject_code?: string | null;
  message?: string | null;
  user_hint?: string | null;
}

export interface AgentExplainability {
  schema_version: 'p0.1' | string;
  run_id?: string;
  trace_id?: string;
  mode?: AgentMode;
  mcp_proxy?: McpProxyExplain;
  phases: {
    intent?: IntentExplain;
    plan?: PlanExplain;
    execution?: ExecutionExplain;
    postprocess?: PostprocessExplain;
    fallback?: FallbackExplain;
  };
}

export interface AgentStreamRequest {
  question: string;
  conversation_id?: string | null;
  connection_id?: number | null;
  explain?: boolean;
  explain_detail?: 'compact' | 'debug';
}

/** SSE event types from POST /api/agent/stream */
export type AgentStreamEvent =
  | { type: 'metadata'; conversation_id: string; run_id: string; trace_id?: string; mode?: AgentMode; contract_version?: string }
  | { type: 'thinking'; content: string }
  | { type: 'tool_call'; tool: string; params: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; summary: string }
  | { type: 'explainability'; phase: ExplainabilityPhase; status: ExplainabilityStatus; payload: unknown; explainability?: AgentExplainability }
  | { type: 'token'; content: string }
  | { type: 'table_data'; fields: string[]; rows: (string | number | null)[][]; col_types: ('numeric' | 'string')[] }
  | { type: 'chart_data'; chart_type: 'bar' | 'line' | 'pie'; x_field: string | null; y_fields: string[]; series_field: string | null; data: Record<string, string | number | null>[] }
  | { type: 'done'; answer: string; trace_id: string; run_id: string; tools_used: string[]; response_type: string; response_data: unknown; steps_count: number; execution_time_ms: number; sources_count: number; top_sources: string[]; explainability?: AgentExplainability; fallback?: FallbackExplain }
  | { type: 'error'; error_code: string; message: string; user_hint?: string; explainability?: AgentExplainability; fallback?: FallbackExplain };

function asObject(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  return value as Record<string, unknown>;
}

function parseMcpProxyRepairs(value: unknown): McpProxyRepairExplain[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(asObject(item)))
    .map((item) => ({
      type: typeof item.type === 'string' ? item.type : undefined,
      path: typeof item.path === 'string' ? item.path : undefined,
      before: item.before,
      after: item.after,
      reason: typeof item.reason === 'string' ? item.reason : undefined,
    }));
}

function mcpProxyFromPayload(payload: Record<string, unknown>): McpProxyExplain | undefined {
  const detail = asObject(asObject(payload.controlled_chain)?.detail);
  const source = detail?.chain_mode === 'mcp_proxy' ? detail : payload;
  if (source.chain_mode !== 'mcp_proxy') return undefined;
  return {
    chain_mode: 'mcp_proxy',
    guardrail_decision: typeof source.guardrail_decision === 'string' ? source.guardrail_decision : undefined,
    guardrail_repairs: parseMcpProxyRepairs(source.guardrail_repairs),
    reject_code: typeof source.reject_code === 'string'
      ? source.reject_code
      : typeof payload.error_code === 'string'
        ? payload.error_code
        : null,
    message: typeof payload.message === 'string' ? payload.message : null,
    user_hint: typeof payload.user_hint === 'string' ? payload.user_hint : null,
  };
}

function withMcpProxyExplainability(explainability: AgentExplainability | undefined, payload: unknown): AgentExplainability | undefined {
  const payloadObject = asObject(payload);
  const mcpProxy = payloadObject ? mcpProxyFromPayload(payloadObject) : undefined;
  if (!mcpProxy) return explainability;
  return {
    schema_version: explainability?.schema_version ?? 'p0.1',
    run_id: explainability?.run_id,
    trace_id: explainability?.trace_id,
    mode: explainability?.mode,
    phases: { ...(explainability?.phases ?? {}) },
    mcp_proxy: mcpProxy,
  };
}

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
            explain: req.explain ?? true,
            explain_detail: req.explain_detail ?? 'compact',
          }),
          signal,
        });

        if (!response.ok || !response.body) {
          controller.enqueue({
            type: 'error',
            error_code: `HTTP_${response.status}`,
            message: `请求失败: HTTP ${response.status}`,
          } as AgentStreamEvent);
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
                  trace_id: raw['trace_id'] as string | undefined,
                  mode: raw['mode'] as AgentMode | undefined,
                  contract_version: raw['contract_version'] as string | undefined,
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
              } else if (raw['type'] === 'explainability') {
                controller.enqueue({
                  type: 'explainability',
                  phase: raw['phase'] as ExplainabilityPhase,
                  status: (raw['status'] as ExplainabilityStatus) ?? 'completed',
                  payload: raw['payload'] as unknown,
                  explainability: raw['explainability'] as AgentExplainability | undefined,
                });
              } else if (raw['type'] === 'token') {
                controller.enqueue({
                  type: 'token',
                  content: raw['content'] as string,
                });
              } else if (raw['type'] === 'table_data') {
                controller.enqueue({
                  type: 'table_data',
                  fields: (raw['fields'] as string[]) ?? [],
                  rows: (raw['rows'] as (string | number | null)[][]) ?? [],
                  col_types: (raw['col_types'] as ('numeric' | 'string')[]) ?? [],
                });
              } else if (raw['type'] === 'chart_data') {
                controller.enqueue({
                  type: 'chart_data',
                  chart_type: (raw['chart_type'] as 'bar' | 'line' | 'pie') ?? 'bar',
                  x_field: (raw['x_field'] as string | null) ?? null,
                  y_fields: (raw['y_fields'] as string[]) ?? [],
                  series_field: (raw['series_field'] as string | null) ?? null,
                  data: (raw['data'] as Record<string, string | number | null>[]) ?? [],
                });
              } else if (raw['type'] === 'done') {
                const responseData = raw['response_data'] as unknown;
                controller.enqueue({
                  type: 'done',
                  answer: raw['answer'] as string ?? '',
                  trace_id: raw['trace_id'] as string ?? '',
                  run_id: raw['run_id'] as string ?? '',
                  tools_used: (raw['tools_used'] as string[]) ?? [],
                  response_type: raw['response_type'] as string ?? 'text',
                  response_data: responseData,
                  steps_count: (raw['steps_count'] as number) ?? 0,
                  execution_time_ms: (raw['execution_time_ms'] as number) ?? 0,
                  sources_count: (raw['sources_count'] as number) ?? 0,
                  top_sources: (raw['top_sources'] as string[]) ?? [],
                  explainability: withMcpProxyExplainability(raw['explainability'] as AgentExplainability | undefined, responseData),
                  fallback: raw['fallback'] as FallbackExplain | undefined,
                });
              } else if (raw['type'] === 'error') {
                controller.enqueue({
                  type: 'error',
                  error_code: raw['error_code'] as string ?? 'AGENT_ERROR',
                  message: raw['message'] as string ?? '未知错误',
                  user_hint: raw['user_hint'] as string | undefined,
                  explainability: withMcpProxyExplainability(raw['explainability'] as AgentExplainability | undefined, raw),
                  fallback: raw['fallback'] as FallbackExplain | undefined,
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
   * GET /api/agent/conversations/{id} — 获取单个会话元数据（含 connection_id）
   */
  getConversation: (conversationId: string): Promise<AgentConversationItem> =>
    fetch(`/api/agent/conversations/${conversationId}`, {
      credentials: 'include',
    }).then((r) => {
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
   * PATCH /api/agent/conversations/{id} — 更新 Data Agent 会话标题
   */
  updateConversationTitle: (conversationId: string, title: string): Promise<AgentConversationItem> =>
    fetch(`/api/agent/conversations/${conversationId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }).then((r) => {
      if (!r.ok) throw new Error(`重命名失败: HTTP ${r.status}`);
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
  username: string | null;
  question: string;
  /** Run status returned by admin API: running / completed / failed (legacy error may still appear in old data). */
  status: string;
  execution_time_ms: number | null;
  tools_used: string[] | null;
  created_at: string | null;
  feedback: 'up' | 'down' | null;
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
  duration_source: 'recorded' | 'derived' | 'none';
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
  username: string | null;
  title: string | null;
  connection_id: number | null;
  connection_name: string | null;
  status: string;
  message_count: number;
  runs_count: number;
  latest_run_id: string | null;
  latest_run_status: string | null;
  latest_run_created_at: string | null;
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
  username: string | null;
  title: string | null;
  connection_id: number | null;
  connection_name: string | null;
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
    run_id?: string;
  }): Promise<AgentRunsResponse> => {
    const query = new URLSearchParams({
      limit: String(params.limit),
      offset: String(params.offset),
      ...(params.status ? { status: params.status } : {}),
      ...(params.run_id ? { run_id: params.run_id } : {}),
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
