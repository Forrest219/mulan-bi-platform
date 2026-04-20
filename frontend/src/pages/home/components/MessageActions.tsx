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
      if (traceId) {
        await fetch('/api/ask-data/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ trace_id: traceId, rating, question }),
        });
      } else {
        await fetch('/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            conversation_id: conversationId,
            message_index: messageIndex,
            question,
            answer_summary: content.slice(0, 100),
            rating,
          }),
        });
      }
    } catch {
      // 埋点失败不影响用户
    }
  };

  return (
    <div className="flex items-center gap-0.5 mt-2 flex-wrap">
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
