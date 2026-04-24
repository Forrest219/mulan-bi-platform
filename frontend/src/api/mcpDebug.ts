import { API_BASE } from '../config';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface McpTool {
  name: string;
  description: string;
  inputSchema: {
    type: string;
    properties?: Record<string, {
      type: string;
      description?: string;
      enum?: string[];
    }>;
    required?: string[];
  };
}

export interface McpDebugCallResponse {
  tool_name: string;
  result: Record<string, unknown>;
  status: 'success' | 'error';
  duration_ms: number;
  log_id: number;
}

export interface McpDebugLog {
  id: number;
  user_id: number;
  username: string;
  tool_name: string;
  arguments_json: Record<string, unknown> | null;
  status: 'success' | 'error';
  result_summary: string | null;
  error_message: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface McpDebugLogsResponse {
  logs: McpDebugLog[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ── API Functions ─────────────────────────────────────────────────────────────

/** 调用 MCP 工具 */
export async function callMcpTool(
  toolName: string,
  args: Record<string, unknown>,
  serverId?: number,
): Promise<McpDebugCallResponse> {
  const res = await fetch(`${API_BASE}/api/mcp-debug/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ tool_name: toolName, arguments: args, server_id: serverId ?? null }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '调用失败' }));
    throw new Error(err.detail || '调用 MCP 工具失败');
  }
  return res.json();
}

/** 获取 MCP 工具列表（通过内置 /tableau-mcp 端点的 tools/list 方法） */
export async function getMcpTools(serverId?: number): Promise<McpTool[]> {
  const qs = serverId != null ? `?server_id=${serverId}` : '';
  const res = await fetch(`${API_BASE}/tableau-mcp${qs}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/list',
      params: {},
    }),
  });
  if (!res.ok) throw new Error('获取工具列表失败');
  const data = await res.json();
  return data?.result?.tools ?? [];
}

/** 获取 MCP 调试日志 */
export async function getMcpDebugLogs(params?: {
  tool_name?: string;
  status?: 'success' | 'error';
  page?: number;
  page_size?: number;
}): Promise<McpDebugLogsResponse> {
  const sp = new URLSearchParams();
  if (params?.tool_name) sp.set('tool_name', params.tool_name);
  if (params?.status) sp.set('status', params.status);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));

  const res = await fetch(`${API_BASE}/api/mcp-debug/logs?${sp}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('获取调试日志失败');
  return res.json();
}
