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
 */
import { useState, useEffect, useRef, forwardRef, memo } from 'react';
import { Link } from 'react-router-dom';
import type { SearchAnswer, AskQuestionRequest } from '../../../api/search';
import { listConnections, type TableauConnection } from '../../../api/tableau';
import { useScope } from '../context/ScopeContext';

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
}

// memo 包裹：Gap-05 §11 陷阱6 — streaming content state 在父层，AskBar 不应因 token 到达而重渲染
// forwardRef + memo 组合：先用 forwardRef 定义，再用 memo 导出
const AskBarBase = forwardRef<HTMLTextAreaElement, AskBarProps>(
  function AskBar({ onResult, onError, onLoading, onQuestionChange, conversationId, connectionId: externalConnectionId, isStreaming, onAbort }, ref) {
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [connections, setConnections] = useState<TableauConnection[]>([]);
    const [selectedConnectionId, setSelectedConnectionId] = useState<number | null>(null);
    const [noConnectionHint, setNoConnectionHint] = useState(false);

    // 从 ScopeContext 获取连接状态，用于 noConnection 判断
    const { connections: scopeConnections, connectionsLoading } = useScope();
    const noConnection = !connectionsLoading && scopeConnections.length === 0;

    // 当外部 connectionId 有值时，不使用内部下拉
    const useExternalConnection = externalConnectionId != null;

    const internalRef = useRef<HTMLTextAreaElement>(null);
    const textareaRef = (ref as React.RefObject<HTMLTextAreaElement>) ?? internalRef;

    // 加载连接列表（仅在无外部 connectionId 时加载内部下拉所需数据）
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

    // Escape 键清空输入（当 textarea 获取焦点时）
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

    const submit = async () => {
      if (!input.trim() || loading) return;
      if (noConnection) {
        // 无连接时不发请求，显示 inline 提示
        setNoConnectionHint(true);
        return;
      }
      const question = input.trim().slice(0, MAX_LENGTH);
      onQuestionChange?.(question);
      setInput('');
      setLoading(true);
      onLoading(true);
      try {
        const { askQuestion } = await import('../../../api/search');
        const req: AskQuestionRequest & { conversation_id?: string } = { question };
        // 优先使用外部 connectionId（来自 ScopePicker），否则使用内部下拉值
        const effectiveConnectionId = useExternalConnection
          ? (externalConnectionId ? Number(externalConnectionId) : null)
          : selectedConnectionId;
        if (effectiveConnectionId !== null) req.connection_id = effectiveConnectionId;
        if (conversationId) req.conversation_id = conversationId;
        const result = await askQuestion(req);
        onResult(result);
      } catch (err: unknown) {
        if (err instanceof Error) {
          const code = (err as { code?: string }).code || 'UNKNOWN';
          onError({ code, message: err.message });
        } else {
          onError({ code: 'UNKNOWN', message: String(err) });
        }
      } finally {
        setLoading(false);
        onLoading(false);
      }
    };

    // 内部连接下拉：仅在无外部 connectionId 且连接数 > 1 时显示
    const showConnectionSelect = !useExternalConnection && connections.length > 1;

    return (
      <>
      <div className="relative rounded-3xl border border-slate-200/70 bg-white/80 backdrop-blur-sm shadow-md px-3 py-3 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20 focus-within:shadow-lg transition-shadow">
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
          rows={2}
          disabled={loading}
          className={`w-full pr-20 py-3 bg-white text-slate-800 placeholder-slate-400
                     focus:outline-none text-sm resize-none leading-relaxed rounded-xl
                     ${showConnectionSelect ? 'pl-36 px-4' : 'px-4'}`}
        />

        {/* 快捷键提示 */}
        <span className="absolute right-14 bottom-4 text-[10px] text-slate-300 select-none pointer-events-none" style={{ color: '#cbd5e1' }}>
          ⌘K
        </span>

        {isStreaming ? (
          <button
            onClick={onAbort}
            className="absolute right-4 top-1/2 -translate-y-1/2 p-2.5 bg-blue-700
                       hover:bg-blue-800 text-white rounded-lg transition-colors"
            aria-label="停止"
          >
            <i className="ri-stop-circle-line text-base" />
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={loading || !input.trim()}
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
          尚未配置数据连接，请先<Link to="/admin/llm-configs" className="underline hover:text-amber-700">前往添加</Link>。
        </p>
      )}
      </>
    );
  }
);

// Gap-05 §11 陷阱6：memo 隔离，使 streaming token 更新不触发 AskBar 重渲染
export const AskBar = memo(AskBarBase);
AskBar.displayName = 'AskBar';
