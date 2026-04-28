import { useState, useEffect } from 'react';
import { getConnectionHealthOverview, getSyncStatus, type HealthOverview } from '../../api/tableau';

interface SyncStatus {
  status: string;
  last_sync_at: string | null;
  last_sync_duration_sec: number | null;
  auto_sync_enabled: boolean;
  sync_interval_hours: number;
  next_sync_at: string | null;
}

export function useOpsSnapshot(connectionId: string | null) {
  const connId = connectionId ? Number(connectionId) : null;

  const [health, setHealth] = useState<HealthOverview | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState(false);

  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);

  useEffect(() => {
    if (!connId) return;
    setHealthLoading(true);
    setHealthError(false);
    getConnectionHealthOverview(connId)
      .then((data) => { setHealth(data); setHealthLoading(false); })
      .catch(() => { setHealthError(true); setHealthLoading(false); });
  }, [connId]);

  useEffect(() => {
    if (!connId) return;
    setSyncLoading(true);
    getSyncStatus(connId)
      .then((data) => { setSync(data); setSyncLoading(false); })
      .catch(() => setSyncLoading(false));
  }, [connId]);

  return { health, healthLoading, healthError, sync, syncLoading };
}
