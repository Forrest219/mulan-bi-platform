import type { ExplorerError, TableColumn } from './types';

interface SchemaTabProps {
  columns?: TableColumn[];
  loading?: boolean;
  error?: string | ExplorerError | null;
  onRetry?: () => void;
}

const ROLE_LABEL: Record<string, string> = {
  identifier: '标识',
  time: '时间',
  measure: '度量',
  flag: '标志',
  dimension: '维度',
};

function messageOf(error: SchemaTabProps['error']) {
  if (!error) return '';
  return typeof error === 'string' ? error : error.message;
}

export default function SchemaTab({ columns = [], loading = false, error = null, onRetry }: SchemaTabProps) {
  const errorMessage = messageOf(error);

  if (loading) {
    return <div className="py-16 text-center text-[13px] text-slate-400"><i className="ri-loader-4-line animate-spin mr-1" />加载字段...</div>;
  }

  if (errorMessage) {
    return (
      <div className="border border-red-100 bg-red-50 rounded-xl p-4 text-sm text-red-700">
        <div className="font-medium flex items-center gap-2"><i className="ri-error-warning-line" />字段加载失败</div>
        <p className="mt-1 text-[13px]">{errorMessage}</p>
        {onRetry && <button onClick={onRetry} className="mt-3 px-3 py-1.5 bg-white border border-red-200 rounded-lg text-[12px] hover:bg-red-50">重试</button>}
      </div>
    );
  }

  if (columns.length === 0) {
    return <div className="py-16 text-center text-[13px] text-slate-400">暂无字段信息</div>;
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <table className="w-full text-[13px]">
        <thead className="bg-slate-50 border-b border-slate-100">
          <tr>
            <th className="text-left px-4 py-3 text-[11px] font-medium text-slate-500">字段</th>
            <th className="text-left px-4 py-3 text-[11px] font-medium text-slate-500">类型</th>
            <th className="text-left px-4 py-3 text-[11px] font-medium text-slate-500">Nullable</th>
            <th className="text-left px-4 py-3 text-[11px] font-medium text-slate-500">角色</th>
            <th className="text-left px-4 py-3 text-[11px] font-medium text-slate-500">默认值</th>
            <th className="text-left px-4 py-3 text-[11px] font-medium text-slate-500">说明</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {columns.map(column => (
            <tr key={column.name} className="hover:bg-slate-50/70">
              <td className="px-4 py-3">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono text-slate-800 truncate">{column.name}</span>
                  {column.is_primary_key && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">PK</span>}
                  {column.is_indexed && <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">IDX</span>}
                </div>
              </td>
              <td className="px-4 py-3 font-mono text-slate-600">{column.data_type}</td>
              <td className="px-4 py-3 text-slate-500">{column.nullable === false ? '否' : '是'}</td>
              <td className="px-4 py-3">
                {column.semantic_role ? (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">
                    {ROLE_LABEL[column.semantic_role] ?? column.semantic_role}
                  </span>
                ) : '—'}
              </td>
              <td className="px-4 py-3 font-mono text-slate-500 max-w-[180px] truncate">{column.default ?? '—'}</td>
              <td className="px-4 py-3 text-slate-500 max-w-[260px] truncate">{column.comment || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
