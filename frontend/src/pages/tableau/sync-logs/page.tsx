import { useState, useEffect, Fragment } from 'react';
import { useParams, Link } from 'react-router-dom';
import { listSyncLogs, listConnections, type TableauSyncLog } from '../../../api/tableau';

const statusConfig: Record<string, { label: string; color: string; bg: string }> = {
  running: { label: '进行中', color: 'text-blue-700', bg: 'bg-blue-100' },
  success: { label: '成功', color: 'text-green-700', bg: 'bg-green-100' },
  partial: { label: '部分失败', color: 'text-yellow-700', bg: 'bg-yellow-100' },
  failed: { label: '失败', color: 'text-red-700', bg: 'bg-red-100' },
};

export default function SyncLogsPage() {
  const { connId } = useParams<{ connId: string }>();
  const [connName, setConnName] = useState<string | null>(null);
  const [logs, setLogs] = useState<TableauSyncLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const pageSize = 15;

  useEffect(() => {
    if (!connId) return;
    listConnections(true)
      .then(data => {
        const match = data.connections.find(c => c.id === Number(connId));
        if (match) setConnName(match.name);
      })
      .catch(() => {});
  }, [connId]);

  useEffect(() => {
    if (!connId) return;
    setLoading(true);
    listSyncLogs(Number(connId), { page, page_size: pageSize })
      .then((data) => {
        setLogs(data.logs);
        setTotal(data.total);
        setPages(data.pages);
      })
      .catch((e: unknown) => {
        setLogs([]);
        setError(e instanceof Error ? e.message : '加载失败，请重试');
      })
      .finally(() => setLoading(false));
  }, [connId, page]);

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-refresh-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">{connName ?? `连接 #${connId}`} · 同步日志</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">
            <Link to="/assets/tableau-connections" className="hover:text-blue-600">← Tableau 连接</Link>
            {"　·　"}共 {total} 条记录
          </p>
        </div>
      </div>
      <div className="max-w-6xl mx-auto px-8 py-7">

        {/* Table */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-4 py-3 text-left text-slate-600 font-medium">流水号</th>
                <th className="px-4 py-3 text-left text-slate-600 font-medium">开始时间</th>
                <th className="px-4 py-3 text-left text-slate-600 font-medium">结束时间</th>
                <th className="px-4 py-3 text-left text-slate-600 font-medium">触发方式</th>
                <th className="px-4 py-3 text-left text-slate-600 font-medium">状态</th>
                <th className="px-4 py-3 text-right text-slate-600 font-medium">工作簿</th>
                <th className="px-4 py-3 text-right text-slate-600 font-medium">仪表盘</th>
                <th className="px-4 py-3 text-right text-slate-600 font-medium">视图</th>
                <th className="px-4 py-3 text-right text-slate-600 font-medium">数据源</th>
                <th className="px-4 py-3 text-right text-slate-600 font-medium">字段(增量)</th>
                <th className="px-4 py-3 text-right text-slate-600 font-medium">删除</th>
                <th className="px-4 py-3 text-right text-slate-600 font-medium">耗时</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={12} className="px-4 py-12 text-center text-slate-400">
                    <div className="flex flex-col items-center gap-2">
                      <i className="ri-loader-2-line animate-spin text-2xl" />
                      <span>加载中...</span>
                    </div>
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td colSpan={12} className="px-4 py-12 text-center text-red-500">
                    <div className="flex flex-col items-center gap-2">
                      <i className="ri-error-warning-line text-2xl" />
                      <span>{error}</span>
                      <button
                        onClick={() => listSyncLogs(Number(connId), { page, page_size: pageSize })
                          .then((d) => { setLogs(d.logs); setTotal(d.total); setPages(d.pages); setError(null); })
                          .catch((e: unknown) => setError(e instanceof Error ? e.message : '加载失败'))}
                        className="text-sm text-blue-500 hover:underline"
                      >
                        重试
                      </button>
                    </div>
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={12} className="px-4 py-12 text-center text-slate-400">
                    <div className="flex flex-col items-center gap-2">
                      <i className="ri-file-list-3-line text-3xl opacity-50" />
                      <span>暂无同步记录</span>
                    </div>
                  </td>
                </tr>
              ) : (
                logs.map((log, idx) => {
                  const st = statusConfig[log.status] || statusConfig.failed;
                  const isExpanded = expandedId === log.id;
                  const seq = total - ((page - 1) * pageSize + idx);
                  const dateStr = log.started_at ? log.started_at.replace(/[-/]/g, '').slice(0, 8) : '00000000';
                  const seqId = `${dateStr}-${String(seq).padStart(4, '0')}`;
                  return (
                    <Fragment key={log.id}>
                      <tr
                        className="cursor-pointer hover:bg-slate-50"
                        onClick={() => setExpandedId(isExpanded ? null : log.id)}
                      >
                        <td className="px-4 py-3 text-slate-700 font-mono">{seqId}</td>
                        <td className="px-4 py-3 text-slate-700">{log.started_at}</td>
                        <td className="px-4 py-3 text-slate-700">{log.finished_at || '-'}</td>
                        <td className="px-4 py-3 text-slate-700">
                          {log.trigger_type === 'manual' ? '手动' : '定时'}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full font-medium ${st.bg} ${st.color}`}>
                            {st.label}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right text-slate-700">{log.workbooks_synced}</td>
                        <td className="px-4 py-3 text-right text-slate-700">{log.dashboards_synced}</td>
                        <td className="px-4 py-3 text-right text-slate-700">{log.views_synced}</td>
                        <td className="px-4 py-3 text-right text-slate-700">{log.datasources_synced}</td>
                        <td className="px-4 py-3 text-right">
                          {log.fields_added != null || log.fields_deleted != null ? (
                            <span className="text-slate-700">
                              {log.fields_added != null && log.fields_added > 0 && (
                                <span className="text-green-600">+{log.fields_added}</span>
                              )}
                              {log.fields_deleted != null && log.fields_deleted > 0 && (
                                <span className="text-red-600 ml-1">-{log.fields_deleted}</span>
                              )}
                              {(log.fields_added == null || log.fields_added === 0) && (log.fields_deleted == null || log.fields_deleted === 0) && '-'}
                            </span>
                          ) : '-'}
                        </td>
                        <td className="px-4 py-3 text-right text-slate-700">{log.assets_deleted}</td>
                        <td className="px-4 py-3 text-right text-slate-700">
                          {log.duration_sec != null ? `${log.duration_sec}s` : '-'}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${log.id}-detail`}>
                          <td colSpan={12} className="px-4 py-3 bg-red-50 border-b border-slate-100">
                            {log.error_message ? (
                              <div>
                                <p className="text-xs text-red-600 font-medium mb-1">错误详情</p>
                                <pre className="text-xs text-red-700 whitespace-pre-wrap">{log.error_message}</pre>
                              </div>
                            ) : (
                              <p className="text-xs text-green-600">同步正常完成，无错误</p>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-6">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50"
            >
              上一页
            </button>
            <span className="text-xs text-slate-500">第 {page} 页，共 {pages} 页</span>
            <button
              onClick={() => setPage(Math.min(pages, page + 1))}
              disabled={page === pages}
              className="px-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg disabled:opacity-50 hover:bg-slate-50"
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
