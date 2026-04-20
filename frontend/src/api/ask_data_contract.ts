/**
 * AskData 流式契约 — Spec 22 / Spec 25
 * GET /api/chat/stream 返回 text/event-stream
 */

export interface AskDataRequest {
  q: string;
  connection_id?: number;
  conversation_id?: string;
}

export type AskDataStreamEvent =
  | { type: 'token'; content: string }
  | { type: 'done'; answer: string; trace_id?: string }
  | { type: 'error'; code: string; message: string }
  | { type: 'metadata'; sources_count: number; top_sources: string[] };

export type AskDataEventHandler = (event: AskDataStreamEvent) => void;

/**
 * 真实 SSE 实现（后端就绪后使用）
 * 返回 abort 函数
 */
export function streamAskData(
  req: AskDataRequest,
  onEvent: AskDataEventHandler
): () => void {
  const controller = new AbortController();

  const params: Record<string, string> = { q: req.q };
  if (req.connection_id !== undefined) {
    params['connection_id'] = String(req.connection_id);
  }
  if (req.conversation_id !== undefined) {
    params['conversation_id'] = req.conversation_id;
  }

  (async () => {
    try {
      const response = await fetch(
        '/api/chat/stream?' + new URLSearchParams(params),
        {
          credentials: 'include',
          signal: controller.signal,
        }
      );

      if (!response.ok || !response.body) {
        onEvent({
          type: 'error',
          code: `HTTP_${response.status}`,
          message: `请求失败: HTTP ${response.status}`,
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
        const parts = buffer.split('\n\n');
        buffer = parts.pop() ?? '';

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data:')) continue;
          const jsonStr = line.slice('data:'.length).trim();
          if (!jsonStr || jsonStr === '[DONE]') continue;
          try {
            const raw = JSON.parse(jsonStr) as Record<string, unknown>;
            if (typeof raw['token'] === 'string') {
              onEvent({ type: 'token', content: raw['token'] });
            } else if (raw['done'] === true) {
              onEvent({ type: 'done', answer: '', trace_id: undefined });
            } else if (typeof raw['error'] === 'string') {
              onEvent({ type: 'error', code: 'STREAM_ERROR', message: raw['error'] });
            } else if (typeof raw['sources_count'] === 'number' || raw['type'] === 'metadata') {
              onEvent({
                type: 'metadata',
                sources_count: raw['sources_count'] as number ?? 0,
                top_sources: (raw['top_sources'] as string[]) ?? [],
              });
            }
          } catch {
            // 忽略无法解析的行
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      onEvent({
        type: 'error',
        code: 'STREAM_ERROR',
        message: err instanceof Error ? err.message : String(err),
      });
    }
  })();

  return () => controller.abort();
}

/**
 * Mock 实现 — 30 token/s，无需后端
 * 返回 abort 函数
 */
export function mockStreamAskData(
  req: AskDataRequest,
  onEvent: AskDataEventHandler
): () => void {
  const tokens = [
    '根据', '木兰', '数据', '分析，', '2024 年', 'Q4', '销售额', '同比', '增长',
    ' **23.7%**', '，', '达到', ' ¥1,280 万', '。', '\n\n',
    '主要', '驱动', '因素', '：', '\n- ', '华南', '区域', '增速', '最快（+41%）',
    '\n- ', '数字', '渠道', '占比', '首次', '超过', '50%',
  ];

  let aborted = false;
  let timeoutId: ReturnType<typeof setTimeout>;

  const emitNext = (index: number) => {
    if (aborted) return;
    if (index >= tokens.length) {
      const answer = tokens.join('');
      onEvent({ type: 'done', answer, trace_id: 'mock-trace-001' });
      return;
    }
    onEvent({ type: 'token', content: tokens[index] });
    timeoutId = setTimeout(() => emitNext(index + 1), 33);
  };

  // 触发首个 token（使用 setTimeout 保证异步，避免同步调用栈问题）
  timeoutId = setTimeout(() => emitNext(0), 0);

  // 消除未使用变量警告
  void (req as AskDataRequest).q;

  return () => {
    aborted = true;
    clearTimeout(timeoutId);
  };
}
