/**
 * ScopePicker — 作用域选择工具栏（Ops Workbench 版本）
 *
 * 默认"全部连接"，按需收窄到单个连接。
 */
import { useScope } from './ScopeContext';

interface ScopePickerProps {
  variant?: 'idle' | 'default';
}

export function ScopePicker({ variant = 'default' }: ScopePickerProps) {
  const {
    connectionId,
    setConnectionId,
    connections,
    connectionsLoading,
  } = useScope();

  const containerClass =
    variant === 'idle'
      ? 'flex items-center gap-3'
      : 'flex items-center gap-3 px-4 py-2 border border-slate-200 rounded-lg bg-white';

  return (
    <div className={containerClass}>
      <div className="flex items-center gap-1.5">
        <label
          htmlFor="scope-connection"
          className="text-xs text-slate-500 whitespace-nowrap"
        >
          连接
        </label>

        {connectionsLoading && (
          <select
            id="scope-connection"
            disabled
            className="text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded-md
                       px-2 py-1 focus:outline-none min-w-[120px] disabled:opacity-50"
          >
            <option value="">加载中…</option>
          </select>
        )}

        {!connectionsLoading && connections.length === 0 && (
          <span className="text-xs text-slate-400">暂无连接</span>
        )}

        {!connectionsLoading && connections.length > 0 && (
          <select
            id="scope-connection"
            value={connectionId ?? ''}
            onChange={(e) => setConnectionId(e.target.value || null)}
            className="text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded-md
                       px-2 py-1 focus:outline-none focus:border-blue-300 min-w-[120px]"
          >
            <option value="">全部</option>
            {connections.map((c) => (
              <option key={c.id} value={String(c.id)}>
                {c.name}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
