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

// ─── MessageBubble ────────────────────────────────────────────────────────────

export interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
}

export default function MessageBubble({
  role,
  content,
  isStreaming = false,
}: MessageBubbleProps) {
  const isUser = role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm ${
          isUser
            ? 'bg-blue-700 text-white'
            : 'bg-white border border-slate-200 text-slate-800 shadow-sm'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap break-words">{content}</p>
        ) : (
          <div className="prose prose-sm max-w-none prose-slate">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {content}
            </ReactMarkdown>
            {isStreaming && (
              <span className="inline-block w-2 h-4 bg-slate-400 animate-pulse ml-0.5 align-middle rounded-sm" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
