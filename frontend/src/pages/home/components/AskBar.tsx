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
import { useState, useEffect, useRef, forwardRef } from 'react';
import type { SearchAnswer, AskQuestionRequest } from '../../../api/search';
import { listConnections, type TableauConnection } from '../../../api/tableau';

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
}

export const AskBar = forwardRef<HTMLTextAreaElement, AskBarProps>(
  function AskBar({ onResult, onError, onLoading, onQuestionChange, conversationId }, ref) {
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [connections, setConnections] = useState<TableauConnection[]>([]);
    const [selectedConnectionId, setSelectedConnectionId] = useState<number | null>(null);

    const internalRef = useRef<HTMLTextAreaElement>(null);
    const textareaRef = (ref as React.RefObject<HTMLTextAreaElement>) ?? internalRef;

    // 加载连接列表
    useEffect(() => {
      listConnections()
        .then((res) => {
          const active = res.connections.filter((c) => c.is_active);
          setConnections(active);
          if (active.length > 0) setSelectedConnectionId(active[0].id);
        })
        .catch(() => {
          // 忽略：连接列表加载失败不影响问答
        });
    }, []);

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
      const question = input.trim().slice(0, MAX_LENGTH);
      onQuestionChange?.(question);
      setInput('');
      setLoading(true);
      onLoading(true);
      try {
        const { askQuestion } = await import('../../../api/search');
        const req: AskQuestionRequest & { conversation_id?: string } = { question };
        if (selectedConnectionId !== null) req.connection_id = selectedConnectionId;
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

    const showConnectionSelect = connections.length > 1;

    return (
      <div className="relative rounded-2xl border border-slate-200 bg-white shadow-sm px-3 py-3">
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
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="输入你的数据问题…（Enter 发送，Shift+Enter 换行）"
          rows={2}
          disabled={loading}
          className={`w-full pr-20 py-3 bg-white text-slate-800 placeholder-slate-400
                     focus:outline-none text-sm resize-none leading-relaxed rounded-xl
                     ${showConnectionSelect ? 'pl-36 px-4' : 'px-4'}`}
        />

        {/* 快捷键提示 */}
        <span className="absolute right-14 bottom-4 text-[10px] text-slate-300 select-none pointer-events-none">
          ⌘K
        </span>

        <button
          onClick={submit}
          disabled={loading || !input.trim()}
          className="absolute right-4 top-1/2 -translate-y-1/2 p-2.5 bg-slate-900
                     hover:bg-slate-800 disabled:opacity-40 text-white rounded-lg transition-colors"
          aria-label="发送"
        >
          {loading ? (
            <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
          ) : (
            <i className="ri-send-plane-fill text-base" />
          )}
        </button>
      </div>
    );
  }
);
