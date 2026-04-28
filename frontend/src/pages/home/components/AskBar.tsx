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
 * - 文件附件（paperclip 按钮 + chips 预览）
 * - DragDropOverlay（拖拽上传，dragCounter 避免闪烁）
 * - mockStreamAskData 流式接入
 */
import { useState, useEffect, useRef, forwardRef, memo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { SearchAnswer } from '../../../api/search';
import { listConnections, type TableauConnection } from '../../../api/tableau';
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
      useMock = true,
      onStreamToken,
    },
    ref
  ) {
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [connections, setConnections] = useState<TableauConnection[]>([]);
    const [selectedConnectionId, setSelectedConnectionId] = useState<number | null>(null);
    const [noConnectionHint, setNoConnectionHint] = useState(false);
    const [files, setFiles] = useState<File[]>([]);
    const [isDragging, setIsDragging] = useState(false);
    const [searchParams] = useSearchParams();

    const { connections: scopeConnections, connectionsLoading } = useScope();
    const noConnection = !connectionsLoading && scopeConnections.length === 0;

    // B24: Support ?prefill= URL parameter to pre-fill the question input
    useEffect(() => {
      const prefill = searchParams.get('prefill');
      if (prefill) {
        const decoded = decodeURIComponent(prefill);
        setInput(decoded);
        onQuestionChange?.(decoded);
      }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const useExternalConnection = externalConnectionId != null;

    const internalRef = useRef<HTMLTextAreaElement>(null);
    const textareaRef = (ref as React.RefObject<HTMLTextAreaElement>) ?? internalRef;
    const fileInputRef = useRef<HTMLInputElement>(null);
    const abortRef = useRef<(() => void) | null>(null);
    const dragCounterRef = useRef(0);

    useEffect(() => {
      if (useExternalConnection) return;
      listConnections()
        .then((res) => {
          const active = res.connections.filter((c) => c.is_active);
          setConnections(active);
          if (active.length > 0) setSelectedConnectionId(active[0].id);
        })
        .catch(() => {
          // 忽略：连接列表加载失败不影响问答
        });
    }, [useExternalConnection]);

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

    const effectiveConnectionId = useExternalConnection
      ? (externalConnectionId ? Number(externalConnectionId) : null)
      : selectedConnectionId;

    const submit = () => {
      if ((!input.trim() && files.length === 0) || loading) return;
      if (noConnection) {
        setNoConnectionHint(true);
        return;
      }

      setLoading(true);
      onLoading(true);
      const question = input.trim().slice(0, MAX_LENGTH);
      onQuestionChange?.(question);
      setInput('');
      setFiles([]);

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

    // DragDrop 处理，用 dragCounter 避免子元素穿越时闪烁
    const handleDragEnter = (e: React.DragEvent) => {
      e.preventDefault();
      dragCounterRef.current += 1;
      if (dragCounterRef.current === 1) setIsDragging(true);
    };

    const handleDragLeave = (e: React.DragEvent) => {
      e.preventDefault();
      dragCounterRef.current -= 1;
      if (dragCounterRef.current === 0) setIsDragging(false);
    };

    const handleDragOver = (e: React.DragEvent) => {
      e.preventDefault();
    };

    const handleDrop = (e: React.DragEvent) => {
      e.preventDefault();
      dragCounterRef.current = 0;
      setIsDragging(false);
      const dropped = Array.from(e.dataTransfer.files);
      if (dropped.length > 0) {
        setFiles((prev) => [...prev, ...dropped]);
      }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!e.target.files) return;
      const selected = Array.from(e.target.files);
      setFiles((prev) => [...prev, ...selected]);
      e.target.value = '';
    };

    const removeFile = (index: number) => {
      setFiles((prev) => prev.filter((_, i) => i !== index));
    };

    const showConnectionSelect = !useExternalConnection && connections.length > 1;
    const canSubmit = (input.trim().length > 0 || files.length > 0) && !loading;

    return (
      <>
        <div
          className="relative rounded-3xl border border-slate-200/70 bg-white/80 backdrop-blur-sm shadow-md px-3 py-3 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20 focus-within:shadow-lg transition-shadow"
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          {/* DragDrop 遮罩 */}
          <div
            aria-hidden="true"
            className="absolute inset-0 rounded-3xl bg-blue-500/20 border-2 border-blue-400 pointer-events-none z-20 flex items-center justify-center"
            style={{
              opacity: isDragging ? 1 : 0,
              transition: isDragging
                ? 'opacity 150ms ease-out'
                : 'opacity 100ms ease-in',
            }}
          >
            <span className="text-blue-600 text-sm font-medium select-none">
              释放以添加文件
            </span>
          </div>

          {/* 文件 chips 预览区 */}
          {files.length > 0 && (
            <div className="flex flex-wrap gap-2 px-4 pt-2 pb-1">
              {files.map((file, i) => (
                <div
                  key={i}
                  className="relative flex items-center gap-1.5 bg-slate-100 rounded-lg px-2 py-1 text-xs text-slate-700"
                >
                  {file.type.startsWith('image/') ? (
                    <img
                      src={URL.createObjectURL(file)}
                      alt={file.name}
                      className="w-16 h-16 object-cover rounded"
                    />
                  ) : (
                    <span className="max-w-[120px] truncate">
                      {file.name}
                      <span className="ml-1 text-slate-400">
                        ({(file.size / 1024).toFixed(1)}KB)
                      </span>
                    </span>
                  )}
                  <button
                    onClick={() => removeFile(i)}
                    className="ml-1 text-slate-400 hover:text-slate-600 transition-colors"
                    aria-label={`移除 ${file.name}`}
                  >
                    <i className="ri-close-line text-xs" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 连接选择器（多连接时，左下角 inline） */}
          {showConnectionSelect && (
            <div className="absolute left-5 bottom-4 z-10">
              <select
                value={selectedConnectionId ?? ''}
                onChange={(e) => setSelectedConnectionId(Number(e.target.value))}
                className="text-xs text-slate-400 bg-slate-50 border border-slate-200 rounded-md
                           px-1.5 py-0.5 focus:outline-none focus:border-blue-300 max-w-[120px]"
              >
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          )}

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
            placeholder={noConnection ? '请先添加连接，再开始提问' : '向木兰提问…'}
            disabled={loading}
            style={{ minHeight: '56px', maxHeight: '200px', overflowY: 'auto' }}
            className={`w-full pr-20 py-3 bg-white text-slate-800 placeholder-slate-400
                       focus:outline-none text-sm resize-none overflow-y-auto leading-relaxed rounded-xl
                       ${showConnectionSelect ? 'pl-36 px-4' : 'px-4'}`}
          />

          {/* 左下角：paperclip 按钮 */}
          <div className="absolute left-4 bottom-4 z-10 flex items-center gap-1">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="p-1.5 text-slate-400 hover:text-slate-600 transition-colors"
              aria-label="添加附件"
            >
              <i className="ri-attachment-2 text-base" />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileChange}
            />
          </div>

          {/* 快捷键提示 */}
          <span
            className="absolute right-14 bottom-4 text-[10px] text-slate-300 select-none pointer-events-none"
            style={{ color: '#cbd5e1' }}
          >
            ⌘K
          </span>

          {isStreaming ? (
            <button
              onClick={handleAbort}
              className="absolute right-4 top-1/2 -translate-y-1/2 p-2.5 bg-blue-700
                         hover:bg-blue-800 text-white rounded-lg transition-colors"
              aria-label="停止"
            >
              <i className="ri-stop-circle-line text-base" />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!canSubmit}
              className="absolute right-4 top-1/2 -translate-y-1/2 p-2.5 bg-blue-700
                         hover:bg-blue-800 disabled:bg-slate-100 disabled:text-slate-300 text-white rounded-lg transition-colors"
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

        {noConnectionHint && (
          <p className="mt-1.5 text-xs text-amber-600">
            尚未配置数据连接，请先
            <Link to="/system/mcp-configs" className="underline hover:text-amber-700">
              前往添加
            </Link>
            。
          </p>
        )}
      </>
    );
  }
);

export default memo(AskBarBase);
