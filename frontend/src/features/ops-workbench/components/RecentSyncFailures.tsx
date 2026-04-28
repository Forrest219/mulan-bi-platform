/**
 * RecentSyncFailures — 同步失败状态展示
 */
interface SyncStatus {
  status: string;
  last_sync_at: string | null;
  last_sync_duration_sec: number | null;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  next_sync_at: string | null;
}

interface RecentSyncFailuresProps {
  sync: SyncStatus | null;
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

export function RecentSyncFailures({ sync }: RecentSyncFailuresProps) {
  if (!sync) return null;

  const isFailing = sync.status === 'failed' || sync.status === 'error';

  return (
    <div className="flex items-center gap-2 text-xs">
      {isFailing ? (
        <span className="inline-flex items-center gap-1 text-red-600">
          <i className="ri-error-warning-line" />
          同步失败
          {sync.last_sync_at && <span className="text-slate-400">· {timeAgo(sync.last_sync_at)}</span>}
        </span>
      ) : sync.status === 'syncing' ? (
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
