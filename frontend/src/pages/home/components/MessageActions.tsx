import { useState } from 'react';

interface MessageActionsProps {
  content: string;
  conversationId: string | null;
  messageIndex: number;
  question: string;
  traceId?: string;
  onRegenerate?: () => void;
}

export function MessageActions({ content, conversationId, messageIndex, question, traceId, onRegenerate }: MessageActionsProps) {
  const [copied, setCopied] = useState(false);
  const [rated, setRated] = useState<'up' | 'down' | null>(null);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRate = async (rating: 'up' | 'down') => {
    if (rated) return;
    setRated(rating);
    try {
      // Spec 36 §5: POST /api/agent/feedback — 使用 run_id + rating
      // MessageBubble 已通过 traceId 传入 run_id（见 MessageList.tsx）
      if (traceId) {
        await fetch('/api/agent/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ run_id: traceId, rating }),
        });
      }
      // Fallback: 如果没有 traceId 则静默忽略（老数据兼容）
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
