import { useState } from 'react';
import type { SearchAnswer } from '../../../api/search';

const MAX_LENGTH = 500;

interface AskBarProps {
  onResult: (result: SearchAnswer) => void;
  onError: (err: { code: string; message: string }) => void;
  onLoading: (loading: boolean) => void;
}

export function AskBar({ onResult, onError, onLoading }: AskBarProps) {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!input.trim() || loading) return;
    const question = input.trim().slice(0, MAX_LENGTH);
    setLoading(true);
    onLoading(true);
    try {
      const { askQuestion } = await import('../../../api/search');
      const result = await askQuestion({ question });
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

  return (
    <div className="relative">
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value.slice(0, MAX_LENGTH))}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="有什么可以帮到您"
        rows={2}
        disabled={loading}
        className="w-full px-8 pr-20 py-4 bg-white text-slate-800 placeholder-slate-400
                   focus:outline-none text-base resize-none leading-relaxed rounded-full
                   disabled:opacity-60"
        style={{ border: '1px solid #dfe1e5' }}
      />
      <button
        onClick={submit}
        disabled={loading || !input.trim()}
        className="absolute right-3 top-1/2 -translate-y-1/2 p-2.5 bg-slate-900
                   hover:bg-slate-800 disabled:opacity-40 text-white rounded-full transition-colors"
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
