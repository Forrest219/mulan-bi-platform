/**
 * MessageBubble — 带 Markdown 渲染的消息气泡（Gap-04）
 *
 * - user 消息：右对齐，蓝底白字，whitespace-pre-wrap 纯文本
 * - assistant 消息：左对齐，白底，react-markdown + remark-gfm 渲染
 *   - 代码块：react-syntax-highlighter (oneLight) + 一键复制
 *   - 表格：横向滚动容器包裹
 *   - 链接：新标签打开
 *   - isStreaming：末尾打字光标动画
 */
import React, { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Components } from 'react-markdown';
import ThinkingBlock from '../../pages/home/components/ThinkingBlock';

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

// ─── MarkdownComponents ───────────────────────────────────────────────────────

const markdownComponents: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '');
    const codeContent = String(children).replace(/\n$/, '');

    if (match) {
      // 围栏代码块（有语言标识）
      return <CodeBlock language={match[1]}>{codeContent}</CodeBlock>;
    }
    // 行内代码
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
};

// ─── parseThought ─────────────────────────────────────────────────────────────

function parseThought(content: string): { thought: string | null; body: string } {
  const match = content.match(/^<Thought>([\s\S]*?)<\/Thought>\s*([\s\S]*)$/);
  if (!match) return { thought: null, body: content };
  return { thought: match[1], body: match[2] };
}

// ─── MessageBubble ────────────────────────────────────────────────────────────

export interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isError?: boolean;
  /** ReAct reasoning text from SSE thinking event (Spec 29/30) */
  thinking?: string;
  /** trace_id for feedback/rating (Spec 36 §5) */
  traceId?: string;
  /** Tool calls made during this message (Spec 29/30 §5) */
  toolCalls?: Array<{ tool: string; params: Record<string, unknown> }>;
  /** Tool results from this message (Spec 29/30 §5) */
  toolResults?: Array<{ tool: string; summary: string }>;
}

export default function MessageBubble({
  role,
  content,
  isStreaming = false,
  isError = false,
  thinking,
  traceId: _traceId,
  toolCalls: _toolCalls,
  toolResults: _toolResults,
}: MessageBubbleProps) {
  const isUser = role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-white border border-slate-200 text-slate-800 shadow-sm'
        }`}
      >
        {!isUser && (
          <div className="flex items-center gap-1 mb-1">
            <span className="w-5 h-5 rounded-full bg-slate-200 flex items-center justify-center">
              <i className="ri-robot-2-line text-[10px] text-slate-500" />
            </span>
            <span className="text-xs text-slate-400">木兰</span>
          </div>
        )}
        {isUser ? (
          <p className="whitespace-pre-wrap break-words">{content}</p>
        ) : isError ? (
          <div className="flex items-center gap-2 text-sm text-red-500 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
            <i className="ri-wifi-off-line" />
            <span>连接中断，请重试。</span>
          </div>
        ) : isStreaming ? (
          <div className="prose prose-sm max-w-none prose-slate">
            <p className="whitespace-pre-wrap break-words leading-relaxed m-0">{content}</p>
            <span className="inline-block w-2 h-4 bg-slate-400 animate-pulse ml-0.5 align-middle rounded-sm" />
          </div>
        ) : (
          <div className="prose prose-sm max-w-none prose-slate">
            {(() => {
              // Prefer SSE-provided thinking over content parsing (Spec 29/30)
              const showThought = thinking ?? (parseThought(content).thought ?? null);
              const bodyText = thinking ? content : parseThought(content).body;
              return (
                <>
                  {showThought != null && <ThinkingBlock content={showThought} />}
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                    {bodyText}
                  </ReactMarkdown>
                </>
              );
            })()}
          </div>
        )}
      </div>
    </div>
  );
}
