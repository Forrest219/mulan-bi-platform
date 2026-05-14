/**
 * MessageBubble — 带 Markdown 渲染的消息气泡（Gap-04）
 *
 * - user 消息：右对齐，蓝底白字，whitespace-pre-wrap 纯文本
 * - assistant 消息：左对齐，全宽白卡，react-markdown + remark-gfm 渲染
 *   - 代码块：react-syntax-highlighter (oneLight) + 一键复制
 *   - 表格：横向滚动容器包裹
 *   - 链接：新标签打开
 *   - 简单无序列表：自动渲染为资产卡片 Grid
 *   - isStreaming：末尾打字光标动画
 *   - 引用源：泡泡内底部脚注
 */
import React, { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Components } from 'react-markdown';
import ThinkingBlock from '../../pages/home/components/ThinkingBlock';
import AnalysisProcessBlock from '../../pages/home/components/AnalysisProcessBlock';
import QueryResultTable from './QueryResultTable';
import QueryResultChart from './QueryResultChart';
import type { TableData, ChartData } from '../../hooks/useStreamingChat';
import type { AgentExplainability } from '../../api/agent';
import { searchAssets } from '../../api/tableau';


// ─── CodeBlock ────────────────────────────────────────────────────────────────

interface CodeBlockProps {
  language: string;
  children: string;
}

function CodeBlock({ language, children }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [children]);

  return (
    <div className="relative group my-3">
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity
                   px-2 py-1 text-xs bg-slate-200 hover:bg-slate-300 text-slate-700 rounded"
      >
        {copied ? '已复制' : '复制'}
      </button>
      <SyntaxHighlighter
        style={oneLight}
        language={language || 'text'}
        PreTag="div"
        className="!rounded-lg !text-sm"
      >
        {children}
      </SyntaxHighlighter>
    </div>
  );
}

// ─── Asset Card Grid（简单无序列表 → 卡片） ────────────────────────────────────

function getTextFromNode(node: React.ReactNode): string {
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(getTextFromNode).join('');
  if (React.isValidElement(node)) {
    return getTextFromNode((node.props as { children?: React.ReactNode }).children);
  }
  return '';
}

function getUrlFromNode(node: React.ReactNode): string | undefined {
  if (React.isValidElement(node)) {
    const p = node.props as { href?: string; children?: React.ReactNode };
    if (p.href) return p.href;
    return getUrlFromNode(p.children);
  }
  if (Array.isArray(node)) {
    for (const child of node) {
      const url = getUrlFromNode(child);
      if (url) return url;
    }
  }
  return undefined;
}

interface AssetCardItem { text: string; url?: string }

function AssetCardGrid({ items }: { items: AssetCardItem[] }) {
  const navigate = useNavigate();
  const [loadingIdx, setLoadingIdx] = useState<number | null>(null);

  const handleClick = useCallback(async (item: AssetCardItem, idx: number) => {
    if (item.url) {
      window.open(item.url, '_blank', 'noopener,noreferrer');
      return;
    }
    setLoadingIdx(idx);
    try {
      const result = await searchAssets({ q: item.text, page_size: 1 });
      const asset = result.assets[0];
      if (asset?.web_url) {
        window.open(asset.web_url, '_blank', 'noopener,noreferrer');
      } else if (asset?.content_url && asset.server_url) {
        const sitePart = asset.site ? `/site/${asset.site}` : '';
        window.open(`${asset.server_url}/#${sitePart}${asset.content_url}`, '_blank', 'noopener,noreferrer');
      } else {
        navigate(`/assets/tableau?q=${encodeURIComponent(item.text)}`);
      }
    } catch {
      navigate(`/assets/tableau?q=${encodeURIComponent(item.text)}`);
    } finally {
      setLoadingIdx(null);
    }
  }, [navigate]);

  return (
    <ul className="my-3 space-y-1.5 not-prose">
      {items.map((item, i) => (
        <li
          key={i}
          onClick={() => handleClick(item, i)}
          className="flex items-center gap-2 px-3 py-2 bg-slate-50 border border-slate-100 rounded-lg
                     hover:bg-blue-50 hover:border-blue-100 cursor-pointer transition-all duration-150 text-xs text-slate-600"
        >
          {loadingIdx === i ? (
            <i className="ri-loader-4-line animate-spin text-blue-400 flex-shrink-0 text-[11px]" />
          ) : (
            <i className="ri-bookmark-line text-slate-400 group-hover:text-blue-500 flex-shrink-0 text-[11px]" />
          )}
          <span className="flex-1 leading-tight break-all">{item.text}</span>
          <span className="text-[10px] text-blue-400 whitespace-nowrap ml-2">
            {loadingIdx === i ? '查询中' : '查看'}
          </span>
        </li>
      ))}
    </ul>
  );
}

// ─── MarkdownComponents ───────────────────────────────────────────────────────

const markdownComponents: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '');
    const codeContent = String(children).replace(/\n$/, '');

    if (match) {
      return <CodeBlock language={match[1]}>{codeContent}</CodeBlock>;
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
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 hover:text-blue-700 underline"
      >
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

  thead({ children }) {
    return <thead className="bg-slate-100">{children}</thead>;
  },

  tr({ children }) {
    return (
      <tr className="border-b border-slate-100 even:bg-slate-50 odd:bg-white last:border-0">
        {children}
      </tr>
    );
  },

  th({ children }) {
    return (
      <th className="border border-slate-200 bg-slate-50 px-3 py-2 text-left font-medium text-slate-700">
        {children}
      </th>
    );
  },

  td({ children }) {
    return (
      <td className="border border-slate-200 px-3 py-2 text-slate-600">
        {children}
      </td>
    );
  },

  ul({ children }) {
    const items = React.Children.toArray(children).filter(
      (c): c is React.ReactElement => React.isValidElement(c) && c.type === 'li'
    );

    if (items.length >= 2 && items.length <= 15) {
      const cardItems = items.map(item => ({
        text: getTextFromNode(item).trim(),
        url: getUrlFromNode((item.props as { children?: React.ReactNode }).children),
      }));
      const isSimpleList = cardItems.every(
        ({ text }) => text.length > 0 && text.length <= 80 && !text.includes('\n')
      );
      if (isSimpleList) {
        return <AssetCardGrid items={cardItems} />;
      }
    }

    return <ul className="list-disc pl-5 my-2 space-y-1 text-slate-700">{children}</ul>;
  },
};

// ─── parseThought ─────────────────────────────────────────────────────────────

function parseThought(content: string): { thought: string | null; body: string } {
  const match = content.match(/^<Thought>([\s\S]*?)<\/Thought>\s*([\s\S]*)$/);
  if (!match) return { thought: null, body: content };
  return { thought: match[1], body: match[2] };
}

// ─── SourceFootnote ───────────────────────────────────────────────────────────

interface SourceFootnoteProps {
  sourcesCount: number;
  topSources: string[];
  onSourceClick?: (sourceName: string) => void;
}

function SourceFootnote({ sourcesCount, topSources, onSourceClick }: SourceFootnoteProps) {
  const handleSourceClick = (name: string) => {
    console.log('Open DataSource Drawer:', name);
    onSourceClick?.(name);
  };
  return (
    <div className="mt-4 pt-3 border-t border-slate-100">
      <div className="flex items-center gap-1.5 flex-wrap">
        <i className="ri-database-2-line text-[10px] text-slate-400" />
        <span className="text-[10px] text-slate-400">
          基于 <strong className="text-slate-500 font-medium">{sourcesCount}</strong> 个数据源
        </span>
        {topSources.map(name => (
          <button
            key={name}
            onClick={() => handleSourceClick(name)}
            className="px-1.5 py-0.5 bg-slate-50 border border-slate-100 rounded text-[10px] text-blue-500 cursor-pointer hover:bg-blue-50 hover:border-blue-200 hover:text-blue-600 transition-colors"
          >
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── MessageBubble ────────────────────────────────────────────────────────────

export interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isError?: boolean;
  /** error_code from SSE error event — controls icon choice */
  errorCode?: string;
  /** user-readable hint from backend — shown as secondary text */
  errorHint?: string;
  /** ReAct reasoning text from SSE thinking event (Spec 29/30) */
  thinking?: string;
  /** Structured, sanitized analysis process. This is the primary P0 explainability UI. */
  explainability?: AgentExplainability;
  /** trace_id for feedback/rating (Spec 36 §5) */
  traceId?: string;
  /** Structured table data from table_data SSE event */
  tableData?: TableData;
  /** Structured chart data from chart_data SSE event */
  chartData?: ChartData;
  /** Source metadata — rendered as inline footnote inside assistant bubble */
  sourcesCount?: number;
  topSources?: string[];
  /** Callback when user clicks a source tag to open datasource drawer */
  onSourceClick?: (sourceName: string) => void;
}

export default function MessageBubble({
  role,
  content,
  isStreaming = false,
  isError = false,
  errorCode,
  errorHint,
  thinking,
  explainability,
  tableData,
  chartData,
  sourcesCount,
  topSources,
  onSourceClick,
}: MessageBubbleProps) {
  const isUser = role === 'user';

  function errorIcon(code: string | undefined): string {
    if (code === 'AGENT_001') return 'ri-timer-line';
    if (code === 'AGENT_003') return 'ri-tools-line';
    if (code === 'STREAM_ERROR') return 'ri-wifi-off-line';
    return 'ri-error-warning-line';
  }

  function errorLabel(code: string | undefined): string {
    if (code === 'AGENT_001') return '查询超时';
    if (code === 'AGENT_003') return '工具执行失败';
    if (code === 'STREAM_ERROR') return '连接中断，请重试';
    return '出现错误，请重试';
  }

  const hasSourceFootnote = !isStreaming && !isUser && !isError
    && sourcesCount != null && sourcesCount > 0
    && topSources && topSources.length > 0;

  return (
    <div className={`flex ${isUser ? 'flex-row-reverse' : 'justify-start'} mb-4 group`}>
      <div
        className={`${
          isUser
            ? 'self-end max-w-[72%]'
            : 'self-start w-full'
        } rounded-2xl px-4 py-3 text-sm ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-white border border-slate-200 text-slate-800 shadow-sm'
        }`}
      >
        {!isUser && (
          <div className="flex items-center gap-1 mb-2">
            <span className="w-5 h-5 rounded-full bg-slate-200 flex items-center justify-center">
              <i className="ri-robot-2-line text-[10px] text-slate-500" />
            </span>
            <span className="text-xs text-slate-400">木兰</span>
          </div>
        )}
        {isUser ? (
          <p className="whitespace-pre-wrap break-words">{content}</p>
        ) : isError ? (
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1 text-sm text-red-500 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
              <div className="flex items-center gap-2">
                <i className={`${errorIcon(errorCode)} flex-shrink-0`} />
                <span>{errorLabel(errorCode)}</span>
              </div>
              {errorHint && (
                <p className="text-xs text-red-400 ml-6 leading-relaxed">{errorHint}</p>
              )}
            </div>
            <AnalysisProcessBlock explainability={explainability} />
          </div>
        ) : isStreaming ? (
          <div className="prose prose-sm max-w-none prose-slate">
            <p className="whitespace-pre-wrap break-words leading-relaxed m-0">{content}</p>
            <span className="inline-block w-2 h-4 bg-slate-400 animate-pulse ml-0.5 align-middle rounded-sm" />
            <AnalysisProcessBlock explainability={explainability} isStreaming />
          </div>
        ) : (
          <div className="prose prose-sm max-w-none prose-slate">
            {(() => {
              const showThought = thinking ?? (parseThought(content).thought ?? null);
              const bodyText = thinking ? content : parseThought(content).body;
              return (
                <>
                  {showThought != null && <ThinkingBlock content={showThought} />}
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                    {bodyText}
                  </ReactMarkdown>
                  {tableData && <QueryResultTable data={tableData} />}
                  {chartData && <QueryResultChart data={chartData} />}
                  <AnalysisProcessBlock explainability={explainability} />
                  {hasSourceFootnote && (
                    <SourceFootnote sourcesCount={sourcesCount!} topSources={topSources!} onSourceClick={onSourceClick} />
                  )}
                </>
              );
            })()}
          </div>
        )}
      </div>
    </div>
  );
}
