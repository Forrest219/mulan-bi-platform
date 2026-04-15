import type { SearchAnswer, NumberData, TableData } from '../../../api/search';

interface SearchResultProps {
  result: SearchAnswer;
  onRetry: () => void;
}

export function SearchResult({ result, onRetry }: SearchResultProps) {
  if (result.type === 'number') {
    return <NumberCard data={result.data as NumberData} confidence={result.confidence} datasource={result.datasource} />;
  }
  if (result.type === 'table') {
    return <TableResult data={result.data as TableData} />;
  }
  if (result.type === 'text') {
    return <TextAnswer answer={result.answer} />;
  }
  if (result.type === 'error') {
    return (
      <ErrorCard
        code={result.reason || 'UNKNOWN'}
        detail={result.detail}
        onRetry={onRetry}
      />
    );
  }
  if (result.type === 'ambiguous') {
    const data = result.data as { candidates?: Array<{ id: number; name: string }> };
    return (
      <AmbiguousPicker
        candidates={data?.candidates || []}
        question={result.answer}
        onRetry={onRetry}
      />
    );
  }
  return null;
}

// ─── NumberCard ───────────────────────────────────────────────────────────────

interface NumberCardProps {
  data?: NumberData;
  confidence?: number;
  datasource?: { id: number; name: string };
}

function NumberCard({ data, confidence, datasource }: NumberCardProps) {
  const uncertain = confidence !== undefined && confidence < 0.6;
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6 text-center">
      {uncertain && (
        <span className="inline-block mb-2 text-xs px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full">
          AI 不确定
        </span>
      )}
      <div className="text-5xl font-bold text-slate-800 mb-1">
        {data?.formatted ?? data?.value ?? '—'}
      </div>
      {data?.unit && (
        <div className="text-xl text-slate-400 mb-2">{data.unit}</div>
      )}
      {datasource && (
        <div className="text-xs text-slate-400 mt-2">{datasource.name}</div>
      )}
    </div>
  );
}

// ─── TableResult ───────────────────────────────────────────────────────────────

interface TableResultProps {
  data?: TableData;
}

function TableResult({ data }: TableResultProps) {
  if (!data) return null;
  const rows = data.rows.slice(0, 10);
  const truncated = data.rows.length > 10;
  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {data.columns.map((col) => (
                <th key={col} className="px-4 py-2 text-left font-medium text-slate-600">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                {data.columns.map((col) => (
                  <td key={col} className="px-4 py-2 text-slate-700">{String(row[col] ?? '')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {truncated && (
        <div className="px-4 py-2 text-xs text-slate-400 bg-slate-50">
          共 {data.rows.length} 行，已截断显示前 10 行
        </div>
      )}
    </div>
  );
}

// ─── TextAnswer ──────────────────────────────────────────────────────────────

interface TextAnswerProps {
  answer: string;
}

function TextAnswer({ answer }: TextAnswerProps) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6">
      <pre className="text-sm text-slate-700 whitespace-pre-wrap">{answer}</pre>
    </div>
  );
}

// ─── ErrorCard ────────────────────────────────────────────────────────────────

export const ERROR_MESSAGES: Record<string, { title: string; hint: string }> = {
  NLQ_001: { title: '问题不合法', hint: '请用完整的中文或英文描述你的问题' },
  NLQ_003: { title: 'LLM 服务暂不可用', hint: '请稍后重试，或联系管理员' },
  NLQ_005: { title: '参数缺失', hint: '请指定数据源后重试' },
  NLQ_006: { title: '查询执行失败', hint: 'Tableau MCP 调用出错，请联系管理员' },
  NLQ_007: { title: '查询超时', hint: '问题较复杂，请简化后重试' },
  NLQ_008: { title: '字段未识别', hint: '没找到与问题相关的数据字段，请换种说法' },
  NLQ_009: { title: '无权限', hint: '该数据源访问被拒绝' },
  NLQ_010: { title: '查询过于频繁', hint: '每分钟最多 20 次，请稍后再试' },
  NLQ_011: { title: '敏感数据不支持查询', hint: '该数据源为高敏级别，请联系管理员' },
  UNKNOWN: { title: '未知错误', hint: '请重试或联系管理员' },
};

interface ErrorCardProps {
  code: string;
  detail?: string;
  onRetry: () => void;
}

export function ErrorCard({ code, detail, onRetry }: ErrorCardProps) {
  const info = ERROR_MESSAGES[code] ?? ERROR_MESSAGES.UNKNOWN;
  return (
    <div className="bg-white rounded-xl border border-red-200 p-6">
      <div className="flex items-start gap-3">
        <i className="ri-error-warning-line text-xl text-red-500 mt-0.5" />
        <div className="flex-1">
          <div className="font-semibold text-slate-800">{info.title}</div>
          <div className="text-sm text-slate-500 mt-1">{info.hint}</div>
          {detail && (
            <div className="text-xs text-slate-400 mt-2">{detail}</div>
          )}
        </div>
        <button
          onClick={onRetry}
          className="text-sm px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg transition-colors"
        >
          重试
        </button>
      </div>
    </div>
  );
}

// ─── AmbiguousPicker ──────────────────────────────────────────────────────────

interface AmbiguousPickerProps {
  candidates: Array<{ id: number; name: string }>;
  question: string;
  onRetry: () => void;
}

function AmbiguousPicker({ candidates, question, onRetry }: AmbiguousPickerProps) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6">
      <div className="text-sm text-slate-600 mb-4">{question || '请选择数据源'}</div>
      <div className="flex flex-wrap gap-2">
        {candidates.slice(0, 5).map((c) => (
          <button
            key={c.id}
            onClick={onRetry}
            className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm rounded-lg transition-colors"
          >
            {c.name}
          </button>
        ))}
      </div>
    </div>
  );
}
