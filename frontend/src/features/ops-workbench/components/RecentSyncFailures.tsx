/**
 * RecentSyncFailures — 同步失败状态展示（Phase 3 T9）
 *
 * 显示最近 5 条失败同步日志（来自 sync-logs?status=failed&limit=5）。
 * 同时保留 sync status 的兜底展示（当 failedSyncLogs 为空时）。
 */
import type { TableauSyncLog } from '../../../api/tableau';

interface SyncStatus {
  status: string;
  last_sync_at: string | null;
  last_sync_duration_sec: number | null;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  next_sync_at: string | null;
}

interface RecentSyncFailuresProps {
  /** 来自 getSyncStatus 的单条同步状态（兜底展示） */
  sync: SyncStatus | null;
  /** 来自 listSyncLogs 过滤的失败日志列表 */
  failedSyncLogs: TableauSyncLog[];
  failedSyncLogsLoading?: boolean;
}

function timeAgo(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}

function formatDuration(sec: number | null): string {
  if (sec === null) return '-';
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

export function RecentSyncFailures({ sync, failedSyncLogs, failedSyncLogsLoading }: RecentSyncFailuresProps) {
  if (!sync) return null;

  // 加载中状态（首次或切换连接时）
  if (failedSyncLogsLoading) {
    return (
      <div className="flex items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-400">
          <i className="ri-loader-2-line animate-spin" />
          加载同步记录...
        </span>
      </div>
    );
  }

  // 有失败日志时展示列表
  if (failedSyncLogs.length > 0) {
    return (
      <div className="space-y-1">
        <p className="text-xs font-medium text-slate-500 mb-1">最近同步失败</p>
        {failedSyncLogs.slice(0, 5).map((log) => (
          <div key={log.id} className="flex items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-1 min-w-0">
              <i className="ri-error-warning-line text-red-500 shrink-0" />
              <span className="text-red-600 truncate">
                {log.error_message ? log.error_message.slice(0, 30) : '同步失败'}
              </span>
            </div>
            <div className="flex items-center gap-2 shrink-0 text-slate-400">
              {log.duration_sec !== null && (
                <span className="font-mono">{formatDuration(log.duration_sec)}</span>
              )}
              <span>{timeAgo(log.started_at)}</span>
            </div>
          </div>
        ))}
      </div>
    );
  }

  // 无失败日志时回退到简单状态展示
  const isFailing = sync.status === 'failed' || sync.status === 'error';

  return (
    <div className="flex items-center gap-2 text-xs">
      {isFailing ? (
        <span className="inline-flex items-center gap-1 text-red-600">
          <i className="ri-error-warning-line" />
          同步失败
          {sync.last_sync_at && <span className="text-slate-400">· {timeAgo(sync.last_sync_at)}</span>}
        </span>
      ) : sync.status === 'running' || sync.status === 'syncing' ? (
        <span className="inline-flex items-center gap-1 text-blue-600">
          <i className="ri-loader-2-line animate-spin" />
          同步中...
        </span>
      ) : sync.last_sync_at ? (
        <span className="text-slate-400">
          最后同步：{timeAgo(sync.last_sync_at)}
        </span>
      ) : (
        <span className="text-slate-400">暂无同步记录</span>
      )}
    </div>
  );
}
