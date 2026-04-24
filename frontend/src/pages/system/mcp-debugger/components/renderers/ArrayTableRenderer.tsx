import React, { useState, useMemo } from 'react';

interface Props {
  rows: unknown[];
  toolName: string;
  hint?: string;
}

// 自动推断列：从 rows 中找出所有 key，按出现频率排序
function inferColumns(rows: unknown[]): { key: string; label: string }[] {
  const freq: Record<string, number> = {};
  for (const row of rows) {
    if (row && typeof row === 'object') {
      for (const key of Object.keys(row as Record<string, unknown>)) {
        freq[key] = (freq[key] ?? 0) + 1;
      }
    }
  }
  return Object.entries(freq)
    .sort((a, b) => b[1] - a[1])
    .map(([key]) => ({ key, label: niceLabel(key) }));
}

function niceLabel(key: string): string {
  return key
    .replace(/_([a-z])/g, (_, c) => c.toUpperCase())
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, (s) => s.toUpperCase())
    .trim();
}

// 判断某字段是否像是 ID / token 类需要截断展示
function isIdLike(key: string, val: unknown): boolean {
  const str = String(val ?? '');
  return (
    /(id|ID$|luid|Luid|token|Token|key|Key)$/.test(key) ||
    (str.length > 24 && /^[a-zA-Z0-9_\-]+$/.test(str))
  );
}

function isDateLike(val: unknown): boolean {
  const str = String(val ?? '');
  return /^\d{4}-\d{2}-\d{2}T\d{2}:/.test(str) || /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(str);
}

function formatCell(val: unknown, isId: boolean, isDate: boolean): string {
  if (val == null || val === '') return '—';
  if (typeof val === 'boolean') return val ? '是' : '否';
  const str = String(val);
  if (isDate) {
    try {
      const d = new Date(str);
      if (!isNaN(d.getTime())) {
        return d.toLocaleString('zh-CN');
      }
    } catch { /* fall through */ }
  }
  if (isId && str.length > 24) return str.slice(0, 12) + '…' + str.slice(-8);
  return str;
}

export default function ArrayTableRenderer({ rows, toolName, hint }: Props) {
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<string>('');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const columns = useMemo(() => inferColumns(rows), [rows]);

  const filtered = useMemo(() => {
    let result = rows.filter((row) => {
      if (!search || !columns.length) return true;
      const q = search.toLowerCase();
      return columns.some(({ key }) => {
        const val = (row as Record<string, unknown>)?.[key];
        return String(val ?? '').toLowerCase().includes(q);
      });
    });

    if (sortKey) {
      result = [...result].sort((a, b) => {
        const av = (a as Record<string, unknown>)?.[sortKey] ?? '';
        const bv = (b as Record<string, unknown>)?.[sortKey] ?? '';
        return sortDir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
      });
    }

    return result;
  }, [rows, search, columns, sortKey, sortDir]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const copyId = (val: string, key: string) => {
    const id = `${key}:${val}`;
    navigator.clipboard.writeText(val).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 1200);
    });
  };

  const countLabel = hint ?? `${rows.length} 条记录`;

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* 顶栏 */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <i className="ri-list-check-2 text-blue-500" />
          <span>
            <strong className="text-slate-700">{filtered.length}</strong> {countLabel}
            {search && rows.length !== filtered.length && (
              <span className="text-slate-400">（筛选自 {rows.length}）</span>
            )}
          </span>
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`搜索 ${columns.map((c) => c.label).join(' / ')}...`}
          className="flex-1 text-xs border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-400"
        />
      </div>

      {/* 表格 */}
      {filtered.length === 0 ? (
        <div className="text-xs text-slate-400 text-center py-8">
          {rows.length === 0 ? '无数据' : '无匹配结果'}
        </div>
      ) : (
        <div className="flex-1 overflow-auto border border-slate-200 rounded-lg">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 border-b border-slate-200 z-10">
              <tr>
                {columns.map((col) => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    className={`px-3 py-2 text-left font-medium cursor-pointer hover:text-slate-700 select-none whitespace-nowrap ${
                      sortKey === col.key ? 'text-blue-600' : 'text-slate-500'
                    }`}
                  >
                    {col.label}
                    {sortKey === col.key && (sortDir === 'asc' ? ' ↑' : ' ↓')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, idx) => {
                const obj = row as Record<string, unknown>;
                return (
                  <tr
                    key={idx}
                    className="border-b border-slate-100 hover:bg-blue-50/30 transition-colors"
                  >
                    {columns.map((col) => {
                      const val = obj?.[col.key];
                      const isId = isIdLike(col.key, val);
                      const isDate = isDateLike(val);
                      const display = formatCell(val, isId, isDate);
                      const cellId = `${idx}-${col.key}`;

                      return (
                        <td
                          key={col.key}
                          className={`px-3 py-1.5 max-w-[240px] truncate ${isId ? 'font-mono text-slate-500' : 'text-slate-700'}`}
                          title={String(val ?? '')}
                        >
                          {display}
                          {isId && val && copiedId !== cellId && (
                            <button
                              onClick={(e) => { e.stopPropagation(); copyId(String(val), cellId); }}
                              className="ml-1 text-slate-300 hover:text-slate-500 text-[10px]"
                              title="复制完整值"
                            >
                              📋
                            </button>
                          )}
                          {copiedId === cellId && (
                            <span className="ml-1 text-green-500 text-[10px]">✓</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
