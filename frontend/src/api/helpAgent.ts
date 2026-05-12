import { API_BASE } from '../config';

export type HelpAgentEntryPoint = 'global_drawer' | 'inline_panel' | 'route_page';

export interface HelpPageContext {
  entry_point?: HelpAgentEntryPoint;
  path: string;
  query: Record<string, string>;
  selection?: {
    run_id?: string;
    task_run_id?: number;
    connection_id?: number;
    skill_key?: string;
    asset_id?: number;
  };
  visible_state?: {
    status?: string;
    error_code?: string;
    expanded?: boolean;
  };
  client_time: string;
}

export interface HelpAgentStreamRequest {
  question: string;
  conversation_id?: string | null;
  entry_point?: HelpAgentEntryPoint;
  page_context?: HelpPageContext;
}

export type DiagnosticStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface HelpDiagnosticProgressEvent {
  type: 'diagnostic_progress';
  run_id?: string;
  step_key: string;
  parent_step_key?: string | null;
  parallel_group?: string | null;
  level?: number;
  label: string;
  status: DiagnosticStepStatus;
  started_at?: string | null;
  finished_at?: string | null;
  execution_time_ms?: number | null;
  snapshot_at?: string | null;
  message?: string;
  error_summary?: string;
}

export type HelpAgentStreamEvent =
  | { type: 'metadata'; conversation_id: string; run_id: string }
  | { type: 'thinking'; content: string }
  | HelpDiagnosticProgressEvent
  | { type: 'tool_call'; tool: string; params: Record<string, unknown>; step_key?: string }
  | { type: 'tool_result'; tool: string; summary: string; step_key?: string; snapshot_at?: string | null }
  | { type: 'token'; content: string }
  | {
      type: 'done';
      answer: string;
      trace_id: string;
      run_id: string;
      tools_used: string[];
      response_type: string;
      response_data: unknown;
      steps_count: number;
      execution_time_ms: number;
      sources_count: number;
      top_sources: string[];
    }
  | { type: 'error'; error_code: string; message: string; user_hint?: string };

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function parseHelpEvent(raw: Record<string, unknown>): HelpAgentStreamEvent | null {
  switch (raw.type) {
    case 'metadata':
      return {
        type: 'metadata',
        conversation_id: String(raw.conversation_id ?? ''),
        run_id: String(raw.run_id ?? ''),
      };
    case 'thinking':
      return { type: 'thinking', content: String(raw.content ?? '') };
    case 'diagnostic_progress':
      return {
        type: 'diagnostic_progress',
        run_id: raw.run_id == null ? undefined : String(raw.run_id),
        step_key: String(raw.step_key ?? ''),
        parent_step_key: raw.parent_step_key == null ? null : String(raw.parent_step_key),
        parallel_group: raw.parallel_group == null ? null : String(raw.parallel_group),
        level: typeof raw.level === 'number' ? raw.level : undefined,
        label: String(raw.label ?? '诊断步骤'),
        status: (raw.status as DiagnosticStepStatus) ?? 'pending',
        started_at: raw.started_at == null ? null : String(raw.started_at),
        finished_at: raw.finished_at == null ? null : String(raw.finished_at),
        execution_time_ms: typeof raw.execution_time_ms === 'number' ? raw.execution_time_ms : null,
        snapshot_at: raw.snapshot_at == null ? null : String(raw.snapshot_at),
        message: raw.message == null ? undefined : String(raw.message),
        error_summary: raw.error_summary == null ? undefined : String(raw.error_summary),
      };
    case 'tool_call':
      return {
        type: 'tool_call',
        tool: String(raw.tool ?? ''),
        params: asRecord(raw.params),
        step_key: raw.step_key == null ? undefined : String(raw.step_key),
      };
    case 'tool_result':
      return {
        type: 'tool_result',
        tool: String(raw.tool ?? ''),
        summary: String(raw.summary ?? ''),
        step_key: raw.step_key == null ? undefined : String(raw.step_key),
        snapshot_at: raw.snapshot_at == null ? null : String(raw.snapshot_at),
      };
    case 'token':
      return { type: 'token', content: String(raw.content ?? '') };
    case 'done':
      return {
        type: 'done',
        answer: String(raw.answer ?? ''),
        trace_id: String(raw.trace_id ?? ''),
        run_id: String(raw.run_id ?? ''),
        tools_used: Array.isArray(raw.tools_used) ? raw.tools_used.map(String) : [],
        response_type: String(raw.response_type ?? 'help'),
        response_data: raw.response_data,
        steps_count: typeof raw.steps_count === 'number' ? raw.steps_count : 0,
        execution_time_ms: typeof raw.execution_time_ms === 'number' ? raw.execution_time_ms : 0,
        sources_count: typeof raw.sources_count === 'number' ? raw.sources_count : 0,
        top_sources: Array.isArray(raw.top_sources) ? raw.top_sources.map(String) : [],
      };
    case 'error':
      return {
        type: 'error',
        error_code: String(raw.error_code ?? 'HELP_AGENT_ERROR'),
        message: String(raw.message ?? '诊断请求失败'),
        user_hint: raw.user_hint == null ? undefined : String(raw.user_hint),
      };
    default:
      return null;
  }
}

function extractSsePayloads(chunk: string): string[] {
  return chunk
    .split('\n')
    .filter((line) => line.trimStart().startsWith('data:'))
    .map((line) => line.slice(line.indexOf('data:') + 5).trim())
    .filter(Boolean);
}

export function streamHelpAgent(
  req: HelpAgentStreamRequest,
  signal: AbortSignal
): ReadableStream<HelpAgentStreamEvent> {
  return new ReadableStream({
    async start(controller) {
      try {
        const response = await fetch(`${API_BASE}/api/help-agent/stream`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: req.question,
            conversation_id: req.conversation_id ?? null,
            entry_point: req.entry_point ?? 'global_drawer',
            page_context: req.page_context,
          }),
          signal,
        });

        if (!response.ok || !response.body) {
          let message = `请求失败: HTTP ${response.status}`;
          let userHint: string | undefined;
          const body = await response.json().catch(() => null);
          const detail = asRecord(asRecord(body).detail);
          if (typeof detail.message === 'string') message = detail.message;
          if (typeof detail.user_hint === 'string') userHint = detail.user_hint;
          controller.enqueue({
            type: 'error',
            error_code: `HTTP_${response.status}`,
            message,
            user_hint: userHint,
          });
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split(/\r?\n\r?\n/);
          buffer = parts.pop() ?? '';

          for (const part of parts) {
            for (const payload of extractSsePayloads(part)) {
              if (payload === '[DONE]') continue;
              try {
                const event = parseHelpEvent(JSON.parse(payload) as Record<string, unknown>);
                if (event) controller.enqueue(event);
              } catch {
                // Ignore malformed SSE payloads while keeping the stream alive.
              }
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          controller.enqueue({
            type: 'error',
            error_code: 'STREAM_ERROR',
            message: err.message,
            user_hint: '请稍后重试；如果持续失败，请联系管理员查看 Help Agent 服务状态。',
          });
        }
      } finally {
        controller.close();
      }
    },
  });
}
