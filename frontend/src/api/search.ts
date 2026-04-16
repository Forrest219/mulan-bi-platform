/**
 * AskBar / Search Query API client
 * POST /api/search/query
 */
export type SearchAnswerType = 'number' | 'table' | 'text' | 'error' | 'ambiguous';

export interface NumberData {
  value: number;
  unit?: string;
  formatted?: string;
}

export interface TableData {
  columns: string[];
  rows: Array<Record<string, unknown>>;
}

export interface SearchAnswer {
  answer: string;
  type: SearchAnswerType;
  data?: NumberData | TableData | { text?: string; candidates?: Array<{ id: number; name: string }> };
  datasource?: { id: number; name: string };
  datasource_luid?: string;
  query?: unknown;
  confidence?: number;
  reason?: string;
  detail?: string;
  trace_id?: string;
}

export interface AskQuestionRequest {
  question: string;
  datasource_luid?: string;
  connection_id?: number;
  conversation_id?: string;
  use_conversation_context?: boolean;
}

export class SearchError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = 'SearchError';
    this.code = code;
  }
}

export async function askQuestion(req: AskQuestionRequest): Promise<SearchAnswer> {
  const resp = await fetch(`/api/search/query`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    const code = err?.detail?.code || err?.code || 'UNKNOWN';
    const msg = err?.detail?.message || err?.message || `HTTP ${resp.status}`;
    throw new SearchError(code, msg);
  }
  const json = await resp.json();
  // Normalize backend response: map response_type → type
  const { response_type, ...rest } = json;
  return { type: response_type, ...rest };
}
