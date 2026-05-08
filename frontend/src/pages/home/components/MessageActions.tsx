import { useState, useEffect } from 'react';

interface MessageActionsProps {
  content: string;
  conversationId: string | null;
  messageIndex: number;
  question: string;
  traceId?: string;
  onRegenerate?: () => void;
  /** Callback when user clicks edit */
  onEdit?: (content: string) => void;
  /** Callback when user clicks delete */
  onDelete?: () => void;
}

export function MessageActions({ content, conversationId, messageIndex, question, traceId, onRegenerate, onEdit, onDelete }: MessageActionsProps) {
  const [copied, setCopied] = useState(false);
  const [rated, setRated] = useState<'up' | 'down' | null>(null);

  useEffect(() => {
    if (!conversationId) return;
    fetch(`/api/agent/feedback?conversation_id=${encodeURIComponent(conversationId)}&message_index=${messageIndex}`, {
      credentials: 'include',
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.rating) setRated(data.rating as 'up' | 'down'); })
      .catch(() => {});
  }, [conversationId, messageIndex]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRate = async (rating: 'up' | 'down') => {
    if (rated) return;
    setRated(rating);
    try {
      // Spec 25 Gap 1: POST /api/agent/feedback/v2 — 传递完整参数
      // 优先使用 v2 端点（支持 run_id 映射和 conversation_id 等）
      const payload: Record<string, unknown> = { rating };
      if (traceId) {
        payload.run_id = traceId;
      }
      if (conversationId) {
        payload.conversation_id = conversationId;
      }
      if (messageIndex !== undefined) {
        payload.message_index = messageIndex;
      }
      if (question) {
        payload.question = question;
      }

      await fetch('/api/agent/feedback/v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      });
    } catch {
      // 埋点失败不影响用户
    }
  };

  return (
    <div className="flex items-center gap-0.5 mt-2 flex-wrap opacity-0 group-hover:opacity-100 transition-opacity duration-150">
      <button
        onClick={() => handleRate('up')}
        disabled={rated !== null}
        className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-colors ${
          rated === 'up'
            ? 'text-green-600 bg-green-50'
            : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100'
        }`}
        title="有用"
      >
        <i className="ri-thumb-up-line" />
        <span>有用</span>
      </button>
      <button
        onClick={() => handleRate('down')}
        disabled={rated !== null}
        className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-colors ${
          rated === 'down'
            ? 'text-red-500 bg-red-50'
            : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100'
        }`}
        title="报告错误"
      >
        <i className="ri-error-warning-line" />
        <span>报错</span>
      </button>
      {onRegenerate && (
        <button
          onClick={onRegenerate}
          className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          title="重新生成"
        >
          <i className="ri-refresh-line" />
          <span>重新生成</span>
        </button>
      )}
      {onEdit && (
        <button
          onClick={() => onEdit(content)}
          className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          title="编辑"
        >
          <i className="ri-edit-line" />
          <span>编辑</span>
        </button>
      )}
      {onDelete && (
        <button
          onClick={onDelete}
          className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
          title="删除"
        >
          <i className="ri-delete-bin-line" />
          <span>删除</span>
        </button>
      )}
      <button
        onClick={handleCopy}
        className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
        title="复制全文"
      >
        <i className={copied ? 'ri-check-line' : 'ri-file-copy-line'} />
        <span>{copied ? '已复制' : '复制全文'}</span>
      </button>
    </div>
  );
}
