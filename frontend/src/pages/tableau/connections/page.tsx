import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  listConnections, testConnection, syncConnection,
  checkWorkerHealth, TableauConnection
} from '../../../api/tableau';

export default function TableauConnectionsPage() {
  const navigate = useNavigate();
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [modalNotify, setModalNotify] = useState<{ success: boolean; message: string } | null>(null);

  const fetchConnections = async () => {
    try {
      const data = await listConnections(showInactive);
      setConnections(data.connections);
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : '加载失败，请检查是否已登录');
    } finally {
      setLoading(false);
    }
  };

  /* eslint-disable react-hooks/exhaustive-deps -- fetchConnections 故意只在 showInactive 变化时重新加载 */
  useEffect(() => { fetchConnections(); }, [showInactive]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const handleTest = async (id: number) => {
    setTestingId(id);
    try {
      const result = await testConnection(id);
      setModalNotify({ success: result.success, message: result.message || '连接测试成功' });
      fetchConnections();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: e instanceof Error ? e.message : '测试失败' });
    } finally {
      setTestingId(null);
    }
  };

  const handleSync = async (id: number) => {
    setSyncingId(id);
    try {
      const healthResp = await checkWorkerHealth();
      if (!healthResp.available) {
        setModalNotify({ success: false, message: '后台任务队列不可用，请检查 Worker 是否已启动' });
        setSyncingId(null);
        return;
      }
    } catch {
      setModalNotify({ success: false, message: '无法检查 Worker 健康状态' });
      setSyncingId(null);
      return;
    }

    try {
      const result = await syncConnection(id);
      if (result.status === 'running' || result.status === 'pending') {
        setModalNotify({ success: true, message: result.message || '同步任务已提交' });
        pollSyncStatus(id);
      } else {
        setModalNotify({ success: true, message: result.message || '同步已完成' });
        fetchConnections();
        setSyncingId(null);
      }
    } catch (e: unknown) {
      setModalNotify({ success: false, message: e instanceof Error ? e.message : '同步失败' });
      setSyncingId(null);
    }
  };

  const pollSyncStatus = async (connId: number) => {
    let attempts = 0;
    const maxAttempts = 30;
    const poll = async () => {
      attempts++;
      try {
        const { getSyncStatus, listSyncLogs } = await import('../../../api/tableau');
        const statusResp = await getSyncStatus(connId);
        if (statusResp.status === 'idle') {
          try {
            const logsResp = await listSyncLogs(connId, { page: 1, page_size: 1 });
            if (logsResp.logs && logsResp.logs.length > 0) {
              const log = logsResp.logs[0];
              const parts = [];
              if (log.workbooks_synced) parts.push(`工作簿 ${log.workbooks_synced}`);
              if (log.views_synced) parts.push(`视图 ${log.views_synced}`);
              if (log.datasources_synced) parts.push(`数据源 ${log.datasources_synced}`);
              if (log.dashboards_synced) parts.push(`仪表盘 ${log.dashboards_synced}`);
              const duration = log.duration_sec ? `，耗时 ${log.duration_sec}s` : '';
              setModalNotify({
                success: log.status === 'success' || log.status === 'partial',
                message: `同步完成：${parts.join('、') || '无新增'}${duration}`
              });
            }
          } catch {
            // ignore
          }
          fetchConnections();
          setSyncingId(null);
          return;
        }
        if (statusResp.status === 'failed') {
          setModalNotify({ success: false, message: '同步失败，请查看同步日志' });
          fetchConnections();
          setSyncingId(null);
          return;
        }
        if (attempts < maxAttempts) {
          setTimeout(poll, 2000);
        } else {
          setModalNotify({ success: true, message: '同步仍在进行中，请稍后查看同步日志' });
          setSyncingId(null);
        }
      } catch {
        if (attempts < maxAttempts) {
          setTimeout(poll, 2000);
        } else {
          setSyncingId(null);
        }
      }
    };
    setTimeout(poll, 2000);
  };

  const formatDate = (d: string | null | undefined) => d ? new Date(d).toLocaleString('zh-CN') : '—';

  const getStatusBadge = (conn: TableauConnection) => {
    if (!conn.is_active) return { text: '已禁用', className: 'bg-slate-100 text-slate-500 border border-slate-200' };
    if (conn.last_test_success === false) return { text: '连接失败', className: 'bg-red-50 text-red-600 border border-red-200' };
    return { text: '启用', className: 'bg-emerald-50 text-emerald-600 border border-emerald-200' };
  };

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;
  if (loadError) return <div className="p-8 text-center text-red-500">{loadError}</div>;

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-7xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span className="font-semibold text-slate-700">Tableau 连接</span>
          <span>共 {connections.length} 个</span>
        </div>
      </div>

      {/* MCP 自动管理提示 */}
      <div className="mb-4 flex items-center gap-2 px-4 py-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-700">
        <i className="ri-information-line text-base" />
        <span>
          连接由 MCP 配置自动管理，如需新建、编辑或删除连接，请前往{' '}
          <Link to="/system/mcp-configs" className="font-medium underline hover:text-blue-900">
            MCP 配置
          </Link>
          {' '}页面操作。
        </span>
      </div>

      {/* 过滤选项 */}
      <div className="flex items-center gap-4 mb-4">
        <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-600">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={e => setShowInactive(e.target.checked)}
            className="w-4 h-4 rounded border-slate-300 text-blue-600"
          />
          显示已禁用的连接
        </label>
      </div>

      {/* Connection Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {connections.map(conn => {
          const status = getStatusBadge(conn);
          return (
            <div key={conn.id} className="bg-white border border-slate-200 rounded-xl p-5 flex flex-col">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-semibold text-slate-800">{conn.name}</h3>
                  <p className="text-xs text-slate-400 mt-0.5">{conn.server_url}</p>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    conn.connection_type === 'tsc'
                      ? 'bg-amber-50 text-amber-600 border border-amber-200'
                      : 'bg-blue-50 text-blue-600 border border-blue-200'
                  }`}>
                    {conn.connection_type === 'tsc' ? 'TSC 直连' : 'MCP/REST'}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${status.className}`}>
                    {status.text}
                  </span>
                </div>
              </div>
              <div className="space-y-1.5 text-xs text-slate-500 mb-4">
                <div><span className="text-slate-400">站点：</span> {conn.site}</div>
                <div><span className="text-slate-400">API 版本：</span> {conn.api_version}</div>
                <div><span className="text-slate-400">上次同步：</span> {formatDate(conn.last_sync_at)}</div>
                {conn.last_sync_duration_sec != null && (
                  <div><span className="text-slate-400">同步耗时：</span> {conn.last_sync_duration_sec}s</div>
                )}
                {conn.sync_status && conn.sync_status !== 'idle' && (
                  <div>
                    <span className="text-slate-400">同步状态：</span>{' '}
                    <span className={conn.sync_status === 'running' ? 'text-blue-600' : 'text-red-600'}>
                      {conn.sync_status === 'running' ? '同步中...' : '同步失败'}
                    </span>
                  </div>
                )}
                {conn.auto_sync_enabled ? (
                  <div><span className="text-slate-400">自动同步：</span> 每日 00:00 / 12:00</div>
                ) : (
                  <div><span className="text-slate-400">自动同步：</span> 未启用</div>
                )}
                {conn.auto_sync_enabled ? (
                  <div><span className="text-slate-400">下次同步：</span> {(() => {
                    const now = new Date();
                    const d = now.getDate(), m = now.getMonth(), y = now.getFullYear();
                    const t00 = new Date(y, m, d, 0, 0, 0);
                    const t12 = new Date(y, m, d, 12, 0, 0);
                    const t00next = new Date(t00.getTime() + 86400_000);
                    const next = now < t00 ? t00 : now < t12 ? t12 : t00next;
                    return next.toLocaleString('zh-CN');
                  })()}</div>
                ) : (
                  <div><span className="text-slate-400">下次同步：</span> —</div>
                )}
                {conn.last_test_at && (
                  <div><span className="text-slate-400">连接测试：</span> {formatDate(conn.last_test_at)}</div>
                )}
              </div>
              <div className="mt-auto pt-4 flex items-center gap-2">
                <button onClick={() => handleTest(conn.id)}
                  disabled={testingId === conn.id}
                  className="flex-1 px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-lg flex items-center justify-center gap-1">
                  {testingId === conn.id ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-plug-line" />}
                  测试
                </button>
                <button onClick={() => handleSync(conn.id)}
                  disabled={syncingId === conn.id}
                  className="flex-1 px-3 py-1.5 text-xs bg-blue-50 hover:bg-blue-100 text-blue-600 rounded-lg flex items-center justify-center gap-1">
                  {syncingId === conn.id ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-refresh-line" />}
                  同步
                </button>
                <button onClick={() => navigate(`/assets/tableau-connections/${conn.id}/sync-logs`)}
                  className="flex-1 px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-lg flex items-center justify-center gap-1">
                  <i className="ri-file-list-3-line" /> 日志
                </button>
              </div>
            </div>
          );
        })}
        {connections.length === 0 && (
          <div className="col-span-full text-center py-12 text-slate-400">
            <i className="ri-links-line text-3xl mb-2 block" />
            暂无连接，请前往{' '}
            <Link to="/system/mcp-configs" className="text-blue-500 hover:text-blue-700 underline">
              MCP 配置
            </Link>
            {' '}页面添加 Tableau 连接
          </div>
        )}
      </div>
      </div>

      {/* 中央 Modal 通知 */}
      {modalNotify && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setModalNotify(null)}>
          <div
            className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center ${modalNotify.success ? 'bg-emerald-100' : 'bg-red-100'}`}>
                <i className={`${modalNotify.success ? 'ri-check-line text-emerald-600' : 'ri-error-warning-line text-red-600'} text-xl`} />
              </div>
              <div className="flex-1">
                <h3 className={`font-semibold ${modalNotify.success ? 'text-emerald-700' : 'text-red-700'}`}>
                  {modalNotify.success ? '操作成功' : '操作失败'}
                </h3>
                <p className="text-sm text-slate-600 mt-1">{modalNotify.message}</p>
              </div>
            </div>
            <button
              onClick={() => setModalNotify(null)}
              className="mt-4 w-full py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium rounded-lg"
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
