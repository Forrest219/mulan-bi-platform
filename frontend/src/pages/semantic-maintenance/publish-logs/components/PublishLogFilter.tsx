import { useState, useEffect } from 'react';
import { listConnections, TableauConnection } from '../../../../api/tableau';

export interface PublishLogFilters {
  connection_id?: number;
  object_type?: 'datasource' | 'field' | '';
  status?: string;
  operator_id?: number;
  start_date?: string;
  end_date?: string;
}

interface PublishLogFilterProps {
  onFilterChange: (filters: PublishLogFilters) => void;
  isAdmin: boolean;
}

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '进行中' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'rolled_back', label: '已回滚' },
  { value: 'not_supported', label: '不支持' },
];

const OBJECT_TYPE_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'datasource', label: '数据源' },
  { value: 'field', label: '字段' },
];

export function PublishLogFilter({ onFilterChange, isAdmin }: PublishLogFilterProps) {
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [filters, setFilters] = useState<PublishLogFilters>({
    connection_id: undefined,
    object_type: '',
    status: '',
    operator_id: undefined,
    start_date: '',
    end_date: '',
  });

  useEffect(() => {
    listConnections(true).then(data => {
      setConnections(data.connections);
    }).catch(() => {});
  }, []);

  const handleChange = (key: keyof PublishLogFilters, value: string | number | undefined) => {
    const newFilters = { ...filters, [key]: value || undefined };
    setFilters(newFilters);
    onFilterChange(newFilters);
  };

  const handleClear = () => {
    const cleared: PublishLogFilters = {
      connection_id: undefined,
      object_type: '',
      status: '',
      operator_id: undefined,
      start_date: '',
      end_date: '',
    };
    setFilters(cleared);
    onFilterChange(cleared);
  };

  const hasActiveFilters = Object.values(filters).some(v => v !== undefined && v !== '');

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      <div className="flex flex-wrap items-end gap-3">
        {/* Connection Filter */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500">Tableau 连接</label>
          <select
            value={filters.connection_id || ''}
            onChange={e => handleChange('connection_id', e.target.value ? Number(e.target.value) : undefined)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 min-w-[160px]"
          >
            <option value="">全部连接</option>
            {connections.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        {/* Object Type Filter */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500">对象类型</label>
          <select
            value={filters.object_type || ''}
            onChange={e => handleChange('object_type', e.target.value)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 min-w-[100px]"
          >
            {OBJECT_TYPE_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* Status Filter */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500">状态</label>
          <select
            value={filters.status || ''}
            onChange={e => handleChange('status', e.target.value)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 min-w-[100px]"
          >
            {STATUS_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* Date Range */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500">开始日期</label>
          <input
            type="date"
            value={filters.start_date || ''}
            onChange={e => handleChange('start_date', e.target.value)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500">结束日期</label>
          <input
            type="date"
            value={filters.end_date || ''}
            onChange={e => handleChange('end_date', e.target.value)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* Clear Button */}
        {hasActiveFilters && (
          <button
            onClick={handleClear}
            className="px-3 py-1.5 text-sm text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
          >
            清除筛选
          </button>
        )}
      </div>

      {/* Active filter tags */}
      {hasActiveFilters && (
        <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-slate-100">
          {filters.connection_id && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded-full">
              连接: {connections.find(c => c.id === filters.connection_id)?.name || filters.connection_id}
              <button onClick={() => handleChange('connection_id', undefined)} className="hover:text-blue-900">×</button>
            </span>
          )}
          {filters.object_type && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded-full">
              类型: {filters.object_type === 'datasource' ? '数据源' : '字段'}
              <button onClick={() => handleChange('object_type', '')} className="hover:text-blue-900">×</button>
            </span>
          )}
          {filters.status && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded-full">
              状态: {STATUS_OPTIONS.find(o => o.value === filters.status)?.label}
              <button onClick={() => handleChange('status', '')} className="hover:text-blue-900">×</button>
            </span>
          )}
          {filters.start_date && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded-full">
              开始: {filters.start_date}
              <button onClick={() => handleChange('start_date', '')} className="hover:text-blue-900">×</button>
            </span>
          )}
          {filters.end_date && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded-full">
              结束: {filters.end_date}
              <button onClick={() => handleChange('end_date', '')} className="hover:text-blue-900">×</button>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
