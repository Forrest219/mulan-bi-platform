/**
 * ConnectionSelector — 数据源下拉选择器
 *
 * 使用 React.lazy + Suspense 懒加载，失败时降级为"全数据源"（不阻塞主流程）。
 */
import { useState, useEffect } from 'react';
import { listConnections, type ConnectionOption } from '../../../api/connections';

interface Props {
  value: number | null;
  onChange: (id: number | null) => void;
}

export function ConnectionSelector({ value, onChange }: Props) {
  const [connections, setConnections] = useState<ConnectionOption[]>([]);

  useEffect(() => {
    listConnections()
      .then(setConnections)
      .catch(() => {
        // 连接列表加载失败：降级为空列表，用户只能选"全数据源"
      });
  }, []);

  return (
    <select
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      className="text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded-md
                 px-2 py-1 focus:outline-none focus:border-blue-300 min-w-[140px]"
    >
      <option value="">全数据源</option>
      {connections.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name} ({c.type})
        </option>
      ))}
    </select>
  );
}
