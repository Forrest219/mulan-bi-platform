import { useState } from 'react';

interface ThinkingBlockProps {
  content: string;
  durationMs?: number;
}

export default function ThinkingBlock({ content, durationMs }: ThinkingBlockProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-3 border border-slate-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-50 text-xs text-slate-500 hover:bg-slate-100"
      >
        <i className={open ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'} />
        <span>AI 思考过程</span>
        {durationMs != null && (
          <span className="ml-auto text-slate-400">{(durationMs / 1000).toFixed(1)}s</span>
        )}
      </button>
      {open && (
        <div className="px-4 py-3 text-xs text-slate-500 bg-white whitespace-pre-wrap leading-relaxed border-t border-slate-100">
          {content}
        </div>
      )}
    </div>
  );
}
