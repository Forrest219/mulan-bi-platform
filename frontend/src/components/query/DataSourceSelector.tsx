/**
 * DataSourceSelector — 数据源选择器
 *
 * 调用 GET /api/query/datasources?connection_id=<id> 获取用户有权限的数据源列表
 * Props 驱动，无业务状态（loading/data 由 hook 管理，此组件仅展示）
 *
 * connectionId 变化时重新请求
 */
import { useState, useEffect } from 'react';
import { listQueryDatasources, type QueryDatasource } from '../../api/query';

interface DataSourceSelectorProps {
  connectionId: number | null;
  value: string | null;
  onChange: (datasource: QueryDatasource | null) => void;
  disabled?: boolean;
}

export default function DataSourceSelector({
  connectionId,
  value,
  onChange,
  disabled = false,
}: DataSourceSelectorProps) {
  const [datasources, setDatasources] = useState<QueryDatasource[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // P0-2：使用 AbortController 取消过期请求，防止快速切换连接时慢请求覆盖结果
  useEffect(() => {
    if (connectionId == null) {
      setDatasources([]);
      onChange(null);
      return;
    }

    const controller = new AbortController();
    const { signal } = controller;

    // connectionId 变化时重置选中项
    onChange(null);
    setLoading(true);
    setError(null);

    listQueryDatasources(connectionId, signal)
      .then((data) => {
        if (signal.aborted) return;
        setDatasources(data);
      })
      .catch((err) => {
        if (signal.aborted) return;
        setError(err instanceof Error ? err.message : '加载数据源失败');
        setDatasources([]);
      })
      .finally(() => {
        if (!signal.aborted) setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [connectionId, onChange]);

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const luid = e.target.value;
    const found = datasources.find((d) => d.luid === luid) ?? null;
    onChange(found);
  };

  if (connectionId == null) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <i className="ri-database-2-line" />
        <span>请先选择连接</span>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <i className="ri-loader-4-line animate-spin" />
        <span>加载数据源...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 text-sm text-red-500">
        <i className="ri-error-warning-line" />
        <span>{error}</span>
      </div>
    );
  }

  if (datasources.length === 0) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <i className="ri-database-2-line" />
        <span>暂无可用数据源</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <i className="ri-database-2-line text-sm text-slate-500 shrink-0" />
      <select
        value={value ?? ''}
        onChange={handleChange}
        disabled={disabled}
        aria-label="选择数据源"
        className="text-sm text-slate-700 bg-white border border-slate-200 rounded-lg px-2 py-1.5
                   focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400
                   disabled:opacity-50 disabled:cursor-not-allowed transition-colors max-w-[240px] truncate"
      >
        <option value="">选择数据源...</option>
        {datasources.map((ds) => (
          <option key={ds.luid} value={ds.luid}>
            {ds.name}
          </option>
        ))}
      </select>
    </div>
  );
}
