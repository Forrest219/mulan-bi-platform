import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { listSyncLogs, type TableauSyncLog } from '../../../api/tableau';

const statusConfig: Record<string, { label: string; color: string; bg: string }> = {
  running: { label: '进行中', color: 'text-blue-700', bg: 'bg-blue-100' },
  success: { label: '成功', color: 'text-green-700', bg: 'bg-green-100' },
  partial: { label: '部分失败', color: 'text-yellow-700', bg: 'bg-yellow-100' },
  failed: { label: '失败', color: 'text-red-700', bg: 'bg-red-100' },
};

export default function SyncLogsPage() {
  const { connId } = useParams<{ connId: string }>();
  const navigate = useNavigate();
  const [logs, setLogs] = useState<TableauSyncLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const pageSize = 15;

  useEffect(() => {
    if (!connId) return;
    setLoading(true);
    listSyncLogs(Number(connId), { page, page_size: pageSize })
      .then((data) => {
        setLogs(data.logs);
        setTotal(data.total);
        setPages(data.pages);
      })
      .catch(() => setLogs([]))
      .finally(() => setLoading(false));
  }, [connId, page]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <button
            onClick={() => navigate('/tableau/connections')}
            className="text-gray-500 hover:text-gray-700 text-sm flex items-center gap-1"
          >
            <i className="ri-arrow-left-line" /> 返回连接管理
          </button>
          <h1 className="text-2xl font-bold text-gray-800">同步日志</h1>
          <span className="text-sm text-gray-500">连接 #{connId} | 共 {total} 条记录</span>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left text-gray-600 font-medium">时间</th>
                <th className="px-4 py-3 text-left text-gray-600 font-medium">触发方式</th>
                <th className="px-4 py-3 text-left text-gray-600 font-medium">状态</th>
                <th className="px-4 py-3 text-right text-gray-600 font-medium">工作簿</th>
                <th className="px-4 py-3 text-right text-gray-600 font-medium">仪表盘</th>
                <th className="px-4 py-3 text-right text-gray-600 font-medium">视图</th>
                <th className="px-4 py-3 text-right text-gray-600 font-medium">数据源</th>
                <th className="px-4 py-3 text-right text-gray-600 font-medium">删除</th>
                <th className="px-4 py-3 text-right text-gray-600 font-medium">耗时</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-gray-400">
                    加载中...
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-gray-400">
                    暂无同步记录
                  </td>
                </tr>
              ) : (
                logs.map((log) => {
                  const st = statusConfig[log.status] || statusConfig.failed;
                  const isExpanded = expandedId === log.id;
                  return (
                    <tr key={log.id} className="group">
                      <td colSpan={9} className="p-0">
                        <div
                          className="grid grid-cols-[1fr_80px_90px_60px_60px_60px_60px_60px_70px] px-4 py-3 border-b border-gray-100 hover:bg-gray-50 cursor-pointer items-center"
                          onClick={() => setExpandedId(isExpanded ? null : log.id)}
                        >
                          <span className="text-gray-700">{log.started_at}</span>
                          <span className="text-gray-500">
                            {log.trigger_type === 'manual' ? '手动' : '定时'}
                          </span>
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${st.bg} ${st.color}`}>
                            {st.label}
                          </span>
                          <span className="text-right text-gray-700">{log.workbooks_synced}</span>
                          <span className="text-right text-gray-700">{log.dashboards_synced}</span>
                          <span className="text-right text-gray-700">{log.views_synced}</span>
                          <span className="text-right text-gray-700">{log.datasources_synced}</span>
                          <span className="text-right text-gray-500">{log.assets_deleted}</span>
                          <span className="text-right text-gray-500">
                            {log.duration_sec != null ? `${log.duration_sec}s` : '-'}
                          </span>
                        </div>
                        {/* Expanded error detail */}
                        {isExpanded && log.error_message && (
                          <div className="px-4 py-3 bg-red-50 border-b border-red-100">
                            <p className="text-xs text-red-600 font-medium mb-1">错误详情</p>
                            <pre className="text-xs text-red-700 whitespace-pre-wrap">{log.error_message}</pre>
                          </div>
                        )}
                        {isExpanded && !log.error_message && (
                          <div className="px-4 py-3 bg-green-50 border-b border-green-100">
                            <p className="text-xs text-green-600">同步正常完成，无错误</p>
                          </div>
                        )}
                      </td>
                    </tr>
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
              className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-40"
            >
              上一页
            </button>
            <span className="text-sm text-gray-500">
              {page} / {pages}
            </span>
            <button
              onClick={() => setPage(Math.min(pages, page + 1))}
              disabled={page === pages}
              className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
