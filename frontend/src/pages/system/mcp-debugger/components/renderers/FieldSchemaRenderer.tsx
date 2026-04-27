import React, { useState, useMemo } from 'react';

interface SchemaField {
  name?: string;
  fully_qualified_name?: string;
  data_type?: string;
  role?: string;
  data_category?: string;
  description?: string;
  formula?: string;
  default_aggregation?: string;
  is_hidden?: boolean;
}

interface FieldSchema {
  datasource_luid?: string;
  datasource_name?: string;
  field_count?: number;
  total_fields?: number;
  visible_fields?: number;
  fields?: SchemaField[];
  dimensions?: SchemaField[];
  measures?: SchemaField[];
  other_fields?: SchemaField[];
}

interface Props {
  payload: unknown;
  raw: Record<string, unknown>;
}

type GroupKey = 'dimensions' | 'measures' | 'other';

const GROUP_LABELS: Record<GroupKey, { label: string; color: string; bg: string }> = {
  dimensions: { label: '维度 (DIMENSION)', color: 'text-purple-700', bg: 'bg-purple-50 border-purple-200' },
  measures: { label: '指标 (MEASURE)', color: 'text-blue-700', bg: 'bg-blue-50 border-blue-200' },
  other: { label: '其他', color: 'text-slate-700', bg: 'bg-slate-50 border-slate-200' },
};

const TABLE_COLS = [
  { key: 'name' as const, label: '字段名', width: 'w-40' },
  { key: 'data_type' as const, label: '类型', width: 'w-24' },
  { key: 'default_aggregation' as const, label: '默认聚合', width: 'w-24' },
  { key: 'is_hidden' as const, label: '隐藏', width: 'w-12' },
  { key: 'description' as const, label: '描述' },
];

function ExpandedRow({ field }: { field: SchemaField }) {
  return (
    <div className="px-4 py-3 bg-slate-50 border-t border-slate-100 text-xs space-y-2">
      {field.formula && (
        <div>
          <span className="text-slate-500 font-medium">Formula: </span>
          <code className="text-slate-700 bg-slate-100 px-1.5 py-0.5 rounded font-mono text-[11px]">
            {field.formula}
          </code>
        </div>
      )}
      {field.fully_qualified_name && (
        <div>
          <span className="text-slate-500 font-medium">完全限定名: </span>
          <span className="text-slate-600 font-mono">{field.fully_qualified_name}</span>
        </div>
      )}
      {field.description && (
        <div>
          <span className="text-slate-500 font-medium">描述: </span>
          <span className="text-slate-600">{field.description}</span>
        </div>
      )}
    </div>
  );
}

export default function FieldSchemaRenderer({ payload }: Props) {
  const schema = useMemo<FieldSchema>(() => (payload as FieldSchema) ?? {}, [payload]);
  const [search, setSearch] = useState('');
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  // 从 dimensions/measures/other_fields 或 fields 三个入口取数据
  const groups = useMemo(() => {
    const result: { key: GroupKey; label: string; color: string; bg: string; fields: SchemaField[] }[] = [];

    if (schema.dimensions || schema.measures || schema.other_fields) {
      // 已经是分组结构
      for (const key of ['dimensions', 'measures', 'other'] as GroupKey[]) {
        const arr = schema[key === 'dimensions' ? 'dimensions' : key === 'measures' ? 'measures' : 'other_fields'] as SchemaField[] | undefined;
        if (arr && arr.length > 0) {
          const { label, color, bg } = GROUP_LABELS[key];
          result.push({ key, label, color, bg, fields: arr });
        }
      }
    } else if (Array.isArray(schema.fields)) {
      // 扁平字段列表，按 role 分组
      const grouped: Record<string, SchemaField[]> = { dimensions: [], measures: [], other: [] };
      for (const f of schema.fields) {
        const role = f.role ?? 'OTHER';
        const gKey = role === 'DIMENSION' ? 'dimensions' : role === 'MEASURE' ? 'measures' : 'other';
        grouped[gKey].push(f);
      }
      for (const key of ['dimensions', 'measures', 'other'] as GroupKey[]) {
        if (grouped[key].length > 0) {
          const { label, color, bg } = GROUP_LABELS[key];
          result.push({ key, label, color, bg, fields: grouped[key] });
        }
      }
    }

    return result;
  }, [schema]);

  const totalVisible = groups.reduce((sum, g) => sum + g.fields.length, 0);

  const toggleRow = (idx: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* 顶部摘要 */}
      <div className="flex items-center gap-4 shrink-0 bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5 text-xs">
        <div className="flex items-center gap-1.5 text-slate-600">
          <i className="ri-database-2-line text-blue-500" />
          <span className="font-medium">{schema.datasource_name ?? schema.datasource_luid ?? '未知数据源'}</span>
        </div>
        <div className="text-slate-400">
          字段总数: <strong className="text-slate-700">{schema.field_count ?? schema.total_fields ?? totalVisible}</strong>
        </div>
        {schema.visible_fields != null && (
          <div className="text-slate-400">
            可见字段: <strong className="text-slate-700">{schema.visible_fields}</strong>
          </div>
        )}
      </div>

      {/* 搜索 */}
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="搜索字段名、类型、描述..."
        className="shrink-0 text-xs border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-400"
      />

      {/* 分组字段表 */}
      <div className="flex-1 overflow-auto">
        {groups.length === 0 ? (
          <div className="text-xs text-slate-400 text-center py-8">无字段数据</div>
        ) : (
          <div className="space-y-4">
            {groups.map(({ key, label, color, bg, fields: grpFields }) => {
              const filtered = search
                ? grpFields.filter(
                    (f) =>
                      !search ||
                      f.name?.toLowerCase().includes(search.toLowerCase()) ||
                      f.data_type?.toLowerCase().includes(search.toLowerCase()) ||
                      f.description?.toLowerCase().includes(search.toLowerCase()),
                  )
                : grpFields;

              if (filtered.length === 0 && search) return null;

              return (
                <div key={key} className="border border-slate-200 rounded-lg overflow-hidden">
                  <div className={`px-3 py-2 border-b ${bg} ${color} text-xs font-semibold flex items-center gap-2`}>
                    {label}
                    <span className={`${color} opacity-60 font-normal`}>({filtered.length})</span>
                  </div>

                  {filtered.length === 0 ? (
                    <div className="text-xs text-slate-400 text-center py-3">无匹配</div>
                  ) : (
                    <table className="w-full text-xs">
                      <thead className="bg-slate-50 border-b border-slate-100">
                        <tr>
                          <th className="w-4 px-3 py-1.5" />
                          {TABLE_COLS.map((c) => (
                            <th key={c.key} className={`px-3 py-1.5 text-left font-medium text-slate-500 ${c.width ?? ''}`}>
                              {c.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map((f, idx) => {
                          const globalIdx = grpFields.indexOf(f);
                          const isExpanded = expandedRows.has(globalIdx);
                          return (
                            <React.Fragment key={f.name ?? idx}>
                              <tr
                                className="border-b border-slate-100 hover:bg-blue-50/30 transition-colors cursor-pointer"
                                onClick={() => toggleRow(globalIdx)}
                              >
                                <td className="px-2 py-1.5 text-slate-400">
                                  <i className={`${isExpanded ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line'} text-[10px]`} />
                                </td>
                                <td className="px-3 py-1.5 font-mono text-slate-800 font-medium max-w-[160px] truncate" title={f.name}>
                                  {f.name ?? '—'}
                                </td>
                                <td className="px-3 py-1.5 w-24">
                                  <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">
                                    {f.data_type ?? '—'}
                                  </span>
                                </td>
                                <td className="px-3 py-1.5 text-slate-500 w-24">{f.default_aggregation ?? '—'}</td>
                                <td className="px-3 py-1.5 w-12 text-center">
                                  {f.is_hidden ? (
                                    <span className="text-slate-400 text-[10px]">是</span>
                                  ) : (
                                    <span className="text-slate-300 text-[10px]">否</span>
                                  )}
                                </td>
                                <td className="px-3 py-1.5 text-slate-400 max-w-[200px] truncate" title={f.description}>
                                  {f.description ?? '—'}
                                </td>
                              </tr>
                              {isExpanded && <ExpandedRow field={f} />}
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
