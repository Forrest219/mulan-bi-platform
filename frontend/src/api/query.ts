/**
 * Query API client — 问数模块
 *
 * 对接端点：
 *   GET  /api/query/datasources?connection_id=<id>
 *   POST /api/query/ask
 *   GET  /api/query/sessions
 *   GET  /api/query/sessions/{session_id}/messages
 */

// ─── 数据源 ───────────────────────────────────────────────────────────────────

export interface QueryDatasource {
  luid: string;
  name: string;
  connection_id: number;
  description?: string;
}

export async function listQueryDatasources(
  connectionId: number,
  signal?: AbortSignal,
): Promise<QueryDatasource[]> {
  const resp = await fetch(`/api/query/datasources?connection_id=${connectionId}`, {
    credentials: 'include',
    signal,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err?.detail?.message ?? err?.message ?? `HTTP ${resp.status}`);
  }
  const json = await resp.json();
  // 兼容 { items: [] } 或直接 []
  return Array.isArray(json) ? json : (json.items ?? []);
}

// ─── 会话 ─────────────────────────────────────────────────────────────────────

export interface QuerySession {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  datasource_luid?: string;
  datasource_name?: string;
  connection_id?: number;
}

export async function listQuerySessions(): Promise<QuerySession[]> {
  const resp = await fetch('/api/query/sessions', {
    credentials: 'include',
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err?.detail?.message ?? err?.message ?? `HTTP ${resp.status}`);
  }
  const json = await resp.json();
  return Array.isArray(json) ? json : (json.items ?? []);
}

// ─── 消息 ─────────────────────────────────────────────────────────────────────

export interface QueryMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export async function listQueryMessages(sessionId: string): Promise<QueryMessage[]> {
  const resp = await fetch(`/api/query/sessions/${sessionId}/messages`, {
    credentials: 'include',
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err?.detail?.message ?? err?.message ?? `HTTP ${resp.status}`);
  }
  const json = await resp.json();
  return Array.isArray(json) ? json : (json.items ?? []);
}

// ─── Ask ──────────────────────────────────────────────────────────────────────

export interface AskQueryRequest {
  message: string;
  connection_id: number;
  datasource_luid: string;
  session_id?: string;
}

export interface AskQueryResponse {
  session_id: string;
  message_id: string;
  answer: string;
  sql?: string;
  data?: unknown;
  type?: string;
  error?: string;
}

export class QueryApiError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = 'QueryApiError';
    this.code = code;
  }
}

export async function askQuery(req: AskQueryRequest): Promise<AskQueryResponse> {
  const resp = await fetch('/api/query/ask', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    // P2-1：60 秒超时，避免长时间挂起
    signal: AbortSignal.timeout(60_000),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    const code = err?.detail?.code ?? err?.code ?? 'UNKNOWN';
    const msg = err?.detail?.message ?? err?.message ?? `HTTP ${resp.status}`;
    throw new QueryApiError(code, msg);
  }
  return resp.json() as Promise<AskQueryResponse>;
}

// ─── SSE 流式 Ask ─────────────────────────────────────────────────────────────

export interface AskStreamDoneResult {
  session_id: string;
  answer: string;
  data_table: unknown[];
}

/**
 * askQueryStream — 流式问数（Spec 14 §5.2）
 *
 * 使用原生 fetch + ReadableStream 消费 SSE，按 event type 分发回调：
 *   - onToken(content)  — 每个 token chunk 到达时调用，用于追加到 UI
 *   - onDone(result)    — 收到 done event 时调用，含完整 session_id / answer / data_table
 *   - onError(code, message) — 收到 error event 或网络异常时调用
 *
 * @param req     问数请求体
 * @param onToken 每个 token 回调
 * @param onDone  流结束回调
 * @param onError 错误回调
 * @param signal  AbortSignal，用于外部取消流（如用户手动停止）
 */
export async function askQueryStream(
  req: AskQueryRequest,
  onToken: (content: string) => void,
  onDone: (result: AskStreamDoneResult) => void,
  onError: (code: string, message: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch('/api/query/ask', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
      signal,
    });
  } catch (err) {
    // AbortError / TimeoutError 穿透，让 useQuerySession 的 try/catch 接收并处理
    throw err;
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const code = body?.detail?.error_code ?? body?.detail?.code ?? body?.code ?? 'UNKNOWN';
    const msg = body?.detail?.message ?? body?.message ?? `HTTP ${resp.status}`;
    onError(code, msg);
    return;
  }

  if (!resp.body) {
    onError('STREAM_ERROR', '服务器未返回流式响应体');
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE 每条消息以 \n\n 结尾，按双换行分割
      const parts = buffer.split('\n\n');
      // 最后一个可能是不完整的片段，保留到下次循环
      buffer = parts.pop() ?? '';

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;

        const jsonStr = line.slice('data:'.length).trim();
        if (!jsonStr) continue;

        let event: { type: string; content?: string; session_id?: string; answer?: string; data_table?: unknown[]; code?: string; message?: string };
        try {
          event = JSON.parse(jsonStr);
        } catch {
          // 忽略非 JSON 行（如注释行）
          continue;
        }

        if (event.type === 'token') {
          onToken(event.content ?? '');
        } else if (event.type === 'done') {
          onDone({
            session_id: event.session_id ?? '',
            answer: event.answer ?? '',
            data_table: event.data_table ?? [],
          });
        } else if (event.type === 'error') {
          onError(event.code ?? 'UNKNOWN', event.message ?? '未知错误');
        }
      }
    }
  } catch (err) {
    const errName = (err as { name?: string })?.name;
    if (errName === 'AbortError') {
      // 外部主动取消，不触发 onError
      return;
    }
    onError('STREAM_READ_ERROR', err instanceof Error ? err.message : '读取流失败');
  } finally {
    reader.releaseLock();
  }
}
