/**
 * AskBar — 问题输入栏
 *
 * P1 变更：
 * - 新增连接选择下拉框（GET /api/tableau/connections，active 列表）
 * - 只有 > 1 个连接时显示下拉框
 * - 提交时将 connection_id 附在请求体
 * - 支持 data-askbar-input 属性，供全局 Cmd+K 聚焦
 * - 右侧快捷键提示 ⌘K
 * - Escape 键清空输入
 *
 * Open-WebUI 风格改造：
 * - Auto-grow textarea（最高 200px）
 * - mockStreamAskData 流式接入
 */
import { useState, useEffect, useRef, forwardRef, memo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { SearchAnswer } from '../../../api/search';
import { useScope } from '../context/ScopeContext';
import { mockStreamAskData, streamAskData } from '../../../api/ask_data_contract';

const MAX_LENGTH = 500;

interface AskBarProps {
  onResult: (result: SearchAnswer) => void;
  onError: (err: { code: string; message: string }) => void;
  onLoading: (loading: boolean) => void;
  /** 可选：每次输入变化时回调当前问题文本（用于父组件记录 lastQuestion） */
  onQuestionChange?: (question: string) => void;
  /** 预置问题（由 SuggestionGrid 传入）*/
  initialQuestion?: string;
  /** 关联的 conversation_id（追问时使用） */
  conversationId?: string | null;
  /**
   * 外部连接 ID（来自 ScopeContext / ScopePicker）。
   * 有值时：隐藏内部连接下拉，提交时使用此值。
   * 为 undefined 或 null 时：保持原有内部下拉行为。
   */
  connectionId?: string | null;
  /** 流式进行中时为 true，用于显示停止按钮 */
  isStreaming?: boolean;
  /** 停止流式的回调 */
  onAbort?: () => void;
  /** 默认 true，后端就绪后传 false */
  useMock?: boolean;
  /** 每个 token 到达时回调父层 */
  onStreamToken?: (token: string) => void;
}

const AskBarBase = forwardRef<HTMLTextAreaElement, AskBarProps>(
  function AskBar(
    {
      onResult,
      onError,
      onLoading,
      onQuestionChange,
      conversationId,
      connectionId: externalConnectionId,
      isStreaming,
      onAbort,
      useMock = false,
      onStreamToken,
    },
    ref
  ) {
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [noConnectionHint, setNoConnectionHint] = useState(false);
    const [searchParams] = useSearchParams();

    const scopeContext = useScope();
    const noConnection = !scopeContext.connectionsLoading && scopeContext.connections.length === 0;
    const connectionUnavailable = scopeContext.connectionsLoading || noConnection;

    // B24: Support ?prefill= URL parameter to pre-fill the question input
    useEffect(() => {
      const prefill = searchParams.get('prefill');
      if (prefill) {
        const decoded = decodeURIComponent(prefill);
        setInput(decoded);
        onQuestionChange?.(decoded);
      }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const internalRef = useRef<HTMLTextAreaElement>(null);
    const textareaRef = (ref as React.RefObject<HTMLTextAreaElement>) ?? internalRef;
    const abortRef = useRef<(() => void) | null>(null);

    // Auto-grow textarea
    useEffect(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 200) + 'px';
    }, [input, textareaRef]);

    // Escape 键清空输入
    useEffect(() => {
      const handler = (e: KeyboardEvent) => {
        if (e.key === 'Escape' && document.activeElement === textareaRef.current) {
          setInput('');
          onQuestionChange?.('');
        }
      };
      document.addEventListener('keydown', handler);
      return () => document.removeEventListener('keydown', handler);
    }, [onQuestionChange, textareaRef]);

    const prevIsStreamingRef = useRef(false);
    useEffect(() => {
      if (!useMock && prevIsStreamingRef.current && !isStreaming) {
        setLoading(false);
        onLoading(false);
      }
      prevIsStreamingRef.current = isStreaming ?? false;
    }, [isStreaming, useMock, onLoading]);

    const effectiveConnectionId = externalConnectionId != null
      ? (externalConnectionId ? Number(externalConnectionId) : null)
      : (scopeContext.connectionId ? Number(scopeContext.connectionId) : null);

    const submit = () => {
      if (!input.trim() || loading) return;
      if (scopeContext.connectionsLoading) return;
      if (noConnection) {
        setNoConnectionHint(true);
        return;
      }

      setLoading(true);
      const question = input.trim().slice(0, MAX_LENGTH);
      onQuestionChange?.(question);
      onLoading(true);
      setInput('');

      // 非 mock 路径：委托给父层 useStreamingChat，不自己发起 SSE 流
      if (!useMock) {
        return;
      }

      const streamFn = useMock ? mockStreamAskData : streamAskData;
      const abort = streamFn(
        {
          q: question,
          connection_id: effectiveConnectionId ?? undefined,
          conversation_id: conversationId ?? undefined,
        },
        (event) => {
          if (event.type === 'token') {
            onStreamToken?.(event.content);
          } else if (event.type === 'done') {
            onResult({ answer: event.answer, type: 'text', trace_id: event.trace_id });
            setLoading(false);
            onLoading(false);
          } else if (event.type === 'error') {
            onError({ code: event.code, message: event.message });
            setLoading(false);
            onLoading(false);
          }
        }
      );
      abortRef.current = abort;
    };

    const handleAbort = () => {
      abortRef.current?.();
      abortRef.current = null;
      setLoading(false);
      onLoading(false);
      onAbort?.();
    };

    const canSubmit = input.trim().length > 0 && !loading && !connectionUnavailable;

    return (
      <div
        className={[
          'w-full rounded-2xl border border-slate-200/70 bg-white shadow-sm',
          'focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20 focus-within:shadow-md',
          'transition-all duration-200',
        ].join(' ')}
      >
        {/* 顶部连接状态栏 */}
        <div className="flex items-center px-4 pt-2.5 pb-0 gap-2">
          {scopeContext.connectionsLoading && (
            <span className="text-xs text-slate-400 flex items-center gap-1">
              <i className="ri-loader-2-line animate-spin" />
              连接加载中…
            </span>
          )}

          {noConnection && (
            <span className="text-xs text-amber-600 flex items-center gap-1">
              <i className="ri-database-2-line" />
              暂无数据连接
            </span>
          )}

          {!scopeContext.connectionsLoading && scopeContext.connections.length === 1 && (
            <span className="text-xs text-slate-500 flex items-center gap-1.5">
              <i className="ri-database-2-line text-slate-400" />
              <span className="truncate">{scopeContext.connections[0].name}</span>
            </span>
          )}

          {!scopeContext.connectionsLoading && scopeContext.connections.length > 1 && (
            <div className="flex items-center gap-1.5">
              <i className="ri-database-2-line text-xs text-slate-400" />
              <select
                value={scopeContext.connectionId ?? ''}
                onChange={(e) => scopeContext.setConnectionId(e.target.value || null)}
                className="text-xs text-slate-600 bg-gray-100 rounded-full px-2.5 py-1
                           border-none outline-none cursor-pointer hover:bg-gray-200 transition-colors"
                disabled={scopeContext.connectionsLoading}
              >
                {scopeContext.connections.map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* 无连接时的提示链接 */}
          {noConnection && (
            <Link
              to="/system/mcp-configs"
              className="text-xs text-blue-600 hover:text-blue-700 hover:underline ml-auto"
            >
              前往添加连接
            </Link>
          )}
        </div>

        {/* 第二行：输入框 + 发送按钮并排 */}
        <div className="flex items-end px-4 pb-2.5 gap-2">
          <textarea
            ref={textareaRef}
            data-askbar-input
            aria-label="输入你的数据问题"
            value={input}
            onChange={(e) => {
              const val = e.target.value.slice(0, MAX_LENGTH);
              setInput(val);
              onQuestionChange?.(val);
              setNoConnectionHint(false);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="向木兰提问…  ⌘K 聚焦"
            disabled={loading}
            rows={1}
            style={{ minHeight: '28px', maxHeight: '120px' }}
            className="flex-1 bg-transparent text-sm text-slate-800
                       placeholder:text-slate-400/70 focus:outline-none resize-none
                       overflow-y-auto leading-relaxed py-1"
          />

          {noConnectionHint && (
            <span className="text-xs text-amber-600 self-center shrink-0">
              请先
              <Link to="/system/mcp-configs" className="underline hover:text-amber-700">
                添加连接
              </Link>
            </span>
          )}

          {isStreaming ? (
            <button
              onClick={handleAbort}
              className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center
                         bg-blue-700 hover:bg-blue-800 text-white transition-colors"
              aria-label="停止"
            >
              <i className="ri-stop-circle-line text-base" />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!canSubmit}
              className={[
                'shrink-0 w-9 h-9 rounded-full flex items-center justify-center transition-all duration-200 self-end mb-0.5',
                canSubmit
                  ? 'bg-blue-700 hover:bg-blue-800 text-white hover:shadow-md active:scale-95'
                  : 'bg-slate-100 text-slate-300 cursor-not-allowed',
              ].join(' ')}
              aria-label="发送"
            >
              {loading ? (
                <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <i className="ri-send-plane-fill text-base" />
              )}
            </button>
          )}
        </div>
      </div>
    );
  }
);

export default memo(AskBarBase);
