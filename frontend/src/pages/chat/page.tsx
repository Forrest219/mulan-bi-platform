/**
 * ChatPage — /chat/:id
 *
 * 功能：
 * - 从路由参数取 conversation_id，调 conversationsApi.get(id) 加载消息历史
 * - 展示消息流：用户消息（右对齐）+ 助手回复（左对齐，含 SearchResult）
 * - 底部固定 AskBar，追问时调 POST /api/search/query（带 conversation_id）
 * - 加载态骨架屏；错误态提示"对话不存在"并返回首页
 * - 滚动到最新消息
 * - 右上角导出按钮（P2-3）
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Components } from 'react-markdown';
import { conversationsApi, type ConversationDetail, type ConversationMessageAPI } from '../../api/conversations';
import { askQuestion, type SearchAnswer } from '../../api/search';
import { SearchResult } from '../home/components/SearchResult';
import { DataUsedFooter } from '../home/components/DataUsedFooter';
import { useConversations } from '../../store/conversationStore';
import { listConnections, type TableauConnection } from '../../api/tableau';

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function MessageSkeleton() {
  return (
    <div className="space-y-6 py-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className={`flex ${i % 2 === 0 ? 'justify-end' : 'justify-start'}`}>
          <div className={`rounded-2xl px-4 py-3 space-y-2 ${i % 2 === 0 ? 'bg-blue-50 w-48' : 'bg-white border border-slate-200 w-64'}`}>
            <div className="h-3 bg-slate-200 animate-pulse rounded" />
            <div className="h-3 bg-slate-200 animate-pulse rounded w-3/4" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Markdown components for plain-text assistant messages ────────────────────

const plainTextComponents: Components = {
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

// ─── Assistant Message Content ────────────────────────────────────────────────

function AssistantMessageContent({ content, createdAt }: { content: string; createdAt: string }) {
  const parsed = useMemo(() => {
    try {
      const obj = JSON.parse(content);
      if (obj && typeof obj === 'object' && typeof obj.type === 'string') {
        return obj as SearchAnswer;
      }
    } catch (_err) {
      // ignore: assistant message may be plain text
    }
    return null;
  }, [content]);

  if (parsed) {
    return (
      <>
        <SearchResult result={parsed} onRetry={() => {}} />
        <DataUsedFooter result={parsed} timestamp={createdAt} />
      </>
    );
  }
  return (
    <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-md px-4 py-3">
      <div className="prose prose-sm max-w-none prose-slate text-slate-700">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={plainTextComponents}>
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}

// ─── Message Bubble ───────────────────────────────────────────────────────────

interface MessageBubbleProps {
  msg: ConversationMessageAPI;
}

function MessageBubble({ msg }: MessageBubbleProps) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[70%] bg-blue-600 text-white rounded-2xl rounded-tr-md px-4 py-3">
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
          <p className="text-[10px] text-blue-200 mt-1 text-right">
            {new Date(msg.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
          </p>
        </div>
      </div>
    );
  }

  // assistant
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] w-full">
        <div className="flex items-center gap-2 mb-1.5">
          <div className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center">
            <i className="ri-robot-line text-white text-xs" />
          </div>
          <span className="text-xs text-slate-400">Mulan AI</span>
        </div>
        <AssistantMessageContent content={msg.content} createdAt={msg.created_at} />
        <p className="text-[10px] text-slate-400 mt-1 ml-1">
          {new Date(msg.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>
    </div>
  );
}

// ─── Export helper ─────────────────────────────────────────────────────────────

function getAssistantExportText(content: string): string {
  try {
    const parsed = JSON.parse(content) as SearchAnswer;
    if (parsed && typeof parsed === 'object' && typeof parsed.type === 'string') {
      if (parsed.type === 'text') return parsed.answer;
      if (parsed.type === 'error') return `[错误] ${parsed.detail ?? parsed.reason ?? ''}`;
      return JSON.stringify(parsed.data ?? parsed.answer ?? '', null, 2);
    }
  } catch (_err) {
    // ignore: exported content may be plain text
  }
  return content;
}

function exportConversationMarkdown(conv: ConversationDetail) {
  const lines: string[] = [`# ${conv.title}`, '', `> 导出时间：${new Date().toLocaleString('zh-CN')}`, ''];
  for (const msg of conv.messages) {
    if (msg.role === 'user') {
      lines.push(`**You:** ${msg.content}`, '');
    } else {
      lines.push(`**Assistant:** ${getAssistantExportText(msg.content)}`, '');
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `conversation-${conv.id}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─── ChatPage ─────────────────────────────────────────────────────────────────

type ChatState =
  | 'CHAT_LOADING'
  | 'CHAT_READY'
  | 'CHAT_SENDING'
  | 'CHAT_APPEND_ERROR'
  | 'CHAT_NOT_FOUND'
  | 'CHAT_OFFLINE';

export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const { appendMessage } = useConversations();

  const [conv, setConv] = useState<ConversationDetail | null>(null);
  const [chatState, setChatState] = useState<ChatState>('CHAT_LOADING');
  const stateBeforeOfflineRef = useRef<ChatState>('CHAT_LOADING');

  const [input, setInput] = useState('');
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null);
  // P2-1：追问上下文标识（首次成功查询后置为 true）
  const [hasQueryContext, setHasQueryContext] = useState(false);
  // P2-1：缓存 datasource_luid，避免并发写入时后端读取 DB 出现竞态
  const [cachedDatasourceLuid, setCachedDatasourceLuid] = useState<string | undefined>(undefined);

  // 连接选择器（F-P1-4）
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [selectedConnectionId, setSelectedConnectionId] = useState<number | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 加载对话
  useEffect(() => {
    if (!id) return;
    setChatState('CHAT_LOADING');
    conversationsApi
      .get(id)
      .then(async (data) => {
        setConv(data);
        setChatState('CHAT_READY');
        // 初始化追问上下文状态：检查后端是否保存了查询上下文
        try {
          const ctxResp = await fetch(`/api/conversations/${id}/context`, { credentials: 'include' });
          if (ctxResp.ok) {
            const ctxData = await ctxResp.json();
            if (ctxData.context) {
              setHasQueryContext(true);
              if (ctxData.context.datasource_luid) {
                setCachedDatasourceLuid(ctxData.context.datasource_luid);
              }
            }
          }
        } catch (_err) {
          // ignore context bootstrap failures; chat can still work
        }
      })
      .catch(() => setChatState('CHAT_NOT_FOUND'));
  }, [id]);

  useEffect(() => {
    if (chatState !== 'CHAT_OFFLINE') {
      stateBeforeOfflineRef.current = chatState;
    }
  }, [chatState]);

  useEffect(() => {
    const handleOffline = () => setChatState('CHAT_OFFLINE');
    const handleOnline = () => setChatState(stateBeforeOfflineRef.current);

    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);

    if (!navigator.onLine) {
      handleOffline();
    }

    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, []);

  // 加载连接列表
  useEffect(() => {
    listConnections()
      .then((res) => {
        const active = res.connections.filter((c) => c.is_active);
        setConnections(active);
        if (active.length > 0) setSelectedConnectionId(active[0].id);
      })
      .catch(() => {});
  }, []);

  // 滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conv?.messages]);

  // Escape 键清空输入
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && document.activeElement === inputRef.current) {
        setInput('');
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  const handleSend = useCallback(async () => {
    if (
      !input.trim() ||
      chatState === 'CHAT_SENDING' ||
      chatState === 'CHAT_LOADING' ||
      chatState === 'CHAT_NOT_FOUND' ||
      chatState === 'CHAT_OFFLINE' ||
      !id
    ) {
      return;
    }
    const question = input.trim();
    setInput('');
    setChatState('CHAT_SENDING');
    setSendError(null);
    setLastFailedQuestion(null);

    // 乐观追加用户消息
    const userMsg: ConversationMessageAPI = {
      id: `local-${Date.now()}`,
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
    };
    setConv((prev) =>
      prev ? { ...prev, messages: [...prev.messages, userMsg] } : prev
    );
    appendMessage(id, { role: 'user', content: question });

    try {
      const result = await askQuestion({
        question,
        connection_id: selectedConnectionId ?? undefined,
        conversation_id: id,
        use_conversation_context: hasQueryContext,
        datasource_luid: hasQueryContext ? cachedDatasourceLuid : undefined,
      });

      const assistantPayload = JSON.stringify(result);

      const assistantMsg: ConversationMessageAPI = {
        id: `local-${Date.now()}-a`,
        role: 'assistant',
        content: assistantPayload,
        created_at: new Date().toISOString(),
      };
      setConv((prev) =>
        prev ? { ...prev, messages: [...prev.messages, assistantMsg] } : prev
      );
      appendMessage(id, { role: 'assistant', content: assistantPayload });
      // P2-1：标记已有上下文，下次追问自动继承
      if (result.type !== 'error' && result.type !== 'ambiguous') {
        setHasQueryContext(true);
        // 缓存 datasource_luid，防止并发写入竞态
        if (result.datasource_luid) {
          setCachedDatasourceLuid(result.datasource_luid);
        }
      }
      setChatState('CHAT_READY');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setSendError(msg);
      setLastFailedQuestion(question);
      setChatState('CHAT_APPEND_ERROR');
    }
  }, [
    appendMessage,
    cachedDatasourceLuid,
    chatState,
    hasQueryContext,
    id,
    input,
    selectedConnectionId,
  ]);

  // ── 错误态 ──────────────────────────────────────────────────────────────
  if (chatState === 'CHAT_NOT_FOUND') {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <i className="ri-chat-delete-line text-5xl text-slate-300 mb-4 block" />
          <h2 className="text-xl font-semibold text-slate-700 mb-2">对话不存在</h2>
          <p className="text-slate-500 mb-6">该对话已被删除或不存在</p>
          <Link
            to="/"
            className="inline-block px-4 py-2 bg-slate-900 text-white text-sm rounded-lg hover:bg-slate-800 transition-colors"
          >
            返回首页
          </Link>
        </div>
      </div>
    );
  }

  // ── 加载态 ──────────────────────────────────────────────────────────────
  if (chatState === 'CHAT_LOADING') {
    return (
      <div className="min-h-screen flex flex-col">
        <div className="flex items-center gap-3 px-6 py-4 border-b border-slate-200 bg-white">
          <div className="h-5 w-40 bg-slate-200 animate-pulse rounded" />
        </div>
        <div className="flex-1 max-w-3xl mx-auto w-full px-6">
          <MessageSkeleton />
        </div>
      </div>
    );
  }

  const showConnectionSelect = connections.length > 1;

  return (
    <div className="flex flex-col min-h-screen">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-3">
        <Link
          to="/"
          className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-slate-100 transition-colors text-slate-500"
          aria-label="返回首页"
        >
          <i className="ri-arrow-left-line text-base" />
        </Link>
        <h1 className="flex-1 font-medium text-slate-800 truncate">
          {conv?.title ?? '对话详情'}
        </h1>
        {/* 导出按钮（P2-3） */}
        {conv && (
          <button
            onClick={() => exportConversationMarkdown(conv)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-500 hover:text-slate-700
                       hover:bg-slate-100 rounded-lg transition-colors"
            title="导出为 Markdown"
          >
            <i className="ri-download-2-line text-base" />
            导出
          </button>
        )}
      </div>

      {chatState === 'CHAT_OFFLINE' && (
        <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-sm text-amber-700">
          当前离线中，无法发送消息。
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">
          {conv?.messages.length === 0 && (
            <div className="text-center py-12 text-slate-400 text-sm">
              暂无消息，在下方输入框开始对话
            </div>
          )}
          {conv?.messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          {chatState === 'CHAT_SENDING' && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 px-4 py-3 bg-white border border-slate-200 rounded-2xl rounded-tl-md">
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
                <span className="text-xs text-slate-400">AI 正在思考...</span>
              </div>
            </div>
          )}
          {chatState === 'CHAT_APPEND_ERROR' && sendError && (
            <div className="flex justify-center">
              <div className="px-4 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600 flex items-center gap-3">
                <span>发送失败：{sendError}</span>
                {lastFailedQuestion && (
                  <button
                    type="button"
                    onClick={() => {
                      setInput(lastFailedQuestion);
                      setChatState('CHAT_READY');
                    }}
                    className="text-red-700 hover:text-red-800 underline"
                  >
                    重试
                  </button>
                )}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* AskBar（底部固定） */}
      <div className="sticky bottom-0 bg-white border-t border-slate-200 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          {/* P2-1：追问上下文提示 */}
          {hasQueryContext && (
            <div className="flex items-center gap-1.5 mb-2 text-xs text-blue-500">
              <i className="ri-link text-blue-400" />
              继续追问，已关联上次数据源
            </div>
          )}
          <div className="relative">
            {/* 连接选择器（多连接时显示） */}
            {showConnectionSelect && (
              <div className="absolute left-3 bottom-3 z-10">
                <select
                  value={selectedConnectionId ?? ''}
                  onChange={(e) => setSelectedConnectionId(Number(e.target.value))}
                  className="text-xs text-slate-500 bg-transparent border border-slate-200 rounded-md px-1.5 py-0.5 focus:outline-none focus:border-blue-300"
                >
                  {connections.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            )}
            <textarea
              ref={inputRef}
              data-askbar-input
              aria-label="输入你的数据问题"
              value={input}
              onChange={(e) => setInput(e.target.value.slice(0, 500))}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="追问... (Enter 发送，Shift+Enter 换行)"
              rows={2}
              className={`w-full px-4 pr-16 py-3 bg-white border border-slate-200 rounded-xl
                         text-sm resize-none focus:outline-none focus:border-blue-300
                         placeholder-slate-400
                         ${showConnectionSelect ? 'pl-32' : ''}`}
            />
            {/* 快捷键提示 */}
            <span className="absolute right-12 bottom-3.5 text-[10px] text-slate-300 select-none">
              ⌘K
            </span>
            <button
              onClick={handleSend}
              disabled={chatState === 'CHAT_SENDING' || !input.trim() || chatState === 'CHAT_OFFLINE'}
              className="absolute right-3 top-1/2 -translate-y-1/2 w-8 h-8 bg-slate-900
                         hover:bg-slate-800 disabled:opacity-40 text-white rounded-lg
                         flex items-center justify-center transition-colors"
              aria-label="发送"
            >
              {chatState === 'CHAT_SENDING' ? (
                <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <i className="ri-send-plane-fill text-sm" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
