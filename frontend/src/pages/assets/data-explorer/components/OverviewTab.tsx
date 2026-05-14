import type { ExplorerError, ExplorerTable, TableOverview } from './types';

interface OverviewTabProps {
  table?: ExplorerTable | null;
  overview?: TableOverview | null;
  loading?: boolean;
  error?: string | ExplorerError | null;
  onRetry?: () => void;
}

function messageOf(error: OverviewTabProps['error']) {
  if (!error) return '';
  return typeof error === 'string' ? error : error.message;
}

function formatNumber(value?: number | null) {
  return typeof value === 'number' ? value.toLocaleString('zh-CN') : '—';
}

function formatBytes(value?: number | null) {
  if (typeof value !== 'number') return '—';
  if (value < 1024) return `${value} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let size = value / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

function formatDateTime(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

export default function OverviewTab({ table, overview, loading = false, error = null, onRetry }: OverviewTabProps) {
  const errorMessage = messageOf(error);

  if (loading) {
    return <div className="py-16 text-center text-[13px] text-slate-400"><i className="ri-loader-4-line animate-spin mr-1" />加载表概览...</div>;
  }

  if (errorMessage) {
    return (
      <div className="border border-red-100 bg-red-50 rounded-xl p-4 text-sm text-red-700">
        <div className="font-medium flex items-center gap-2"><i className="ri-error-warning-line" />概览加载失败</div>
        <p className="mt-1 text-[13px]">{errorMessage}</p>
        {onRetry && <button onClick={onRetry} className="mt-3 px-3 py-1.5 bg-white border border-red-200 rounded-lg text-[12px] hover:bg-red-50">重试</button>}
      </div>
    );
  }

  if (!overview && !table) {
    return <div className="py-16 text-center text-[13px] text-slate-400">请选择一张表查看概览</div>;
  }

  const current = overview ?? table;
  const stats = [
    { label: '字段数', value: overview?.column_count ?? table?.column_count },
    { label: '索引数', value: overview?.indexes_count },
    { label: '外键数', value: overview?.foreign_keys_count },
    { label: '行数估算', value: overview?.row_count_estimate ?? table?.row_count_estimate ?? table?.row_count },
    { label: '表容量', value: overview?.total_size_bytes, formatter: formatBytes },
  ];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-5 gap-3">
        {stats.map(item => (
          <div key={item.label} className="bg-white border border-slate-200 rounded-xl p-4">
            <div className="text-[11px] text-slate-400">{item.label}</div>
            <div className="mt-1 text-xl font-semibold text-slate-800">
              {item.formatter ? item.formatter(item.value) : formatNumber(item.value)}
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold text-slate-800">对象信息</h3>
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{current.type}</span>
        </div>
        <dl className="divide-y divide-slate-100 text-[13px]">
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">Schema</dt>
            <dd className="font-mono text-slate-700">{current.schema}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">Table</dt>
            <dd className="font-mono text-slate-700">{current.name}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">Primary Key</dt>
            <dd className="font-mono text-slate-700">{overview?.primary_key?.length ? overview.primary_key.join(', ') : '—'}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">数据容量</dt>
            <dd className="font-mono text-slate-700">{formatBytes(overview?.data_size_bytes)}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">索引容量</dt>
            <dd className="font-mono text-slate-700">{formatBytes(overview?.index_size_bytes)}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">创建日期</dt>
            <dd className="font-mono text-slate-700">{formatDateTime(overview?.created_at)}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">表级更新时间</dt>
            <dd className="font-mono text-slate-700">{formatDateTime(overview?.table_updated_at)}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">Comment</dt>
            <dd className="text-slate-700">{current.comment || '—'}</dd>
          </div>
          <div className="grid grid-cols-[140px_1fr] px-4 py-3">
            <dt className="text-slate-400">Preview</dt>
            <dd className={overview?.preview_available === false ? 'text-amber-600' : 'text-emerald-600'}>
              {overview?.preview_available === false ? '不可预览' : '可预览'}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
