import { useEffect, useState } from 'react';
import type { ExplorerError, PreviewCell, PreviewData } from './types';

interface PreviewTabProps {
  data?: PreviewData | null;
  loading?: boolean;
  error?: string | ExplorerError | null;
  onRetry?: () => void;
}

function messageOf(error: PreviewTabProps['error']) {
  if (!error) return '';
  return typeof error === 'string' ? error : error.message;
}

function formatCell(value: PreviewCell) {
  if (value === null) return <span className="text-slate-300">NULL</span>;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

export default function PreviewTab({ data = null, loading = false, error = null, onRetry }: PreviewTabProps) {
  const [slowLoading, setSlowLoading] = useState(false);
  const errorMessage = messageOf(error);

  useEffect(() => {
    if (!loading) {
      setSlowLoading(false);
      return;
    }
    const timer = window.setTimeout(() => setSlowLoading(true), 2000);
    return () => window.clearTimeout(timer);
  }, [loading]);

  if (loading) {
    return (
      <div className="py-16 text-center text-[13px] text-slate-400">
        <i className="ri-loader-4-line animate-spin mr-1" />
        {slowLoading ? '预览查询仍在执行，最多返回前 100 行...' : '加载预览数据...'}
      </div>
    );
  }

  if (errorMessage) {
    return (
      <div className="border border-red-100 bg-red-50 rounded-xl p-4 text-sm text-red-700">
        <div className="font-medium flex items-center gap-2"><i className="ri-error-warning-line" />预览加载失败</div>
        <p className="mt-1 text-[13px]">{errorMessage}</p>
        {onRetry && <button onClick={onRetry} className="mt-3 px-3 py-1.5 bg-white border border-red-200 rounded-lg text-[12px] hover:bg-red-50">重试</button>}
      </div>
    );
  }

  if (!data || data.columns.length === 0) {
    return <div className="py-16 text-center text-[13px] text-slate-400">暂无预览数据</div>;
  }

  if (data.rows.length === 0) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 text-[12px] text-slate-500">
          返回 0 行 · limit {data.limit ?? 100}
        </div>
        <div className="py-16 text-center text-[13px] text-slate-400">该对象没有可展示的数据行</div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <span className="text-[12px] text-slate-500">
          返回 {data.rows.length.toLocaleString('zh-CN')} 行 · limit {data.limit ?? 100}
        </span>
        {data.truncated && <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-600">已截断</span>}
      </div>
      <div className="overflow-x-auto max-h-[560px]">
        <table className="min-w-full text-[12px]">
          <thead className="sticky top-0 z-10 bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="sticky left-0 z-20 bg-slate-50 text-left px-3 py-2.5 text-[11px] font-medium text-slate-400 border-r border-slate-100 w-14">
                #
              </th>
              {data.columns.map(column => (
                <th key={column.name} className="text-left px-3 py-2.5 text-[11px] font-medium text-slate-500 whitespace-nowrap min-w-[140px]">
                  <div className="font-mono text-slate-700">{column.name}</div>
                  {column.data_type && <div className="mt-0.5 font-normal text-slate-400">{column.data_type}</div>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="hover:bg-slate-50/70">
                <td className="sticky left-0 bg-white px-3 py-2.5 text-slate-400 border-r border-slate-100">{rowIndex + 1}</td>
                {data.columns.map((column, columnIndex) => (
                  <td key={`${rowIndex}:${column.name}`} className="px-3 py-2.5 font-mono text-slate-700 whitespace-nowrap max-w-[360px] truncate">
                    {formatCell(row[columnIndex] ?? null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
