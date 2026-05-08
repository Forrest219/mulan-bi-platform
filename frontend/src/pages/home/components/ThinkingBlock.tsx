import { useState } from 'react';

interface ThinkingBlockProps {
  content: string;
  durationMs?: number;
}

export default function ThinkingBlock({ content, durationMs }: ThinkingBlockProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-[10px] text-slate-400 hover:text-slate-500 transition-colors select-none"
      >
        <i className="ri-sparkling-line text-slate-300" />
        <span>思考过程</span>
        {durationMs != null && (
          <span className="text-slate-300">· {(durationMs / 1000).toFixed(1)}s</span>
        )}
        <i className={`${open ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'} text-slate-300`} />
      </button>
      {open && (
        <div className="mt-1.5 px-3 py-2.5 bg-slate-50 rounded-md text-xs text-slate-400 leading-relaxed whitespace-pre-wrap border-l-2 border-slate-200">
          {content}
        </div>
      )}
    </div>
  );
}
