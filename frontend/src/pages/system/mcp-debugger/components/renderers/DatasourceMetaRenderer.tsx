import React, { useState, useMemo } from 'react';

interface Field {
  name?: string;
  description?: string;
  dataType?: string;
  role?: string;
}

interface DatasourceMeta {
  name?: string;
  luid?: string;
  id?: string;
  contentUrl?: string;
  createdAt?: string;
  updatedAt?: string;
  description?: string;
  projectName?: string;
  siteName?: string;
  fields?: Field[];
  fieldCount?: number;
}

interface Props {
  payload: unknown;
  raw: Record<string, unknown>;
}

const INFO_FIELDS: { key: keyof DatasourceMeta; label: string }[] = [
  { key: 'name', label: '名称' },
  { key: 'luid', label: 'LUID' },
  { key: 'projectName', label: '项目' },
  { key: 'siteName', label: '站点' },
  { key: 'updatedAt', label: '更新时间' },
  { key: 'description', label: '描述' },
];

function formatDate(ts?: string) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString('zh-CN');
  } catch {
    return ts;
  }
}

export default function DatasourceMetaRenderer({ payload }: Props) {
  const [fieldSearch, setFieldSearch] = useState('');

  const meta = (payload as DatasourceMeta) ?? {};
  const fields: Field[] = Array.isArray(meta.fields) ? meta.fields : [];

  const filtered = useMemo(() => {
    const q = fieldSearch.toLowerCase();
    if (!q) return fields;
    return fields.filter(
      (f) =>
        f.name?.toLowerCase().includes(q) ||
        f.description?.toLowerCase().includes(q) ||
        f.dataType?.toLowerCase().includes(q),
    );
  }, [fields, fieldSearch]);

  return (
    <div className="flex flex-col gap-4 h-full overflow-auto">
      {/* 基础信息卡片 */}
      <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
          数据源信息
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
          {INFO_FIELDS.map(({ key, label }) => {
            const val = meta[key];
            if (!val) return null;
            return (
              <div key={key} className="flex gap-2">
                <span className="text-slate-500 shrink-0 w-16">{label}:</span>
                <span className="text-slate-800 font-mono break-all">
                  {key === 'updatedAt' || key === 'createdAt' ? formatDate(val as string) : String(val)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 字段列表 */}
      <div className="flex flex-col gap-2 min-h-0">
        <div className="flex items-center gap-3 shrink-0">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            字段列表
            <span className="ml-1 text-slate-400 font-normal">
              ({filtered.length}
              {fieldSearch && fields.length !== filtered.length ? `/${fields.length}` : ''})
            </span>
          </div>
          <input
            type="text"
            value={fieldSearch}
            onChange={(e) => setFieldSearch(e.target.value)}
            placeholder="搜索字段..."
            className="flex-1 text-xs border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-400"
          />
        </div>

        {fields.length === 0 ? (
          <div className="text-xs text-slate-400 text-center py-4">无字段信息</div>
        ) : filtered.length === 0 ? (
          <div className="text-xs text-slate-400 text-center py-4">无匹配字段</div>
        ) : (
          <div className="flex-1 overflow-auto border border-slate-200 rounded-lg">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-slate-500">名称</th>
                  <th className="px-3 py-2 text-left font-medium text-slate-500">类型</th>
                  <th className="px-3 py-2 text-left font-medium text-slate-500">描述</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((f, idx) => (
                  <tr
                    key={f.name ?? idx}
                    className="border-b border-slate-100 hover:bg-blue-50/30 transition-colors"
                  >
                    <td className="px-3 py-2 font-mono text-slate-800 font-medium max-w-[160px] truncate" title={f.name}>
                      {f.name ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-slate-500 w-20">
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">
                        {f.dataType ?? '—'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-400 max-w-[240px] truncate" title={f.description}>
                      {f.description ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
