import { useMemo, useState } from 'react';
import type { SearchAnswer } from '../../../api/search';

interface DataUsedFooterProps {
  result?: SearchAnswer | null;
  timestamp?: string;
}

function formatTimestamp(input?: string): string {
  if (!input) return '刚刚';
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) return '刚刚';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function DataUsedFooter({ result, timestamp }: DataUsedFooterProps) {
  const [expanded, setExpanded] = useState(false);

  const connectionLabel = useMemo(() => {
    if (result?.datasource?.name) return result.datasource.name;
    if (result?.datasource_luid) return `LUID: ${result.datasource_luid}`;
    return '默认连接';
  }, [result?.datasource?.name, result?.datasource_luid]);

  const scopeLabel = useMemo(() => {
    if (!result?.query) return '当前可访问数据范围';
    if (typeof result.query === 'string') return result.query.slice(0, 40);
    if (Array.isArray(result.query)) return `查询步骤 ${result.query.length} 项`;
    return '已应用查询逻辑';
  }, [result?.query]);

  const logicText = useMemo(() => {
    if (!result) return '暂无 SQL/logic 可展示';
    if (!result.query) return '暂无 SQL/logic 可展示';
    if (typeof result.query === 'string') return result.query;
    try {
      return JSON.stringify(result.query, null, 2);
    } catch {
      return '查询逻辑不可序列化';
    }
  }, [result]);

  return (
    <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1">
          <i className="ri-database-2-line" />
          {connectionLabel}
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="ri-time-line" />
          {formatTimestamp(timestamp)}
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="ri-shield-check-line" />
          {scopeLabel}
        </span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="ml-auto text-xs text-blue-600 hover:text-blue-700"
        >
          {expanded ? '收起 SQL/logic' : '显示 SQL/logic'}
        </button>
      </div>
      {expanded && (
        <pre className="mt-2 max-h-48 overflow-auto rounded-md border border-slate-200 bg-white p-2 text-[11px] text-slate-600 whitespace-pre-wrap">
          {logicText}
        </pre>
      )}
    </div>
  );
}
