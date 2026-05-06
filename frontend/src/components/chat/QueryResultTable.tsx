/**
 * QueryResultTable — 结构化查询结果表格
 *
 * - 数字列：右对齐，千分位 + 2 位小数，负数标红
 * - 点击表头排序（升/降序循环）
 * - 超 200 行分页（每页 50 条）
 */
import React, { useState, useMemo } from 'react';
import type { TableData } from '../../hooks/useStreamingChat';

interface Props {
  data: TableData;
}

type SortDir = 'asc' | 'desc' | null;

function formatNum(v: number): string {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const PAGE_SIZE = 50;

export default function QueryResultTable({ data }: Props) {
  const { fields, rows, col_types } = data;
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    if (sortCol === null || sortDir === null) return rows;
    return [...rows].sort((a, b) => {
      const va = a[sortCol];
      const vb = b[sortCol];
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      const cmp = typeof va === 'number' && typeof vb === 'number'
        ? va - vb
        : String(va).localeCompare(String(vb), 'zh-CN');
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [rows, sortCol, sortDir]);

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const pageRows = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function handleHeaderClick(idx: number) {
    if (sortCol !== idx) {
      setSortCol(idx);
      setSortDir('desc');
    } else if (sortDir === 'desc') {
      setSortDir('asc');
    } else {
      setSortCol(null);
      setSortDir(null);
    }
    setPage(0);
  }

  return (
    <div className="my-3">
      <div className="overflow-x-auto rounded-lg border border-slate-200 shadow-sm">
        <table className="min-w-full text-sm border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {fields.map((f, i) => (
                <th
                  key={i}
                  onClick={() => handleHeaderClick(i)}
                  className={`px-4 py-2.5 font-medium text-slate-700 cursor-pointer select-none whitespace-nowrap
                    hover:bg-slate-100 transition-colors
                    ${col_types[i] === 'numeric' ? 'text-right' : 'text-left'}`}
                >
                  <span className="inline-flex items-center gap-1">
                    {f}
                    {sortCol === i && (
                      <span className="text-blue-500 text-xs">
                        {sortDir === 'asc' ? '↑' : '↓'}
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, ri) => (
              <tr
                key={ri}
                className="border-b border-slate-100 last:border-0 hover:bg-blue-50/40 transition-colors"
              >
                {fields.map((_, ci) => {
                  const raw = row[ci];
                  const isNum = col_types[ci] === 'numeric';
                  const numVal = typeof raw === 'number' ? raw : null;
                  const display = isNum && numVal !== null
                    ? formatNum(numVal)
                    : raw === null || raw === undefined ? '—' : String(raw);
                  const isNeg = isNum && numVal !== null && numVal < 0;

                  return (
                    <td
                      key={ci}
                      className={`px-4 py-2 tabular-nums
                        ${isNum ? 'text-right' : 'text-left text-slate-700'}
                        ${isNeg ? 'text-red-600 font-medium' : isNum ? 'text-slate-800' : ''}`}
                    >
                      {display}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-2 px-1 text-xs text-slate-500">
        <span>共 {sorted.length} 条</span>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <button
              disabled={page === 0}
              onClick={() => setPage(p => p - 1)}
              className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-100 transition-colors"
            >
              上一页
            </button>
            <span>{page + 1} / {totalPages}</span>
            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage(p => p + 1)}
              className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-100 transition-colors"
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
