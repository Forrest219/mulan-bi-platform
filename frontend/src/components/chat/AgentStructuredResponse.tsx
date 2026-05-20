import QueryResultTable from './QueryResultTable';
import { tableDataFromStructuredPayload } from '../../hooks/useStreamingChat';
import {
  asRecord,
  fieldGroupsFromAssetMetadata,
  normalizeAnalysisSuggestions,
  normalizeStructuredResponse,
  type JsonRecord,
  type StructuredFieldGroup,
} from './AgentStructuredResponse.utils';

interface Props {
  responseType?: string | null;
  responseData?: unknown;
  tableDataAlreadyRendered?: boolean;
}

function textValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value);
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function formatDateTime(value: unknown): string {
  const raw = textValue(value);
  if (!raw) return '—';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function sourceLabel(source: unknown): string {
  if (source === 'catalog_cache') return 'Catalog cache 缓存';
  if (source === 'mcp') return 'Tableau MCP';
  return textValue(source) || 'Agent';
}

function candidatesFromPayload(payload?: JsonRecord): JsonRecord[] {
  const raw = payload?.candidates;
  if (!Array.isArray(raw)) return [];
  return raw.map(asRecord).filter((item): item is JsonRecord => !!item);
}

function SourceBadge({ source }: { source: unknown }) {
  return (
    <span className="inline-flex items-center rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-normal text-slate-500">
      {sourceLabel(source)}
    </span>
  );
}

function AssetInventory({ payload }: { payload: JsonRecord }) {
  const candidates = candidatesFromPayload(payload);
  const total = numberValue(payload.total_count) ?? candidates.length;
  const shown = numberValue(payload.shown_count) ?? candidates.length;
  const hasProject = candidates.some((item) => textValue(item.project_name));
  const hasFieldCount = candidates.some((item) => item.field_count !== null && item.field_count !== undefined);
  const hasSyncedAt = candidates.some((item) => textValue(item.synced_at));

  return (
    <section className="not-prose my-3 rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-3 py-2">
        <div className="flex items-center gap-2">
          <i className="ri-database-2-line text-slate-400" />
          <div>
            <h4 className="text-sm font-medium text-slate-800">数据源清单</h4>
            <p className="text-xs text-slate-500">
              共 {total} 个{shown !== total ? `，当前显示 ${shown} 个` : ''}
            </p>
          </div>
        </div>
        <SourceBadge source={payload.source} />
      </div>

      {candidates.length === 0 ? (
        <p className="px-3 py-3 text-sm text-slate-500">当前连接没有可展示的数据源。</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50 text-xs text-slate-500">
                <th className="px-3 py-2 text-left font-medium">数据源</th>
                {hasProject && <th className="px-3 py-2 text-left font-medium">项目</th>}
                {hasFieldCount && <th className="px-3 py-2 text-right font-medium">字段数</th>}
                {hasSyncedAt && <th className="px-3 py-2 text-left font-medium">最近同步</th>}
              </tr>
            </thead>
            <tbody>
              {candidates.map((item, index) => (
                <tr key={`${textValue(item.datasource_luid) || textValue(item.asset_id) || index}`} className="border-b border-slate-100 last:border-0 hover:bg-blue-50/30">
                  <td className="px-3 py-2 text-slate-800">
                    <div className="font-medium">{textValue(item.name) || '未命名数据源'}</div>
                    {textValue(item.datasource_luid) && (
                      <div className="mt-0.5 font-mono text-[11px] text-slate-400">{textValue(item.datasource_luid)}</div>
                    )}
                  </td>
                  {hasProject && <td className="px-3 py-2 text-slate-600">{textValue(item.project_name) || '—'}</td>}
                  {hasFieldCount && <td className="px-3 py-2 text-right tabular-nums text-slate-700">{textValue(item.field_count) || '—'}</td>}
                  {hasSyncedAt && <td className="px-3 py-2 whitespace-nowrap text-slate-600">{formatDateTime(item.synced_at)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CandidateClarification({ payload }: { payload: JsonRecord }) {
  const candidates = candidatesFromPayload(payload);
  return (
    <section className="not-prose my-3 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-amber-800">
        <i className="ri-questionnaire-line" />
        <span>请指定一个数据源</span>
      </div>
      {candidates.length > 0 ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {candidates.map((item, index) => (
            <div key={`${textValue(item.datasource_luid) || index}`} className="rounded-md border border-amber-100 bg-white px-3 py-2">
              <div className="text-sm font-medium text-slate-800">{textValue(item.name) || '未命名数据源'}</div>
              <div className="mt-1 text-xs text-slate-500">
                {textValue(item.project_name) || '未标注项目'}
                {item.field_count !== null && item.field_count !== undefined ? ` · ${textValue(item.field_count)} 个字段` : ''}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-amber-700">{textValue(payload.message) || '找到多个可能的数据源，请补充名称后继续。'}</p>
      )}
    </section>
  );
}

function limitedFieldGroups(groups: StructuredFieldGroup[], limit: number): StructuredFieldGroup[] {
  let remaining = limit;
  const visible: StructuredFieldGroup[] = [];
  for (const group of groups) {
    if (remaining <= 0) break;
    const fields = group.fields.slice(0, remaining);
    if (fields.length > 0) {
      visible.push({ ...group, fields });
      remaining -= fields.length;
    }
  }
  return visible;
}

function fieldDisplayName(field: JsonRecord): { name: string; rawName: string; type: string } {
  const name = textValue(field.caption) || textValue(field.field_caption) || textValue(field.name) || textValue(field.field_name);
  const rawName = textValue(field.name) || textValue(field.field_name);
  const type = textValue(field.dataType) || textValue(field.data_type) || textValue(field.type);
  return { name, rawName, type };
}

function qualityNotice(metadataQuality: unknown): string {
  const qualityRecord = asRecord(metadataQuality);
  const quality = qualityRecord ? textValue(qualityRecord.status) : textValue(metadataQuality);
  const message = qualityRecord ? textValue(qualityRecord.message) : '';
  if (quality === 'partial') return '元数据质量：部分字段信息不完整，字段说明、类型或分组可能缺失。';
  if (quality === 'empty') return message || '元数据质量：当前未获取到可展示字段，可能需要重新同步或检查 Tableau 元数据权限。';
  return '';
}

function MetadataQualityNotice({ metadataQuality }: { metadataQuality: unknown }) {
  const message = qualityNotice(metadataQuality);
  if (!message) return null;
  return (
    <p className="mt-2 rounded-md bg-orange-50 px-2 py-1.5 text-xs text-orange-700">
      {message}
    </p>
  );
}

function AssetMetadataFields({ groups, totalFields }: { groups: StructuredFieldGroup[]; totalFields: number }) {
  const displayedGroups = limitedFieldGroups(groups, 30);
  const displayedCount = displayedGroups.reduce((sum, group) => sum + group.fields.length, 0);

  if (displayedGroups.length === 0) {
    return (
      <p className="px-3 py-3 text-sm text-slate-500">当前没有可展示的字段。</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      {displayedGroups.map((group, groupIndex) => (
        <div key={`${group.name || 'fields'}-${groupIndex}`} className="border-b border-slate-100 last:border-0">
          {(displayedGroups.length > 1 || group.name) && (
            <div className="flex items-center justify-between bg-slate-50/80 px-3 py-2 text-xs text-slate-500">
              <span className="font-medium text-slate-600">{group.name || '字段列表'}</span>
              <span>{group.fields.length} 个字段</span>
            </div>
          )}
          <table className="min-w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50 text-xs text-slate-500">
                <th className="px-3 py-2 text-left font-medium">字段</th>
                <th className="px-3 py-2 text-left font-medium">说明</th>
                <th className="px-3 py-2 text-left font-medium">类型</th>
              </tr>
            </thead>
            <tbody>
              {group.fields.map((field, index) => {
                const { name, rawName, type } = fieldDisplayName(field);
                return (
                  <tr key={`${rawName || name || groupIndex}-${index}`} className="border-b border-slate-100 last:border-0">
                    <td className="px-3 py-2 text-slate-800">
                      <div className="font-medium">{name || rawName || '未命名字段'}</div>
                      {rawName && rawName !== name && <div className="mt-0.5 font-mono text-[11px] text-slate-400">{rawName}</div>}
                    </td>
                    <td className="px-3 py-2 text-slate-600">{textValue(field.description) || '—'}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-slate-600">{type || '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
      {totalFields > displayedCount && (
        <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
          已显示前 {displayedCount} 个字段，共 {totalFields} 个。
        </p>
      )}
    </div>
  );
}

function AnalysisSuggestions({ suggestions }: { suggestions: ReturnType<typeof normalizeAnalysisSuggestions> }) {
  if (suggestions.length === 0) return null;
  return (
    <div className="border-t border-slate-100 px-3 py-3">
      <h5 className="mb-2 text-xs font-medium text-slate-600">分析建议</h5>
      <div className="grid gap-2">
        {suggestions.map((suggestion, index) => (
          <div key={`${suggestion.title}-${index}`} className="rounded-md border border-blue-100 bg-blue-50/40 px-3 py-2">
            <div className="text-sm font-medium text-slate-800">{suggestion.title}</div>
            {suggestion.fields.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {suggestion.fields.map((field) => (
                  <span key={field} className="rounded border border-blue-100 bg-white px-1.5 py-0.5 text-[11px] text-blue-700">
                    {field}
                  </span>
                ))}
              </div>
            )}
            {suggestion.exampleQuestions.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-slate-600">
                {suggestion.exampleQuestions.map((question) => (
                  <li key={question} className="flex gap-1.5">
                    <span className="text-blue-400">•</span>
                    <span>{question}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function AssetMetadata({ payload }: { payload: JsonRecord }) {
  const fieldGroups = fieldGroupsFromAssetMetadata(payload);
  const totalFields = fieldGroups.reduce((sum, group) => sum + group.fields.length, 0);
  const fieldCount = numberValue(payload.field_count) ?? totalFields;
  const suggestions = normalizeAnalysisSuggestions(payload.analysis_suggestions);
  const isCache = payload.source === 'catalog_cache';

  return (
    <section className="not-prose my-3 rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-100 px-3 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h4 className="text-sm font-medium text-slate-800">{textValue(payload.datasource_name) || '数据源元数据'}</h4>
            <p className="mt-1 text-xs text-slate-500">
              {textValue(payload.project_name) || '未标注项目'} · {fieldCount} 个字段
            </p>
          </div>
          <SourceBadge source={payload.source} />
        </div>
        {isCache && (
          <p className="mt-2 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-700">
            Tableau MCP metadata 暂不可用，以下内容来自本地 catalog cache 缓存。
          </p>
        )}
        <MetadataQualityNotice metadataQuality={payload.metadata_quality} />
        {textValue(payload.description) && (
          <p className="mt-2 text-sm leading-relaxed text-slate-600">{textValue(payload.description)}</p>
        )}
        {payload.metadata_freshness !== null && payload.metadata_freshness !== undefined && (
          <p className="mt-2 text-xs text-slate-400">元数据新鲜度：{formatDateTime(payload.metadata_freshness)}</p>
        )}
      </div>

      <AssetMetadataFields groups={fieldGroups} totalFields={totalFields} />
      <AnalysisSuggestions suggestions={suggestions} />
    </section>
  );
}

function StructuredNotice({ payload, tone }: { payload: JsonRecord; tone: 'warning' | 'error' }) {
  const isError = tone === 'error';
  return (
    <section className={`not-prose my-3 rounded-lg border px-3 py-3 ${isError ? 'border-red-200 bg-red-50 text-red-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
      <div className="flex items-start gap-2">
        <i className={`${isError ? 'ri-error-warning-line' : 'ri-information-line'} mt-0.5`} />
        <div>
          <p className="text-sm font-medium">{textValue(payload.message) || (isError ? '工具暂不可用' : '未找到匹配资产')}</p>
          {textValue(payload.user_hint) && <p className="mt-1 text-xs opacity-80">{textValue(payload.user_hint)}</p>}
        </div>
      </div>
    </section>
  );
}

export default function AgentStructuredResponse({
  responseType,
  responseData,
  tableDataAlreadyRendered = false,
}: Props) {
  const { responseType: normalizedType, payload } = normalizeStructuredResponse(responseType, responseData);
  if (!normalizedType || !payload) return null;

  if (normalizedType === 'asset_candidates') {
    return payload.reason === 'list_datasources'
      ? <AssetInventory payload={payload} />
      : <CandidateClarification payload={payload} />;
  }

  if (normalizedType === 'clarification') {
    return candidatesFromPayload(payload).length > 0
      ? <CandidateClarification payload={payload} />
      : <StructuredNotice payload={payload} tone="warning" />;
  }

  if (normalizedType === 'asset_metadata') {
    return <AssetMetadata payload={payload} />;
  }

  if (normalizedType === 'asset_not_found') {
    return <StructuredNotice payload={payload} tone="warning" />;
  }

  if (normalizedType === 'tool_unavailable') {
    return <StructuredNotice payload={payload} tone="error" />;
  }

  if (!tableDataAlreadyRendered && (normalizedType === 'query_result' || normalizedType === 'table')) {
    const tableData = tableDataFromStructuredPayload(payload, normalizedType);
    return tableData ? <QueryResultTable data={tableData} /> : null;
  }

  return null;
}
