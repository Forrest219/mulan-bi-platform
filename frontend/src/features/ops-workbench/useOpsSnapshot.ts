import { useState, useEffect } from 'react';
import {
  getConnectionHealthOverview,
  getSyncStatus,
  listSyncLogs,
  type HealthOverview,
  type TableauSyncLog,
} from '../../api/tableau';

interface SyncStatus {
  status: string;
  last_sync_at: string | null;
  last_sync_duration_sec: number | null;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  next_sync_at: string | null;
}

/**
 * useOpsSnapshot — 运维快照数据 hook（Phase 3 T10）
 *
 * 数据来源：
 *  - health overview → getConnectionHealthOverview(connId)
 *  - sync status     → getSyncStatus(connId)
 *  - failed syncs    → listSyncLogs(connId, { page_size: 5 }) 后过滤 status=failed
 *
 * React Query key 以 connectionId 为主键，ScopeContext 切换连接时自动 refetch。
 */
export function useOpsSnapshot(connectionId: string | null) {
  const connId = connectionId ? Number(connectionId) : null;

  const [health, setHealth] = useState<HealthOverview | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState(false);

  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);

  const [failedSyncLogs, setFailedSyncLogs] = useState<TableauSyncLog[]>([]);
  const [failedSyncLogsLoading, setFailedSyncLogsLoading] = useState(false);

  // 健康总览（OI-1-A: GET /api/tableau/connections/{conn_id}/health-overview）
  useEffect(() => {
    if (!connId) return;
    setHealthLoading(true);
    setHealthError(false);
    getConnectionHealthOverview(connId)
      .then((data) => { setHealth(data); setHealthLoading(false); })
      .catch(() => { setHealthError(true); setHealthLoading(false); });
  }, [connId]);

  // 同步状态（兼容旧 RecentSyncFailures 单状态展示）
  useEffect(() => {
    if (!connId) return;
    setSyncLoading(true);
    getSyncStatus(connId)
      .then((data) => { setSync(data); setSyncLoading(false); })
      .catch(() => setSyncLoading(false));
  }, [connId]);

  // 失败同步日志（GET /api/tableau/connections/{conn_id}/sync-logs?status=failed&limit=5）
  // listSyncLogs 暂不支持 server 端 status 过滤，在此做客户端过滤
  useEffect(() => {
    if (!connId) return;
    setFailedSyncLogsLoading(true);
    listSyncLogs(connId, { page_size: 20 })
      .then((res) => {
        const failed = res.logs.filter((log) => log.status === 'failed').slice(0, 5);
        setFailedSyncLogs(failed);
      })
      .catch(() => setFailedSyncLogs([]))
      .finally(() => setFailedSyncLogsLoading(false));
  }, [connId]);

  return {
    health,
    healthLoading,
    healthError,
    sync,
    syncLoading,
    failedSyncLogs,
    failedSyncLogsLoading,
  };
}
