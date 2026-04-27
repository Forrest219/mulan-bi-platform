import { useState } from 'react';
import { PublishLogDetail } from '../../../../api/semantic-maintenance';
import { StatusBadge } from './StatusBadge';
import { DiffViewer } from './DiffViewer';

interface PublishLogDetailProps {
  log: PublishLogDetail | null;
  open: boolean;
  onClose: () => void;
  onRetry?: (logId: number) => void;
  onRollback?: (logId: number) => void;
  isAdmin: boolean;
  userRole: string;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString('zh-CN');
}

export function PublishLogDetailDrawer({
  log,
  open,
  onClose,
  onRetry,
  onRollback,
  isAdmin,
  userRole,
}: PublishLogDetailProps) {
  const [activeTab, setActiveTab] = useState<'diff' | 'payload'>('diff');
  const [actionLoading, setActionLoading] = useState<number | null>(null);

  if (!open || !log) return null;

  const handleAction = async (action: 'retry' | 'rollback', logId: number) => {
    setActionLoading(logId);
    try {
      if (action === 'retry' && onRetry) {
        await onRetry(logId);
      } else if (action === 'rollback' && onRollback) {
        await onRollback(logId);
      }
    } finally {
      setActionLoading(null);
    }
  };

  const isRollbackDiff = log.diff_summary?.is_rollback;
  const canRetry = log.status === 'failed' && (userRole === 'admin' || userRole === 'publisher');
  const canRollback = log.can_rollback && isAdmin;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full max-w-2xl bg-white shadow-2xl z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-semibold text-slate-800">发布日志详情</h2>
            <p className="text-sm text-slate-400 mt-0.5">日志 #{log.id}</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <i className="ri-close-line text-xl" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {/* Info Card */}
          <div className="px-6 py-4 border-b border-slate-100">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-slate-400 mb-1">连接</div>
                <div className="text-sm text-slate-700">{log.connection_name || '-'}</div>
              </div>
              <div>
                <div className="text-xs text-slate-400 mb-1">对象类型</div>
                <div className="text-sm text-slate-700">
                  {log.object_type === 'datasource' ? '数据源' : '字段'}
                </div>
              </div>
              <div>
                <div className="text-xs text-slate-400 mb-1">对象名称</div>
                <div className="text-sm text-slate-700">{log.object_name || '-'}</div>
              </div>
              <div>
                <div className="text-xs text-slate-400 mb-1">状态</div>
                <div className="mt-0.5">
                  <StatusBadge status={log.status} size="md" />
                </div>
              </div>
              <div>
                <div className="text-xs text-slate-400 mb-1">操作人</div>
                <div className="text-sm text-slate-700">
                  {log.operator?.display_name || log.operator?.username || '-'}
                </div>
              </div>
              <div>
                <div className="text-xs text-slate-400 mb-1">发布时间</div>
                <div className="text-sm text-slate-700">{formatDate(log.created_at)}</div>
              </div>
            </div>

            {log.response_summary && (
              <div className="mt-4">
                <div className="text-xs text-slate-400 mb-1">响应摘要</div>
                <div className={`text-sm px-3 py-2 rounded-lg ${
                  log.status === 'success' ? 'bg-emerald-50 text-emerald-700' :
                  log.status === 'failed' ? 'bg-red-50 text-red-700' :
                  'bg-slate-50 text-slate-700'
                }`}>
                  {log.response_summary}
                </div>
              </div>
            )}
          </div>

          {/* Tab Navigation */}
          <div className="px-6 border-b border-slate-100">
            <div className="flex gap-4">
              <button
                onClick={() => setActiveTab('diff')}
                className={`py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'diff'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-slate-400 hover:text-slate-600'
                }`}
              >
                变更对比
              </button>
              <button
                onClick={() => setActiveTab('payload')}
                className={`py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === 'payload'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-slate-400 hover:text-slate-600'
                }`}
              >
                发布 Payload
              </button>
            </div>
          </div>

          {/* Tab Content */}
          <div className="px-6 py-4">
            {activeTab === 'diff' && (
              <div>
                {isRollbackDiff ? (
                  <DiffViewer
                    diff={null}
                    rollbackDiff={log.rollback_diff}
                    isRollback={true}
                  />
                ) : log.diff ? (
                  <DiffViewer diff={log.diff} />
                ) : (
                  <div className="text-center py-8 text-slate-400 text-sm">
                    无差异记录
                  </div>
                )}
              </div>
            )}

            {activeTab === 'payload' && (
              <div>
                {log.publish_payload ? (
                  <pre className="bg-slate-900 text-slate-100 p-4 rounded-lg text-xs overflow-auto max-h-96">
                    {JSON.stringify(log.publish_payload, null, 2)}
                  </pre>
                ) : (
                  <div className="text-center py-8 text-slate-400 text-sm">
                    无 Payload 记录
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Related Logs */}
          {log.related_logs && log.related_logs.length > 0 && (
            <div className="px-6 py-4 border-t border-slate-100">
              <h3 className="text-sm font-medium text-slate-700 mb-3">关联日志</h3>
              <div className="space-y-2">
                {log.related_logs.map(related => (
                  <div
                    key={related.id}
                    className="flex items-center justify-between py-2 px-3 bg-slate-50 rounded-lg text-sm"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-slate-500">#{related.id}</span>
                      <StatusBadge status={related.status as any} />
                    </div>
                    <span className="text-xs text-slate-400">
                      {formatDate(related.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 border-t border-slate-200 flex items-center justify-between">
          <div className="text-xs text-slate-400">
            目标系统: {log.target_system}
          </div>
          <div className="flex gap-2">
            {canRetry && (
              <button
                onClick={() => handleAction('retry', log.id)}
                disabled={actionLoading !== null}
                className="px-4 py-2 text-sm bg-amber-500 hover:bg-amber-400 text-white rounded-lg flex items-center gap-1.5 disabled:opacity-50 transition-colors"
              >
                {actionLoading === log.id ? (
                  <><i className="ri-loader-4-line animate-spin" /> 处理中...</>
                ) : (
                  <><i className="ri-restart-line" /> 重试</>
                )}
              </button>
            )}
            {canRollback && (
              <button
                onClick={() => handleAction('rollback', log.id)}
                disabled={actionLoading !== null}
                className="px-4 py-2 text-sm bg-red-600 hover:bg-red-500 text-white rounded-lg flex items-center gap-1.5 disabled:opacity-50 transition-colors"
              >
                {actionLoading === log.id ? (
                  <><i className="ri-loader-4-line animate-spin" /> 处理中...</>
                ) : (
                  <><i className="ri-arrow-go-back-line" /> 回滚</>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
