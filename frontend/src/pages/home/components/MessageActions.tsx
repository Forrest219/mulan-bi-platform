import { useState } from 'react';

interface MessageActionsProps {
  content: string;
  conversationId: string | null;
  messageIndex: number;
  question: string;
}

export function MessageActions({ content, conversationId, messageIndex, question }: MessageActionsProps) {
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
    } catch {
      // 埋点失败不影响用户
    }
  };

  return (
    <div className="flex items-center gap-1 mt-2 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
      <button
        onClick={handleCopy}
        className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
        title="复制"
      >
        <i className={copied ? 'ri-check-line' : 'ri-file-copy-line'} />
        {copied ? '已复制' : '复制'}
      </button>
      <button
        onClick={() => handleRate('up')}
        disabled={rated !== null}
        className={`px-2 py-1 rounded-md text-xs transition-colors ${
          rated === 'up'
            ? 'text-green-600'
            : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100'
        }`}
        title="有帮助"
      >
        <i className="ri-thumb-up-line" />
      </button>
      <button
        onClick={() => handleRate('down')}
        disabled={rated !== null}
        className={`px-2 py-1 rounded-md text-xs transition-colors ${
          rated === 'down'
            ? 'text-red-500'
            : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100'
        }`}
        title="没帮助"
      >
        <i className="ri-thumb-down-line" />
      </button>
    </div>
  );
}
