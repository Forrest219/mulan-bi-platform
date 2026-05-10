import { useState, useEffect, useCallback } from 'react';
import { getAvatarGradient } from '../../../config';
import { getActivityLogs, getActivityTypes, exportActivityLogs, type ActivityLog } from '../../../api/activity';

type TimeRange = '7d' | '30d' | 'all' | 'custom';

interface User {
  id: number;
  username: string;
  display_name: string;
  tag: string;
  tag_emoji: string;
  tag_color: string;
  days_since_login: number;
}

interface Stats {
  total_users: number;
  active_users: number;
  active_rate: number;
  tag_counts: Record<string, number>;
}

interface LogsResponse {
  logs: ActivityLog[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

function formatDate(iso: string): string {
  if (!iso) return '-';
  const d = new Date(iso.replace(' ', 'T'));
  return d.toLocaleString('zh-CN', { hour12: false });
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function getTagBadgeClass(color: string): string {
  const map: Record<string, string> = {
    emerald: 'bg-emerald-100 text-emerald-700',
    blue: 'bg-blue-100 text-blue-700',
    orange: 'bg-orange-100 text-orange-700',
    gray: 'bg-slate-100 text-slate-600',
    red: 'bg-red-100 text-red-700',
  };
  return map[color] || 'bg-slate-100 text-slate-600';
}

export default function ActivityPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [operationTypes, setOperationTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  // Filter state
  const [timeRange, setTimeRange] = useState<TimeRange>('7d');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [opTypeFilter, setOpTypeFilter] = useState<string>('');
  const [lockedOperatorId, setLockedOperatorId] = useState<number | null>(null);

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);

  // Detail drawer
  const [detailLog, setDetailLog] = useState<ActivityLog | null>(null);

  const fetchUsers = useCallback(async () => {
    try {
      const resp = await fetch(`${import.meta.env.VITE_API_BASE || ''}/api/permissions/users`, { credentials: 'include' });
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      setUsers(data.users || []);
    } catch { /* ignore */ }
  }, []);

  const fetchStats = useCallback(async (userId?: number) => {
    try {
      const sp = userId ? `?user_id=${userId}` : '';
      const resp = await fetch(`${import.meta.env.VITE_API_BASE || ''}/api/activity/stats${sp}`, { credentials: 'include' });
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      setStats(data);
    } catch { /* ignore */ }
  }, []);

  const fetchTypes = useCallback(async () => {
    try {
      const types = await getActivityTypes();
      setOperationTypes(types);
    } catch { /* ignore */ }
  }, []);

  const fetchLogs = useCallback(async (p: number) => {
    setLoading(true);
    try {
      // Build time filter
      let start_time = '';
      let end_time = '';
      const now = new Date();
      if (timeRange === '7d') {
        const d = new Date(now);
        d.setDate(d.getDate() - 7);
        start_time = d.toISOString();
        end_time = now.toISOString();
      } else if (timeRange === '30d') {
        const d = new Date(now);
        d.setDate(d.getDate() - 30);
        start_time = d.toISOString();
        end_time = now.toISOString();
      } else if (timeRange === 'custom') {
        if (customStart) start_time = new Date(customStart).toISOString();
        if (customEnd) end_time = new Date(customEnd + 'T23:59:59').toISOString();
      }

      const params: Parameters<typeof getActivityLogs>[0] = {
        page: p,
        page_size: pageSize,
        operation_type: opTypeFilter || undefined,
        start_time,
        end_time,
        user_id: lockedOperatorId || undefined,
      };
      const data = await getActivityLogs(params);
      setLogs(data.logs);
      setTotal(data.total);
      setPage(data.page);
      setPages(data.pages);
    } catch { /* ignore */ }
    finally {
      setLoading(false);
    }
  }, [timeRange, customStart, customEnd, opTypeFilter, lockedOperatorId, pageSize]);

  useEffect(() => {
    fetchUsers();
    fetchStats();
    fetchTypes();
  }, []);

  useEffect(() => {
    setPage(1);
    fetchLogs(1);
  }, [timeRange, customStart, customEnd, opTypeFilter, lockedOperatorId]);

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    fetchLogs(newPage);
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      let start_time = '';
      let end_time = '';
      const now = new Date();
      if (timeRange === '7d') {
        const d = new Date(now); d.setDate(d.getDate() - 7);
        start_time = d.toISOString(); end_time = now.toISOString();
      } else if (timeRange === '30d') {
        const d = new Date(now); d.setDate(d.getDate() - 30);
        start_time = d.toISOString(); end_time = now.toISOString();
      } else if (timeRange === 'custom') {
        if (customStart) start_time = new Date(customStart).toISOString();
        if (customEnd) end_time = new Date(customEnd + 'T23:59:59').toISOString();
      }
      await exportActivityLogs({
        operation_type: opTypeFilter || undefined,
        start_time,
        end_time,
        user_id: lockedOperatorId || undefined,
      });
    } catch { /* ignore */ }
    finally {
      setExporting(false);
    }
  };

  const handleUserClick = (userId: number) => {
    setLockedOperatorId(prev => prev === userId ? null : userId);
  };

  const totalPages = Math.max(1, pages);

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-history-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">操作日志</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">
            {lockedOperatorId ? '已锁定特定用户' : '用户活动统计和登录记录'}
          </p>
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-6xl mx-auto">

          {/* Filter bar */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 mb-4 flex flex-wrap items-center gap-4">
            {/* Time range */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500">时间范围：</span>
              <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
                {([['7d', '近7天'], ['30d', '近30天'], ['all', '全部'], ['custom', '自定义']] as [TimeRange, string][]).map(([val, label]) => (
                  <button key={val} onClick={() => setTimeRange(val)}
                    className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${timeRange === val ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Custom date inputs */}
            {timeRange === 'custom' && (
              <div className="flex items-center gap-2">
                <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)}
                  className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500" />
                <span className="text-slate-400">—</span>
                <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)}
                  className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500" />
              </div>
            )}

            {/* Operation type */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500">操作类型：</span>
              <select value={opTypeFilter} onChange={e => setOpTypeFilter(e.target.value)}
                className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500">
                <option value="">全部</option>
                {operationTypes.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            {/* Export button */}
            <div className="ml-auto">
              <button onClick={handleExport} disabled={exporting}
                className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 flex items-center gap-1.5 disabled:opacity-50">
                <i className="ri-download-line" />
                {exporting ? '导出中...' : '导出报告'}
              </button>
            </div>
          </div>

          {/* Stats cards */}
          {stats && (
            <div className="grid grid-cols-4 gap-4 mb-6">
              <div className="bg-white rounded-xl border border-slate-200 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 flex items-center justify-center bg-blue-100 rounded-lg">
                    <i className="ri-user-line text-blue-600" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-slate-800">{stats.total_users}</div>
                    <div className="text-xs text-slate-500">总用户数</div>
                  </div>
                </div>
              </div>
              <div className="bg-white rounded-xl border border-slate-200 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 flex items-center justify-center bg-emerald-100 rounded-lg">
                    <i className="ri-user-star-line text-emerald-600" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-slate-800">{stats.active_users}</div>
                    <div className="text-xs text-slate-500">活跃用户</div>
                  </div>
                </div>
              </div>
              <div className="bg-white rounded-xl border border-slate-200 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 flex items-center justify-center bg-purple-100 rounded-lg">
                    <i className="ri-percent-line text-purple-600" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-slate-800">{stats.active_rate}%</div>
                    <div className="text-xs text-slate-500">活跃率</div>
                  </div>
                </div>
              </div>
              <div className="bg-white rounded-xl border border-slate-200 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 flex items-center justify-center bg-slate-100 rounded-lg">
                    <i className="ri-file-list-3-line text-slate-600" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-slate-800">{total}</div>
                    <div className="text-xs text-slate-500">操作记录</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-6">
            {/* Left sidebar: user list */}
            <div className="col-span-1 space-y-4">
              {/* User status distribution */}
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100">
                  <h3 className="text-sm font-semibold text-slate-700">用户状态分布</h3>
                </div>
                <div className="p-4 space-y-3">
                  {stats?.tag_counts && Object.entries(stats.tag_counts).map(([tag, count]) => {
                    const user = users.find(u => u.tag === tag);
                    const color = user?.tag_color || 'gray';
                    const emoji = user?.tag_emoji || '❓';
                    const pct = stats.total_users > 0 ? ((count as number) / stats.total_users * 100) : 0;
                    return (
                      <div key={tag} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-base">{emoji}</span>
                          <span className="text-sm text-slate-600">{tag}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-slate-700">{count as number}</span>
                          <div className="w-16 h-2 rounded-full bg-slate-100">
                            <div className="h-full rounded-full bg-current opacity-40" style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* User list */}
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-700">用户列表</h3>
                  {lockedOperatorId && (
                    <button onClick={() => setLockedOperatorId(null)}
                      className="text-xs text-blue-500 hover:text-blue-600">清除筛选</button>
                  )}
                </div>
                <div className="divide-y divide-slate-100 max-h-80 overflow-y-auto">
                  {users.map(user => (
                    <div key={user.id}
                      onClick={() => handleUserClick(user.id)}
                      className={`px-4 py-2.5 flex items-center justify-between cursor-pointer hover:bg-slate-50 ${lockedOperatorId === user.id ? 'bg-blue-50' : ''}`}>
                      <div className="flex items-center gap-2">
                        <div className={`w-7 h-7 rounded-full bg-gradient-to-br ${getAvatarGradient(user.username)} flex items-center justify-center text-white text-xs font-medium`}>
                          {user.display_name.charAt(0)}
                        </div>
                        <div>
                          <div className="text-sm font-medium text-slate-700">{user.display_name}</div>
                          <div className="text-xs text-slate-400">@{user.username}</div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${getTagBadgeClass(user.tag_color)}`}>
                          {user.tag_emoji} {user.tag}
                        </span>
                        {lockedOperatorId === user.id && (
                          <i className="ri-filter-fill text-blue-500 text-xs" />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Right: operation logs */}
            <div className="col-span-2">
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-700">操作日志</h3>
                  <span className="text-xs text-slate-400">共 {total} 条记录</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200">
                        <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">时间</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">操作者</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">操作类型</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">状态</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">IP / 来源</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {loading ? (
                        <tr>
                          <td colSpan={5} className="px-4 py-12 text-center text-slate-400">
                            <span className="inline-flex items-center gap-2">
                              <i className="ri-loader-2-line animate-spin" /> 加载中...
                            </span>
                          </td>
                        </tr>
                      ) : logs.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="px-4 py-12 text-center text-slate-400">
                            <i className="ri-file-list-3-line text-3xl mb-2 block" /> 暂无操作日志
                          </td>
                        </tr>
                      ) : (
                        logs.map(log => (
                          <tr key={log.id}
                            onClick={() => setDetailLog(log)}
                            className="hover:bg-slate-50 cursor-pointer">
                            <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{formatDate(log.op_time)}</td>
                            <td className="px-4 py-3 text-sm text-slate-700">{log.operator}</td>
                            <td className="px-4 py-3">
                              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                log.operation_type === 'login' ? 'bg-blue-50 text-blue-600' :
                                log.operation_type === 'logout' ? 'bg-slate-100 text-slate-600' :
                                log.status === 'fail' ? 'bg-red-50 text-red-600' :
                                'bg-emerald-50 text-emerald-600'
                              }`}>
                                {log.operation_type === 'login' ? '登录' :
                                 log.operation_type === 'logout' ? '登出' :
                                 log.operation_type}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                log.status === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                              }`}>
                                {log.status === 'success' ? '成功' : '失败'}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-xs text-slate-400">
                              {log.ip_address || '-'}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-center gap-3 px-4 py-3 border-t border-slate-100">
                    <button onClick={() => handlePageChange(page - 1)} disabled={page <= 1}
                      className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50">
                      上一页
                    </button>
                    <span className="text-sm text-slate-500">第 {page} / {totalPages} 页</span>
                    <button onClick={() => handlePageChange(page + 1)} disabled={page >= totalPages}
                      className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50">
                      下一页
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Detail Drawer */}
      {detailLog && (
        <div className="fixed inset-0 z-50 flex justify-end" onClick={() => setDetailLog(null)}>
          <div className="absolute inset-0 bg-black/30" />
          <div className="relative w-full max-w-lg bg-white shadow-xl overflow-y-auto"
            style={{ maxHeight: '100vh' }}
            onClick={e => e.stopPropagation()}>
            {/* Drawer header */}
            <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between z-10">
              <h2 className="text-base font-semibold text-slate-800">操作详情</h2>
              <button onClick={() => setDetailLog(null)}
                className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-slate-100 text-slate-500">
                <i className="ri-close-line text-lg" />
              </button>
            </div>

            {/* Drawer content */}
            <div className="p-6 space-y-5">
              {/* Status badge */}
              <div className="flex items-center gap-3">
                <span className={`text-sm px-3 py-1 rounded-full font-medium ${
                  detailLog.status === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                }`}>
                  {detailLog.status === 'success' ? '成功' : '失败'}
                </span>
                <span className={`text-sm px-3 py-1 rounded-full font-medium ${
                  detailLog.operation_type === 'login' ? 'bg-blue-50 text-blue-600' :
                  detailLog.operation_type === 'logout' ? 'bg-slate-100 text-slate-600' :
                  'bg-purple-50 text-purple-600'
                }`}>
                  {detailLog.operation_type}
                </span>
              </div>

              {/* Info rows */}
              <div className="space-y-3">
                <div className="flex items-start">
                  <span className="w-20 text-xs text-slate-500 pt-0.5">操作时间</span>
                  <span className="text-sm text-slate-700">{formatDate(detailLog.op_time)}</span>
                </div>
                <div className="flex items-start">
                  <span className="w-20 text-xs text-slate-500 pt-0.5">操作者</span>
                  <span className="text-sm text-slate-700">{detailLog.operator}</span>
                </div>
                {detailLog.target && (
                  <div className="flex items-start">
                    <span className="w-20 text-xs text-slate-500 pt-0.5">操作目标</span>
                    <span className="text-sm text-slate-700">{detailLog.target}</span>
                  </div>
                )}
                {detailLog.ip_address && (
                  <div className="flex items-start">
                    <span className="w-20 text-xs text-slate-500 pt-0.5">IP 地址</span>
                    <span className="text-sm text-slate-700 font-mono">{detailLog.ip_address}</span>
                  </div>
                )}
                {detailLog.user_agent && (
                  <div className="flex items-start">
                    <span className="w-20 text-xs text-slate-500 pt-0.5">User-Agent</span>
                    <span className="text-xs text-slate-500 break-all">{detailLog.user_agent}</span>
                  </div>
                )}
                {detailLog.trace_id && (
                  <div className="flex items-start">
                    <span className="w-20 text-xs text-slate-500 pt-0.5">Trace ID</span>
                    <span className="text-sm text-slate-700 font-mono">{detailLog.trace_id}</span>
                  </div>
                )}
              </div>

              {/* Details JSON */}
              {detailLog.details && (
                <div>
                  <h3 className="text-xs font-medium text-slate-500 mb-2">详细信息</h3>
                  <pre className="text-xs bg-slate-50 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap"
                    style={{ maxHeight: '300px', overflowY: 'auto' }}>
                    {typeof detailLog.details === 'string'
                      ? (() => { try { return JSON.stringify(JSON.parse(detailLog.details), null, 2); } catch { return detailLog.details; } })()
                      : JSON.stringify(detailLog.details, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}