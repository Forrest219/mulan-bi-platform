import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Components } from 'react-markdown';
import type { SearchAnswer, NumberData, TableData } from '../../../api/search';

interface SearchResultProps {
  result: SearchAnswer;
  onRetry: () => void;
}

export function SearchResult({ result, onRetry }: SearchResultProps) {
  if (result.type === 'error') {
    return (
      <ErrorCard
        code={result.reason || 'UNKNOWN'}
        detail={result.detail}
        onRetry={onRetry}
      />
    );
  }

  return (
    <div>
      {result.type === 'number' && (
        <NumberCard data={result.data as NumberData} confidence={result.confidence} datasource={result.datasource} />
      )}
      {result.type === 'table' && (
        <TableResult data={result.data as TableData} />
      )}
      {result.type === 'text' && (
        <TextAnswer answer={result.answer} />
      )}
      {result.type === 'ambiguous' && (() => {
        const data = result.data as { candidates?: Array<{ id: number; name: string }> };
        return (
          <AmbiguousPicker
            candidates={data?.candidates || []}
            question={result.answer}
            onRetry={onRetry}
          />
        );
      })()}

    </div>
  );
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

// ─── SimpleBarChart ───────────────────────────────────────────────────────────

interface BarChartRow {
  label: string;
  value: number;
}

interface SimpleBarChartProps {
  rows: BarChartRow[];
  dimCol: string;
  metricCol: string;
}

function SimpleBarChart({ rows, dimCol, metricCol }: SimpleBarChartProps) {
  const maxValue = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="px-4 py-4">
      <div className="flex items-center gap-2 mb-3 text-xs text-slate-400">
        <span>{dimCol}</span>
        <span className="mx-1">vs</span>
        <span>{metricCol}</span>
      </div>
      <div className="space-y-2">
        {rows.map((row, i) => {
          const pct = Math.max((row.value / maxValue) * 100, 0);
          const label = row.label.length > 12 ? row.label.slice(0, 12) + '…' : row.label;
          return (
            <div key={i} className="flex items-center gap-3">
              <div className="w-24 shrink-0 text-xs text-slate-600 text-right truncate" title={row.label}>
                {label}
              </div>
              <div className="flex-1 relative h-7 bg-slate-100 rounded overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 bg-gradient-to-r from-blue-500 to-blue-400 rounded transition-all duration-300"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="w-24 shrink-0 text-xs text-slate-500 text-left tabular-nums">
                {typeof row.value === 'number'
                  ? row.value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
                  : String(row.value)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 判断 TableData 是否适合显示简单柱状图 */
function getBarChartData(data: TableData): BarChartRow[] | null {
  if (data.columns.length !== 2) return null;
  if (data.rows.length === 0 || data.rows.length > 20) return null;

  const [dimCol, metricCol] = data.columns;
  const chartRows: BarChartRow[] = [];

  for (const row of data.rows) {
    const label = String(row[dimCol] ?? '');
    const rawVal = row[metricCol];
    const value = typeof rawVal === 'number' ? rawVal : parseFloat(String(rawVal ?? ''));
    if (isNaN(value)) return null; // 度量列含非数字，放弃
    chartRows.push({ label, value });
  }

  return chartRows;
}

// ─── TableResult ───────────────────────────────────────────────────────────────

interface TableResultProps {
  data?: TableData;
}

function TableResult({ data }: TableResultProps) {
  const [tableExpanded, setTableExpanded] = useState(false);

  if (!data) return null;

  const chartRows = getBarChartData(data);
  const showChart = chartRows !== null;

  const rows = data.rows.slice(0, 10);
  const truncated = data.rows.length > 10;

  const tableNode = (
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
      {truncated && (
        <div className="px-4 py-2 text-xs text-slate-400 bg-slate-50">
          共 {data.rows.length} 行，已截断显示前 10 行
        </div>
      )}
    </div>
  );

  if (showChart) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        {/* 柱状图 */}
        <SimpleBarChart
          rows={chartRows!}
          dimCol={data.columns[0]}
          metricCol={data.columns[1]}
        />
        {/* 可折叠的原始表格 */}
        {truncated && (
          <div className="px-4 py-2 text-xs text-slate-400 bg-slate-50 border-t border-slate-100">
            共 {data.rows.length} 行，已截断显示前 10 行
          </div>
        )}
        <div className="border-t border-slate-100">
          <button
            onClick={() => setTableExpanded((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-2 text-xs text-slate-400
                       hover:text-slate-600 hover:bg-slate-50 transition-colors"
          >
            <span>查看原始数据</span>
            <i className={`ri-arrow-${tableExpanded ? 'up' : 'down'}-s-line`} />
          </button>
          {tableExpanded && tableNode}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      {tableNode}
    </div>
  );
}

// ─── TextAnswer ──────────────────────────────────────────────────────────────

const textAnswerComponents: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '');
    const codeContent = String(children).replace(/\n$/, '');
    if (match) {
      return (
        <SyntaxHighlighter
          style={oneLight}
          language={match[1]}
          PreTag="div"
          className="!rounded-lg !text-sm my-3"
        >
          {codeContent}
        </SyntaxHighlighter>
      );
    }
    return (
      <code
        className="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-xs font-mono"
        {...props}
      >
        {children}
      </code>
    );
  },
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-700 underline">
        {children}
      </a>
    );
  },
  table({ children }) {
    return (
      <div className="overflow-x-auto my-3">
        <table className="min-w-full border-collapse border border-slate-200 text-sm">
          {children}
        </table>
      </div>
    );
  },
  th({ children }) {
    return <th className="border border-slate-200 bg-slate-50 px-3 py-2 text-left font-medium text-slate-700">{children}</th>;
  },
  td({ children }) {
    return <td className="border border-slate-200 px-3 py-2 text-slate-600">{children}</td>;
  },
};

interface TextAnswerProps {
  answer: string;
}

function TextAnswer({ answer }: TextAnswerProps) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6">
      <div className="prose prose-sm max-w-none prose-slate text-slate-700">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={textAnswerComponents}>
          {answer}
        </ReactMarkdown>
      </div>
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
  NLQ_012: { title: '暂无可用数据源', hint: '请先在设置中配置数据连接' },
  SYS_001: { title: '服务器内部错误', hint: '请稍后重试，如问题持续请联系管理员' },
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
