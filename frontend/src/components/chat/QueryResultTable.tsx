/**
 * QueryResultTable — 结构化查询结果表格
 *
 * - 数字列：右对齐，千分位 + 2 位小数，负数标红
 * - 点击表头排序（升/降序循环）
 * - 默认分页展示（每页 15 条）
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

function formatInteger(v: number): string {
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

function formatPercent(v: number): string {
  return v.toLocaleString('zh-CN', {
    style: 'percent',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const PAGE_SIZE = 15;

function escapeCsvCell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '';
  const text = String(value);
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function tableDataToCsv(headers: string[], rows: (string | number | null)[][]): string {
  const lines = [
    headers.map(escapeCsvCell).join(','),
    ...rows.map((row) => headers.map((_, idx) => escapeCsvCell(row[idx])).join(',')),
  ];
  return `\ufeff${lines.join('\r\n')}`;
}

function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export default function QueryResultTable({ data }: Props) {
  const { fields, rows, col_types, table_display } = data;
  const displayColumns = table_display?.columns;
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [page, setPage] = useState(0);

  function columnLabel(index: number): string {
    const label = displayColumns?.[index]?.label;
    return label && label.trim() ? label : fields[index];
  }

  function columnAlign(index: number): 'left' | 'right' | 'center' {
    const align = displayColumns?.[index]?.align;
    if (align === 'left' || align === 'right' || align === 'center') return align;
    return col_types[index] === 'numeric' ? 'right' : 'left';
  }

  function columnFormat(index: number): 'plain' | 'number' | 'integer' | 'percent' | 'date' | undefined {
    const column = displayColumns?.[index];
    if (column?.format) return column.format;
    if (column?.value_type === 'percent') return 'percent';
    if (column?.value_type === 'number') return 'number';
    return undefined;
  }

  function alignClass(index: number): string {
    const align = columnAlign(index);
    if (align === 'right') return 'text-right';
    if (align === 'center') return 'text-center';
    return 'text-left';
  }

  function justifyClass(index: number): string {
    const align = columnAlign(index);
    if (align === 'right') return 'justify-end';
    if (align === 'center') return 'justify-center';
    return 'justify-start';
  }

  function formatCellValue(raw: string | number | null, index: number): string {
    if (raw === null || raw === undefined) return '—';
    const format = columnFormat(index);
    if (format === 'percent') {
      return typeof raw === 'number' ? formatPercent(raw) : String(raw);
    }
    if (format === 'number') {
      return typeof raw === 'number' ? formatNum(raw) : String(raw);
    }
    if (format === 'integer') {
      return typeof raw === 'number' ? formatInteger(raw) : String(raw);
    }
    if (col_types[index] === 'numeric' && typeof raw === 'number') {
      return formatNum(raw);
    }
    return String(raw);
  }

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
  const displayStart = sorted.length === 0 ? 0 : page * PAGE_SIZE + 1;
  const displayEnd = Math.min((page + 1) * PAGE_SIZE, sorted.length);

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

  function handleDownloadCsv() {
    const headers = fields.map((_, idx) => columnLabel(idx));
    downloadCsv('mulan-query-result.csv', tableDataToCsv(headers, rows));
  }

  return (
    <div className="my-3">
      <div className="overflow-x-auto rounded-lg border border-slate-200 shadow-sm">
        <table className="min-w-full text-sm border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {fields.map((_, i) => (
                <th
                  key={i}
                  onClick={() => handleHeaderClick(i)}
                  className={`px-4 py-2.5 font-medium text-slate-700 cursor-pointer select-none whitespace-nowrap
                    hover:bg-slate-100 transition-colors
                    ${alignClass(i)}`}
                >
                  <span className={`flex w-full items-center gap-1 ${justifyClass(i)}`}>
                    {columnLabel(i)}
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
                  const format = columnFormat(ci);
                  const isNum = col_types[ci] === 'numeric' || format === 'number' || format === 'integer' || format === 'percent';
                  const numVal = typeof raw === 'number' ? raw : null;
                  const display = formatCellValue(raw, ci);
                  const isNeg = isNum && numVal !== null && numVal < 0;

                  return (
                    <td
                      key={ci}
                      className={`px-4 py-2 tabular-nums
                        ${alignClass(ci)} ${isNum ? '' : 'text-slate-700'}
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
        <span>显示 {displayStart}-{displayEnd} / 共 {sorted.length} 条</span>
        <div className="flex items-center gap-2">
          {rows.length > 0 && (
            <button
              type="button"
              onClick={handleDownloadCsv}
              className="inline-flex items-center gap-1.5 px-2 py-1 rounded border border-slate-200 text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors"
              title="下载当前已返回的数据"
            >
              <i className="ri-download-2-line" />
              <span>下载 CSV</span>
            </button>
          )}
          {totalPages > 1 && (
            <>
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
            </>
          )}
        </div>
      </div>
    </div>
  );
}
