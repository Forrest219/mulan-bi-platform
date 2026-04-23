/**
 * QueryAlertsPage — /system/query-alerts
 *
 * Spec 14 T-10：告警事件管理员查看页
 *
 * 功能：
 * - 分页查询 query_error_events 告警列表
 * - 筛选：未解决/全部 切换、错误码下拉筛选
 * - 每行「标记已解决」按钮，成功后列表刷新
 * - 空态：无告警时展示"暂无告警"提示
 *
 * 后端 API：
 *   GET  /api/admin/query/errors              → QueryErrorListResponse
 *   POST /api/admin/query/errors/{id}/resolve → { ok, resolved_at }
 */
import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../../../config';

// ─── Types ────────────────────────────────────────────────────────────────────

interface QueryErrorEvent {
  id: number;
  username: string;
  error_type: string;
  connection_id: number | null;
  raw_error: string | null;
  resolved: boolean;
  created_at: string;
  resolved_at: string | null;
}

interface QueryErrorListResponse {
  items: QueryErrorEvent[];
  total: number;
  page: number;
  page_size: number;
}

// 错误码选项（与后端 _VALID_ERROR_CODES 对应）
const ERROR_CODE_OPTIONS = [
  { value: '', label: '全部错误码' },
  { value: 'Q_JWT_001', label: 'Q_JWT_001 — 身份未绑定' },
  { value: 'Q_PERM_002', label: 'Q_PERM_002 — 权限不足' },
  { value: 'Q_TIMEOUT_003', label: 'Q_TIMEOUT_003 — MCP 超时' },
  { value: 'Q_MCP_004', label: 'Q_MCP_004 — MCP 失败' },
  { value: 'Q_LLM_005', label: 'Q_LLM_005 — LLM 失败' },
];

// error_type → 中文标签映射
const ERROR_TYPE_LABEL: Record<string, string> = {
  identity_not_found: '身份未绑定',
  perm_denied: '权限不足',
  mcp_timeout: 'MCP 超时',
  mcp_error: 'MCP 失败',
  llm_error: 'LLM 失败',
};

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr.endsWith('Z') ? dateStr : dateStr + 'Z');
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

function truncate(text: string | null, maxLen = 80): string {
  if (!text) return '-';
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
}

// ─── Page Component ───────────────────────────────────────────────────────────

export default function QueryAlertsPage() {
  const [items, setItems] = useState<QueryErrorEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [resolveLoadingId, setResolveLoadingId] = useState<number | null>(null);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState<'success' | 'error'>('success');

  // 筛选状态
  const [showOnlyUnresolved, setShowOnlyUnresolved] = useState(true);
  const [errorCode, setErrorCode] = useState('');

  // 分页状态
  const [page, setPage] = useState(1);
  const pageSize = 20;

  // ── 数据获取 ────────────────────────────────────────────────────────────────

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        resolved: String(!showOnlyUnresolved),
        page: String(page),
        page_size: String(pageSize),
      });
      if (errorCode) params.set('error_code', errorCode);

      const resp = await fetch(`${API_BASE}/api/admin/query/errors?${params}`, {
        credentials: 'include',
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showMessage(err.detail || '获取告警列表失败', 'error');
        return;
      }
      const data: QueryErrorListResponse = await resp.json();
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      showMessage('网络错误，请稍后重试', 'error');
    } finally {
      setLoading(false);
    }
  }, [showOnlyUnresolved, errorCode, page]);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  // 筛选条件变化时重置到第一页
  useEffect(() => {
    setPage(1);
  }, [showOnlyUnresolved, errorCode]);

  // ── 标记已解决 ──────────────────────────────────────────────────────────────

  const handleResolve = async (eventId: number) => {
    setResolveLoadingId(eventId);
    try {
      const resp = await fetch(`${API_BASE}/api/admin/query/errors/${eventId}/resolve`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showMessage(err.detail || '标记失败', 'error');
        return;
      }
      showMessage('已标记为已解决', 'success');
      fetchAlerts();
    } catch {
      showMessage('网络错误，请稍后重试', 'error');
    } finally {
      setResolveLoadingId(null);
    }
  };

  // ── 消息提示 ────────────────────────────────────────────────────────────────

  const showMessage = (text: string, type: 'success' | 'error') => {
    setMessage(text);
    setMessageType(type);
    setTimeout(() => setMessage(''), 4000);
  };

  // ── 分页 ────────────────────────────────────────────────────────────────────

  const totalPages = Math.ceil(total / pageSize);

  // ── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <div className="p-6">
      {/* 消息提示 */}
      {message && (
        <div
          className={`mb-4 px-4 py-2 border rounded-lg text-sm ${
            messageType === 'success'
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-red-50 text-red-700 border-red-200'
          }`}
        >
          {message}
        </div>
      )}

      {/* 页面标题栏 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">问数告警</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            查看问数过程中发生的身份绑定与权限告警，共 {total} 条
          </p>
        </div>
        <button
          onClick={() => fetchAlerts()}
          className="px-3 py-2 text-sm text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg flex items-center gap-1.5 transition-colors"
        >
          <i className="ri-refresh-line" />
          刷新
        </button>
      </div>

      {/* 筛选条件 */}
      <div className="bg-white rounded-xl border border-slate-200 p-4 mb-4">
        <div className="flex items-center gap-4 flex-wrap">
          {/* 未解决/全部 切换 */}
          <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
            <button
              onClick={() => setShowOnlyUnresolved(true)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                showOnlyUnresolved
                  ? 'bg-white text-slate-700 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              未解决
            </button>
            <button
              onClick={() => setShowOnlyUnresolved(false)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                !showOnlyUnresolved
                  ? 'bg-white text-slate-700 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              全部
            </button>
          </div>

          {/* 错误码下拉筛选 */}
          <select
            value={errorCode}
            onChange={(e) => setErrorCode(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-blue-500"
          >
            {ERROR_CODE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 告警列表表格 */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">
                时间
              </th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">
                用户名
              </th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">
                错误类型
              </th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">
                错误信息
              </th>
              <th className="text-left text-xs font-semibold text-slate-500 uppercase px-4 py-3">
                状态
              </th>
              <th className="text-right text-xs font-semibold text-slate-500 uppercase px-4 py-3">
                操作
              </th>
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
                  <i className="ri-alarm-warning-line text-3xl mb-2 block" />
                  暂无告警
                </td>
              </tr>
            ) : (
              items.map((event) => (
                <tr key={event.id} className="hover:bg-slate-50/50">
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                    {formatDateTime(event.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm font-medium text-slate-800">
                      {event.username}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-1 bg-amber-50 text-amber-700 border border-amber-200 rounded-full">
                      {ERROR_TYPE_LABEL[event.error_type] ?? event.error_type}
                    </span>
                  </td>
                  <td className="px-4 py-3 max-w-xs">
                    <span
                      className="text-xs text-slate-500 block truncate"
                      title={event.raw_error ?? undefined}
                    >
                      {truncate(event.raw_error)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {event.resolved ? (
                      <span className="text-xs font-medium px-2 py-1 rounded-full bg-emerald-50 text-emerald-700">
                        已解决
                      </span>
                    ) : (
                      <span className="text-xs font-medium px-2 py-1 rounded-full bg-red-50 text-red-600">
                        未解决
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!event.resolved && (
                      <button
                        onClick={() => handleResolve(event.id)}
                        disabled={resolveLoadingId === event.id}
                        className="text-xs text-blue-600 hover:text-blue-800 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {resolveLoadingId === event.id ? '处理中...' : '标记已解决'}
                      </button>
                    )}
                    {event.resolved && event.resolved_at && (
                      <span className="text-xs text-slate-400">
                        {formatDateTime(event.resolved_at)}
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
