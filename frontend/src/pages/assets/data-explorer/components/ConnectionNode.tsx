import type { ExplorerConnection } from './types';

interface ConnectionNodeProps {
  connection: ExplorerConnection;
  expanded?: boolean;
  selected?: boolean;
  loading?: boolean;
  schemaCount?: number;
  onToggle?: (connection: ExplorerConnection) => void;
  onSelect?: (connection: ExplorerConnection) => void;
}

const DB_TYPE_LABEL: Record<string, string> = {
  postgres: 'PostgreSQL',
  postgresql: 'PostgreSQL',
  mysql: 'MySQL',
  starrocks: 'StarRocks',
  doris: 'Doris',
  sqlserver: 'SQL Server',
  hive: 'Hive',
};

function isConnectionBroken(connection: ExplorerConnection) {
  return connection.error?.error_code === 'DEX_010';
}

export default function ConnectionNode({
  connection,
  expanded = false,
  selected = false,
  loading = false,
  schemaCount,
  onToggle,
  onSelect,
}: ConnectionNodeProps) {
  const supported = connection.explorer_supported !== false;
  const broken = isConnectionBroken(connection);
  const disabled = !supported || !connection.is_active;
  const reason = !connection.is_active
    ? '连接已停用'
    : connection.unsupported_reason;
  const dbLabel = DB_TYPE_LABEL[connection.db_type] ?? connection.db_type;

  const handleClick = () => {
    onSelect?.(connection);
    if (!disabled) onToggle?.(connection);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled && !broken}
      className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
        selected
          ? 'bg-slate-900 text-white border-slate-900'
          : broken
            ? 'bg-red-50 text-red-700 border-red-100 hover:bg-red-100'
            : disabled
              ? 'bg-slate-50 text-slate-400 border-slate-100 cursor-not-allowed'
              : 'bg-white text-slate-700 border-transparent hover:bg-slate-50 hover:border-slate-100'
      }`}
      title={reason ?? undefined}
    >
      <div className="flex items-center gap-2 min-w-0">
        <i
          className={`text-base shrink-0 ${
            broken
              ? 'ri-plug-2-line text-red-500'
              : disabled
                ? 'ri-database-2-line text-slate-300'
                : 'ri-database-2-line'
          }`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-[13px] font-medium truncate">{connection.name}</span>
            {loading && <i className="ri-loader-4-line animate-spin text-xs opacity-70 shrink-0" />}
          </div>
          <div className={`mt-0.5 text-[11px] truncate ${selected ? 'text-slate-300' : broken ? 'text-red-500' : 'text-slate-400'}`}>
            {dbLabel}
            {connection.database_name ? ` · ${connection.database_name}` : ''}
            {typeof schemaCount === 'number' ? ` · ${schemaCount} schemas` : ''}
          </div>
          {(reason || broken) && (
            <div className={`mt-1 text-[11px] truncate ${broken ? 'text-red-600' : selected ? 'text-slate-300' : 'text-slate-400'}`}>
              {broken ? connection.error?.message ?? '目标数据库连接失败' : reason}
            </div>
          )}
        </div>
        <i className={`${expanded ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line'} text-sm opacity-70 shrink-0`} />
      </div>
    </button>
  );
}
