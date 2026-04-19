import { useState, useEffect, useRef, useCallback } from 'react';
import { getMcpDebugLogs, type McpDebugLog, type McpDebugLogsResponse } from '../../../../api/mcpDebug';

export default function AuditLogPage() {
  const [data, setData] = useState<McpDebugLogsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toolNameFilter, setToolNameFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<'success' | 'error' | ''>('');
  const [page, setPage] = useState(1);
  const [exportLoading, setExportLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const PAGE_SIZE = 20;

  const fetchLogs = useCallback(async (toolName: string, status: 'success' | 'error' | '', p: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getMcpDebugLogs({
        tool_name: toolName || undefined,
        status: status || undefined,
        page: p,
        page_size: PAGE_SIZE,
      });
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLogs(toolNameFilter, statusFilter, page);
  }, [statusFilter, page, fetchLogs]);

  const handleToolNameChange = (value: string) => {
    setToolNameFilter(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setPage(1);
      fetchLogs(value, statusFilter, 1);
    }, 300);
  };

  const handleStatusChange = (value: 'success' | 'error' | '') => {
    setStatusFilter(value);
    setPage(1);
  };

  const triggerDownload = (content: string, filename: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getDateStr = () => new Date().toISOString().slice(0, 10);

  const exportCsv = async () => {
    setExportLoading(true);
    try {
      const result = await getMcpDebugLogs({
        tool_name: toolNameFilter || undefined,
        status: statusFilter || undefined,
        page: 1,
        page_size: 1000,
      });
      const logs: McpDebugLog[] = result.logs;
      const header = 'id,tool_name,username,status,duration_ms,created_at,error_message';
      const rows = logs.map(l =>
        [
          l.id,
          `"${l.tool_name}"`,
          `"${l.username}"`,
          l.status,
          l.duration_ms ?? '',
          `"${l.created_at}"`,
          `"${(l.error_message ?? '').replace(/"/g, '""')}"`,
        ].join(','),
      );
      const csv = [header, ...rows].join('\n');
      triggerDownload(csv, `mcp-audit-${getDateStr()}.csv`, 'text/csv;charset=utf-8;');
    } finally {
      setExportLoading(false);
    }
  };

  const exportJson = async () => {
    setExportLoading(true);
    try {
      const result = await getMcpDebugLogs({
        tool_name: toolNameFilter || undefined,
        status: statusFilter || undefined,
        page: 1,
        page_size: 1000,
      });
      const json = JSON.stringify(result.logs, null, 2);
      triggerDownload(json, `mcp-audit-${getDateStr()}.json`, 'application/json');
    } finally {
      setExportLoading(false);
    }
  };

  const formatDuration = (ms: number | null) => {
    if (ms == null) return '-';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', { hour12: false });
  };

  const totalPages = data?.pages ?? 1;

  return (
    <div className="flex flex-col gap-4">
      {/* 过滤栏 + 导出按钮 */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder="搜索工具名..."
            value={toolNameFilter}
            onChange={e => handleToolNameChange(e.target.value)}
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500 w-48"
          />
          <select
            value={statusFilter}
            onChange={e => handleStatusChange(e.target.value as 'success' | 'error' | '')}
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500"
          >
            <option value="">全部</option>
            <option value="success">成功</option>
            <option value="error">失败</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={exportCsv}
            disabled={exportLoading}
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 flex items-center gap-1.5 disabled:opacity-50"
          >
            <i className="ri-download-line" /> 导出 CSV
          </button>
          <button
            onClick={exportJson}
            disabled={exportLoading}
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 flex items-center gap-1.5 disabled:opacity-50"
          >
            <i className="ri-download-line" /> 导出 JSON
          </button>
        </div>
      </div>

      {/* 错误 */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm flex items-center gap-2">
          <i className="ri-error-warning-line" /> {error}
        </div>
      )}

      {/* 表格 */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">时间</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">工具名</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">操作者</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">状态</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">耗时</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">错误摘要</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <>
                  {[0, 1, 2].map(i => (
                    <tr key={i}>
                      {[0, 1, 2, 3, 4, 5].map(j => (
                        <td key={j} className="px-4 py-3">
                          <div className="h-4 bg-slate-200 rounded animate-pulse" />
                        </td>
                      ))}
                    </tr>
                  ))}
                </>
              ) : data && data.logs.length > 0 ? (
                data.logs.map(log => (
                  <tr key={log.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{formatTime(log.created_at)}</td>
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-slate-700">{log.tool_name}</span>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600">{log.username}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        log.status === 'success'
                          ? 'bg-emerald-50 text-emerald-600'
                          : 'bg-red-50 text-red-600'
                      }`}>
                        {log.status === 'success' ? '成功' : '失败'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">{formatDuration(log.duration_ms)}</td>
                    <td className="px-4 py-3 text-xs text-slate-400 max-w-xs truncate">
                      {log.error_message || '-'}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-slate-400">暂无日志</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 分页 */}
      {data && totalPages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50"
          >
            上一页
          </button>
          <span className="text-sm text-slate-500">第 {page} / {totalPages} 页</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}
