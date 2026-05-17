import type { TaskRun } from '../../../api/tasks';

function getResultNumber(result: Record<string, unknown> | null, key: string): number | null {
  const value = result?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function SyncLogLink({ run }: { run: TaskRun }) {
  const syncLogId = getResultNumber(run.result_summary, 'sync_log_id');
  const connectionId = getResultNumber(run.result_summary, 'connection_id');

  if (syncLogId === null) {
    return <span className="text-xs text-slate-400">-</span>;
  }

  if (connectionId === null) {
    return <span className="text-xs text-slate-500 font-mono">#{syncLogId}</span>;
  }

  return (
    <a
      href={`/assets/tableau-connections/${connectionId}/sync-logs`}
      className="text-xs text-blue-600 hover:text-blue-700 hover:underline font-mono"
    >
      #{syncLogId}
    </a>
  );
}
