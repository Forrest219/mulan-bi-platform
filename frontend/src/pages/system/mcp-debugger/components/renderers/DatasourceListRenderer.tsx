import React, { useState, useCallback, useMemo } from 'react';

interface Datasource {
  name?: string;
  luid?: string;
  id?: string;
  contentUrl?: string;
  createdAt?: string;
  updatedAt?: string;
  description?: string;
  size?: string;
  projectName?: string;
  siteName?: string;
}

interface Props {
  payload: unknown;
  raw: Record<string, unknown>;
}

// 从 raw payload 中找数组
function extractDatasources(payload: unknown): Datasource[] {
  if (Array.isArray(payload)) return payload as Datasource[];
  if (payload && typeof payload === 'object') {
    const obj = payload as Record<string, unknown>;
    // 常见 key
    for (const key of ['datasources', 'data', 'items', 'result', 'sources']) {
      if (Array.isArray(obj[key])) return obj[key] as Datasource[];
    }
    // fallback: 把对象本身当单条
    return [obj as Datasource];
  }
  return [];
}

const COLUMNS: { key: keyof Datasource; label: string; width?: string }[] = [
  { key: 'name', label: '名称' },
  { key: 'luid', label: 'LUID', width: 'w-32' },
  { key: 'projectName', label: '项目' },
  { key: 'updatedAt', label: '更新时间', width: 'w-36' },
  { key: 'description', label: '描述' },
];

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  }, [text]);
  return (
    <button
      onClick={copy}
      className="ml-1 text-xs px-1 py-0.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-500 transition-colors"
      title="复制"
    >
      {copied ? '✓' : '📋'}
    </button>
  );
}

function formatDate(ts: string) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}

export default function DatasourceListRenderer({ payload, raw }: Props) {
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<keyof Datasource>('updatedAt');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const datasources = useMemo(() => extractDatasources(payload), [payload]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return datasources
      .filter((ds) => {
        if (!q) return true;
        return (
          ds.name?.toLowerCase().includes(q) ||
          ds.luid?.toLowerCase().includes(q) ||
          ds.description?.toLowerCase().includes(q) ||
          ds.projectName?.toLowerCase().includes(q)
        );
      })
      .sort((a, b) => {
        const av = (a[sortKey] ?? '') as string;
        const bv = (b[sortKey] ?? '') as string;
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      });
  }, [datasources, search, sortKey, sortDir]);

  const handleSort = (key: keyof Datasource) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* 顶部统计 + 搜索 */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <i className="ri-database-2-line text-blue-500" />
          <span>
            共 <strong className="text-slate-700">{filtered.length}</strong> 个数据源
            {search && <span className="text-slate-400">（筛选自 {datasources.length}）</span>}
          </span>
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索名称、LUID、项目..."
          className="flex-1 text-xs border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-400"
        />
      </div>

      {/* 表格 */}
      {filtered.length === 0 ? (
        <div className="text-sm text-slate-400 text-center py-8">
          {datasources.length === 0 ? '无数据' : '无匹配结果'}
        </div>
      ) : (
        <div className="flex-1 overflow-auto border border-slate-200 rounded-lg">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 border-b border-slate-200">
              <tr>
                {COLUMNS.map((col) => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    className={`px-3 py-2 text-left font-medium text-slate-500 cursor-pointer hover:text-slate-700 select-none ${col.width ?? ''} ${
                      sortKey === col.key ? 'text-blue-600' : ''
                    }`}
                  >
                    {col.label}
                    {sortKey === col.key && (sortDir === 'asc' ? ' ↑' : ' ↓')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((ds, idx) => (
                <tr
                  key={ds.luid ?? ds.id ?? idx}
                  className="border-b border-slate-100 hover:bg-blue-50/30 transition-colors"
                >
                  <td className="px-3 py-2 font-medium text-slate-800 max-w-[200px] truncate" title={ds.name}>
                    {ds.name ?? '—'}
                  </td>
                  <td className="px-3 py-2 font-mono text-slate-500 w-32">
                    <div className="flex items-center">
                      <span className="truncate max-w-[120px]" title={ds.luid ?? ds.id}>
                        {ds.luid ?? ds.id ?? '—'}
                      </span>
                      {(ds.luid ?? ds.id) && (
                        <CopyButton text={ds.luid ?? (ds.id ?? '')} />
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-slate-600 max-w-[150px] truncate" title={ds.projectName}>
                    {ds.projectName ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-slate-500 w-36 whitespace-nowrap">
                    {formatDate(ds.updatedAt ?? ds.createdAt ?? '')}
                  </td>
                  <td className="px-3 py-2 text-slate-400 max-w-[200px] truncate" title={ds.description}>
                    {ds.description ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
