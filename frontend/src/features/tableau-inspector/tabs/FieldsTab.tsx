import { useMemo, useState } from 'react';
import { FieldMetadataStatus, FieldSemantic } from '../types';

interface FieldsTabProps {
  fieldSemantics: FieldSemantic[];
  fieldMetadata: FieldMetadataStatus | null;
  fieldsLoading: boolean;
}

const CACHE_STATUS_LABELS: Record<string, string> = {
  cached: '缓存命中',
  fresh: 'MCP 已刷新',
  stale: '缓存兜底',
  miss: '无缓存',
};

const MCP_STATUS_LABELS: Record<string, string> = {
  ok: '全部可查询',
  partial: '部分可查询',
  unknown: '未校验',
  error: 'MCP 异常',
};

const MCP_STATUS_CLASSES: Record<string, string> = {
  ok: 'bg-emerald-50 text-emerald-700',
  partial: 'bg-amber-50 text-amber-700',
  unknown: 'bg-slate-100 text-slate-600',
  error: 'bg-red-50 text-red-700',
};

type FieldFilter = 'all' | 'queryable' | 'catalog_only' | 'mcp_error' | 'mcp' | 'measure' | 'dimension' | 'calculation' | 'formula' | 'hidden';

const FIELD_FILTERS: Array<{ key: FieldFilter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'queryable', label: 'Agent 可查询' },
  { key: 'catalog_only', label: '仅资产目录' },
  { key: 'mcp_error', label: 'MCP 异常' },
  { key: 'mcp', label: 'MCP 字段' },
  { key: 'measure', label: '度量' },
  { key: 'dimension', label: '维度' },
  { key: 'calculation', label: '计算字段' },
  { key: 'formula', label: '有公式' },
  { key: 'hidden', label: '隐藏字段' },
];

function formatTime(value?: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

function getFieldName(field: FieldSemantic) {
  return field.field || field.name || '-';
}

function getFieldMeaning(field: FieldSemantic) {
  return field.meaning || field.description || '';
}

function getFullyQualifiedName(field: FieldSemantic) {
  return field.fully_qualified_name || field.fullyQualifiedName || field.mcp?.fullyQualifiedName || '';
}

function isHiddenField(field: FieldSemantic) {
  return field.is_hidden ?? field.isHidden ?? field.mcp?.isHidden ?? false;
}

function getFieldRole(field: FieldSemantic) {
  return (field.role || field.mcp?.role || '').toLowerCase();
}

function getDataType(field: FieldSemantic) {
  return field.data_type || field.dataType || field.mcp?.dataType || '';
}

function getFormula(field: FieldSemantic) {
  return field.formula || field.mcp?.formula || '';
}

function getAggregation(field: FieldSemantic) {
  return field.aggregation || field.mcp?.defaultAggregation || '';
}

function isMcpField(field: FieldSemantic) {
  if (field.mcp && Object.values(field.mcp).some(v => v != null)) return true;
  return field.source === 'mcp' || field.source_label?.toLowerCase().includes('mcp');
}

function isCalculatedField(field: FieldSemantic) {
  return field.mcp?.columnClass?.toUpperCase() === 'CALCULATION' || Boolean(getFormula(field));
}

function queryabilityStatus(field: FieldSemantic) {
  if (field.queryability_status) return field.queryability_status;
  if (field.mcp_last_error) return 'error';
  if (field.mcp_checked_at == null && field.mcp_queryable == null) return 'unknown';
  if (field.mcp_queryable === true) return 'queryable';
  if (field.mcp_queryable === false) return 'catalog_only';
  return 'unknown';
}

function queryabilityBadge(field: FieldSemantic) {
  const status = queryabilityStatus(field);
  if (status === 'queryable') return { label: 'Agent 可查询', className: 'bg-emerald-50 text-emerald-700' };
  if (status === 'catalog_only') return { label: '仅资产目录', className: 'bg-amber-50 text-amber-700' };
  if (status === 'error') return { label: 'MCP 异常', className: 'bg-red-50 text-red-700' };
  return { label: '未校验', className: 'bg-slate-100 text-slate-600' };
}

function matchesFilter(field: FieldSemantic, filter: FieldFilter) {
  if (filter === 'all') return true;
  if (filter === 'queryable') return queryabilityStatus(field) === 'queryable';
  if (filter === 'catalog_only') return queryabilityStatus(field) === 'catalog_only';
  if (filter === 'mcp_error') return queryabilityStatus(field) === 'error';
  if (filter === 'mcp') return isMcpField(field);
  if (filter === 'measure') return getFieldRole(field) === 'measure';
  if (filter === 'dimension') return getFieldRole(field) === 'dimension';
  if (filter === 'calculation') return isCalculatedField(field);
  if (filter === 'formula') return Boolean(getFormula(field));
  if (filter === 'hidden') return isHiddenField(field);
  return true;
}

function matchesSearch(field: FieldSemantic, query: string) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  return [
    getFieldName(field),
    field.caption,
    field.mcp?.logicalTableId,
    getFormula(field),
    field.description,
    field.meaning,
  ].some(value => String(value || '').toLowerCase().includes(normalizedQuery));
}

function getMcpTags(field: FieldSemantic) {
  const tags: string[] = [];
  if (isMcpField(field)) tags.push('MCP');
  if (field.mcp?.columnClass) tags.push(field.mcp.columnClass);
  const role = getFieldRole(field);
  if (role) tags.push(role.toUpperCase());
  if (field.mcp?.dataCategory) tags.push(field.mcp.dataCategory);
  const aggregation = getAggregation(field);
  if (aggregation) tags.push(aggregation);
  if (isHiddenField(field)) tags.push('隐藏字段');
  if (getFormula(field)) tags.push('有公式');
  return Array.from(new Set(tags.filter(Boolean)));
}

export function FieldsTab({ fieldSemantics, fieldMetadata, fieldsLoading }: FieldsTabProps) {
  const [activeFilter, setActiveFilter] = useState<FieldFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const catalogFieldCount = fieldMetadata?.catalog_field_count ?? fieldMetadata?.field_count ?? fieldSemantics.length;
  const queryableFieldCount = fieldMetadata?.queryable_field_count ?? fieldSemantics.filter(field => queryabilityStatus(field) === 'queryable').length;
  const catalogOnlyCount = fieldMetadata?.catalog_only_count ?? fieldSemantics.filter(field => queryabilityStatus(field) === 'catalog_only').length;
  const localFieldCount = fieldMetadata?.local_field_count ?? catalogFieldCount;
  const cacheStatus = fieldMetadata?.cache_status || (fieldSemantics.length > 0 ? 'cached' : null);
  const cacheStatusLabel = cacheStatus ? CACHE_STATUS_LABELS[cacheStatus] || cacheStatus : '-';
  const mcpStatus = fieldMetadata?.mcp_status || 'unknown';
  const mcpStatusLabel = MCP_STATUS_LABELS[mcpStatus] || mcpStatus;
  const mcpStatusClass = MCP_STATUS_CLASSES[mcpStatus] || MCP_STATUS_CLASSES.unknown;
  const updatedAt = fieldMetadata?.mcp_checked_at || fieldMetadata?.updated_at || fieldMetadata?.cached_at;
  const filteredFields = useMemo(
    () => fieldSemantics.filter(field => matchesFilter(field, activeFilter) && matchesSearch(field, searchQuery)),
    [activeFilter, fieldSemantics, searchQuery],
  );
  const hasFilters = activeFilter !== 'all' || searchQuery.trim().length > 0;

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-100">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h3 className="text-xs font-semibold text-slate-700">字段元数据</h3>
            <p className="text-xs text-slate-400 mt-0.5">数据源字段信息</p>
          </div>
          <div className="text-xs text-slate-500">
            显示 {filteredFields.length} / {fieldSemantics.length} 个字段
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-3">
          <span className="text-[11px] px-2 py-1 rounded bg-slate-100 text-slate-600">
            资产字段 {catalogFieldCount ?? localFieldCount ?? 0}
          </span>
          <span className="text-[11px] px-2 py-1 rounded bg-emerald-50 text-emerald-700">
            Agent 可查询 {queryableFieldCount ?? 0}
          </span>
          <span className="text-[11px] px-2 py-1 rounded bg-amber-50 text-amber-700">
            仅资产目录 {catalogOnlyCount ?? 0}
          </span>
          <span className={`text-[11px] px-2 py-1 rounded ${
            cacheStatus === 'fresh' ? 'bg-emerald-50 text-emerald-600' :
            cacheStatus === 'stale' ? 'bg-amber-50 text-amber-600' :
            'bg-blue-50 text-blue-600'
          }`}>
            缓存状态 {cacheStatusLabel}
          </span>
          <span className={`text-[11px] px-2 py-1 rounded ${mcpStatusClass}`}>
            MCP 状态 {mcpStatusLabel}
          </span>
          <span className="text-[11px] px-2 py-1 rounded bg-slate-100 text-slate-600">
            MCP 校验时间 {formatTime(updatedAt)}
          </span>
          {fieldMetadata?.mcp_last_error && (
            <span className="text-[11px] px-2 py-1 rounded bg-red-50 text-red-700 max-w-full truncate" title={fieldMetadata.mcp_last_error}>
              {fieldMetadata.mcp_last_error}
            </span>
          )}
        </div>
        <div className="mt-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap gap-2">
            {FIELD_FILTERS.map(filter => (
              <button
                key={filter.key}
                type="button"
                onClick={() => setActiveFilter(filter.key)}
                className={`text-[11px] px-2.5 py-1 rounded-full border transition ${
                  activeFilter === filter.key
                    ? 'border-blue-200 bg-blue-50 text-blue-700'
                    : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <input
            value={searchQuery}
            onChange={event => setSearchQuery(event.target.value)}
            placeholder="搜索字段名、Caption、逻辑表、公式、描述"
            className="w-full xl:w-80 rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-50"
          />
        </div>
      </div>
      {fieldSemantics.length === 0 ? (
        <div className="text-center py-10 text-slate-400 text-xs">
          {fieldsLoading ? '正在加载字段数据...' : '暂无字段数据'}
        </div>
      ) : filteredFields.length === 0 ? (
        <div className="text-center py-10 text-slate-400 text-xs">
          {hasFilters ? '当前筛选无匹配字段' : '暂无字段数据'}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1180px] table-fixed">
            <thead>
              <tr className="bg-slate-50">
                {[
                  ['字段名', 'w-[210px]'],
                  ['中文名', 'w-[140px]'],
                  ['Agent 状态', 'w-[120px]'],
                  ['数据类型', 'w-[100px]'],
                  ['角色', 'w-[90px]'],
                  ['MCP 属性', 'w-[270px]'],
                  ['逻辑表', 'w-[180px]'],
                  ['描述/公式摘要', 'w-[290px]'],
                ].map(([h, width]) => (
                  <th key={h} className={`text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5 ${width}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredFields.map((f, i) => {
                const fullyQualifiedName = getFullyQualifiedName(f);
                const formula = getFormula(f);
                const description = getFieldMeaning(f);
                const role = getFieldRole(f);
                const queryability = queryabilityBadge(f);
                return (
                  <tr key={`${getFieldName(f)}-${i}`} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2.5 text-xs text-slate-700 align-top">
                      <div className="font-mono break-words">{getFieldName(f)}</div>
                      {fullyQualifiedName && (
                        <div className="text-[10px] text-slate-400 font-mono truncate" title={fullyQualifiedName}>
                          {fullyQualifiedName}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-600 align-top break-words">{f.caption || '-'}</td>
                    <td className="px-4 py-2.5 align-top">
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded ${queryability.className}`}
                        title={f.mcp_last_error || undefined}
                      >
                        {queryability.label}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500 align-top">{getDataType(f) || '-'}</td>
                    <td className="px-4 py-2.5 align-top">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                        role === 'measure' ? 'bg-blue-50 text-blue-600' : 'bg-slate-100 text-slate-600'
                      }`}>{role || '-'}</span>
                    </td>
                    <td className="px-4 py-2.5 align-top">
                      <div className="flex flex-wrap gap-1">
                        {getMcpTags(f).map(tag => (
                          <span
                            key={tag}
                            className={`text-[10px] px-1.5 py-0.5 rounded ${
                              tag === '隐藏字段' ? 'bg-amber-50 text-amber-600' :
                              tag === '有公式' ? 'bg-violet-50 text-violet-600' :
                              tag === 'MCP' ? 'bg-emerald-50 text-emerald-600' :
                              'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {tag}
                          </span>
                        ))}
                        {getMcpTags(f).length === 0 && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                            {f.source_label || f.source || '本地缓存'}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500 align-top">
                      <div className="font-mono text-[11px] truncate" title={f.mcp?.logicalTableId || ''}>
                        {f.mcp?.logicalTableId || '-'}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500 align-top">
                      {formula ? (
                        <div className="space-y-1">
                          <div className="font-mono text-[11px] truncate" title={formula}>{formula}</div>
                          {description && <div className="truncate" title={description}>{description}</div>}
                        </div>
                      ) : (
                        <div className="truncate" title={description}>{description || '-'}</div>
                      )}
                    </td>
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
