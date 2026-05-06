/**
 * QueryLogsPage — /system/query-alerts
 *
 * 查数日志：展示所有用户通过首页 Data Agent 发起的问数记录，
 * 支持按状态（成功/失败）、意图、时间范围筛选。
 *
 * 后端 API：GET /api/admin/query/logs
 */
import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../../../config';

// ─── Types ────────────────────────────────────────────────────────────────────

interface NlqLogItem {
  id: number;
  username: string | null;
  question: string;
  intent: string | null;
  response_type: string | null;
  datasource_luid: string | null;
  execution_time_ms: number | null;
  error_code: string | null;
  success: boolean;
  created_at: string;
}

interface NlqLogListResponse {
  items: NlqLogItem[];
  total: number;
  page: number;
  page_size: number;
}

// 意图选项（与后端 nlq_query_logs.intent 字段值对应）
const INTENT_OPTIONS = [
  { value: '', label: '全部意图' },
  { value: 'vizql', label: 'VizQL 查询' },
  { value: 'text', label: '文本回答' },
  { value: 'clarification', label: '澄清追问' },
];

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr.includes('Z') ? dateStr : dateStr);
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function truncate(text: string, maxLen = 80): string {
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
}

function toDatetimeLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function defaultRange(): { start: string; end: string } {
  const now = new Date();
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  return { start: toDatetimeLocal(yesterday), end: toDatetimeLocal(now) };
}

// ─── Page Component ───────────────────────────────────────────────────────────

export default function QueryLogsPage() {
  const [items, setItems] = useState<NlqLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');

  // 筛选状态
  const [status, setStatus] = useState<'all' | 'success' | 'failed'>('all');
  const [intent, setIntent] = useState('');
  const { start: defaultStart, end: defaultEnd } = defaultRange();
  const [startTime, setStartTime] = useState(defaultStart);
  const [endTime, setEndTime] = useState(defaultEnd);

  // 分页
  const [page, setPage] = useState(1);
  const pageSize = 20;

  // ── 数据获取 ────────────────────────────────────────────────────────────────

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setErrorMsg('');
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (status !== 'all') params.set('status', status);
      if (intent) params.set('intent', intent);
      if (startTime) params.set('start_time', startTime);
      if (endTime) params.set('end_time', endTime);

      const resp = await fetch(`${API_BASE}/api/admin/query/logs?${params}`, {
        credentials: 'include',
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        setErrorMsg(err.detail?.message || err.detail || '获取查数日志失败');
        return;
      }
      const data: NlqLogListResponse = await resp.json();
      setItems(data.items);
      setTotal(data.total);
    } catch {
      setErrorMsg('网络错误，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [status, intent, startTime, endTime, page]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    setPage(1);
  }, [status, intent, startTime, endTime]);

  const totalPages = Math.ceil(total / pageSize);

  // ── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <div className="p-6">
      {/* 错误提示 */}
      {errorMsg && (
        <div className="mb-4 px-4 py-2 border rounded-lg text-sm bg-red-50 text-red-700 border-red-200">
          {errorMsg}
        </div>
      )}

      {/* 页面标题栏 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">查数日志</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            所有用户的问数记录，共 {total} 条
          </p>
        </div>
        <button
          onClick={() => fetchLogs()}
          className="px-3 py-2 text-sm text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg flex items-center gap-1.5 transition-colors"
        >
          <i className="ri-refresh-line" />
          刷新
        </button>
      </div>

      {/* 筛选栏 */}
      <div className="bg-white rounded-xl border border-slate-200 p-4 mb-4">
        <div className="flex items-center gap-4 flex-wrap">
          {/* 状态切换 */}
          <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
            {(['all', 'success', 'failed'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatus(s)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  status === s
                    ? 'bg-white text-slate-700 shadow-sm'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {s === 'all' ? '全部' : s === 'success' ? '成功' : '失败'}
              </button>
            ))}
          </div>

          {/* 意图下拉 */}
          <select
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-blue-500"
          >
            {INTENT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>

          {/* 时间范围 */}
          <div className="flex items-center gap-2">
            <input
              type="datetime-local"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-blue-500"
            />
            <span className="text-slate-400 text-xs">至</span>
            <input
              type="datetime-local"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* 重置时间 */}
          <button
            onClick={() => { const r = defaultRange(); setStartTime(r.start); setEndTime(r.end); }}
            className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
          >
            过去24小时
          </button>
        </div>
      </div>

      {/* 日志表格 */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3 whitespace-nowrap">时间</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3 whitespace-nowrap">用户</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">问题</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3 whitespace-nowrap">意图</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3 whitespace-nowrap">耗时</th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3 whitespace-nowrap">状态</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-slate-400">
                  <i className="ri-loader-4-line text-2xl animate-spin mb-2 block" />
                  加载中...
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-slate-400">
                  <i className="ri-file-list-3-line text-3xl mb-2 block" />
                  暂无记录
                </td>
              </tr>
            ) : (
              items.map((log) => (
                <tr key={log.id} className="hover:bg-slate-50/50">
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                    {formatDateTime(log.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm font-medium text-slate-700">
                      {log.username ?? '-'}
                    </span>
                  </td>
                  <td className="px-4 py-3 max-w-sm">
                    <span
                      className="text-sm text-slate-800 block truncate"
                      title={log.question}
                    >
                      {truncate(log.question)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {log.intent ? (
                      <span className="text-xs px-2 py-1 bg-blue-50 text-blue-700 border border-blue-200 rounded-full">
                        {log.intent}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                    {formatDuration(log.execution_time_ms)}
                  </td>
                  <td className="px-4 py-3">
                    {log.success ? (
                      <span className="text-xs font-medium px-2 py-1 rounded-full bg-emerald-50 text-emerald-700">
                        成功
                      </span>
                    ) : (
                      <span
                        className="text-xs font-medium px-2 py-1 rounded-full bg-red-50 text-red-600"
                        title={log.error_code ?? undefined}
                      >
                        失败{log.error_code ? `·${log.error_code}` : ''}
                      </span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between">
            <span className="text-xs text-slate-400">
              共 {total} 条，第 {page} / {totalPages} 页
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg disabled:opacity-40 hover:bg-slate-50 transition-colors"
              >
                上一页
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg disabled:opacity-40 hover:bg-slate-50 transition-colors"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
