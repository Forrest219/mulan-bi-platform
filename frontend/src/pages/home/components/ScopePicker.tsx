/**
 * ScopePicker — 作用域选择工具栏
 *
 * 横向工具栏，包含：
 * 1. 连接下拉（从 ScopeContext 读取）
 * 2. 项目筛选输入框（占位）
 *
 * 无 Props，所有数据从 useScope() 读取。
 */
import { useScope } from '../context/ScopeContext';

export function ScopePicker() {
  const {
    connectionId,
    setConnectionId,
    scopeProject,
    setScopeProject,
    connections,
    connectionsLoading,
  } = useScope();

  return (
    <div className="flex items-center gap-3 px-4 py-2 border border-slate-200 rounded-lg bg-white">
      {/* 连接下拉 */}
      <div className="flex items-center gap-1.5">
        <label
          htmlFor="scope-connection"
          className="text-xs text-slate-500 whitespace-nowrap"
        >
          连接
        </label>
        <select
          id="scope-connection"
          disabled={connectionsLoading || connections.length === 0}
          value={connectionId ?? ''}
          onChange={(e) => setConnectionId(e.target.value || null)}
          className="text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded-md
                     px-2 py-1 focus:outline-none focus:border-blue-300 min-w-[120px]
                     disabled:opacity-50"
        >
          {connectionsLoading && (
            <option value="" disabled>
              加载中…
            </option>
          )}
          {!connectionsLoading && connections.length === 0 && (
            <option value="" disabled>
              暂无连接
            </option>
          )}
          {connections.map((c) => (
            <option key={c.id} value={String(c.id)}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <div className="h-4 w-px bg-slate-200" aria-hidden />

      {/* 项目筛选输入（占位） */}
      <div className="flex items-center gap-1.5">
        <label
          htmlFor="scope-project"
          className="text-xs text-slate-500 whitespace-nowrap"
        >
          项目
        </label>
        <input
          id="scope-project"
          type="text"
          placeholder="筛选项目…"
          value={scopeProject ?? ''}
          onChange={(e) => setScopeProject(e.target.value || null)}
          className="text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded-md
                     px-2 py-1 focus:outline-none focus:border-blue-300 min-w-[120px]
                     placeholder-slate-400"
        />
      </div>
    </div>
  );
}
