import React, { useState, useRef, useCallback, KeyboardEvent } from 'react';

interface AttachedFile {
  id: string;
  file: File;
  previewUrl?: string;
}

interface AskBarProps {
  onSend: (message: string, files: File[]) => void;
  onFileDrop?: (files: File[]) => void;
  disabled?: boolean;
  filterPills?: { label: string; active: boolean; onClick: () => void }[];
}

function AttachmentBubble({
  attached,
  onRemove,
  removing,
}: {
  attached: AttachedFile;
  onRemove: (id: string) => void;
  removing: boolean;
}) {
  const isImage = attached.file.type.startsWith('image/');
  const sizeLabel =
    attached.file.size < 1024 * 1024
      ? `${(attached.file.size / 1024).toFixed(1)} KB`
      : `${(attached.file.size / (1024 * 1024)).toFixed(1)} MB`;

  return (
    <div
      className={[
        'relative group flex-shrink-0',
        removing
          ? 'transition-all duration-100 ease-in opacity-0 scale-90'
          : 'transition-all duration-150 ease-out opacity-100 scale-100',
      ].join(' ')}
    >
      {isImage && attached.previewUrl ? (
        <div className="w-16 h-16 rounded-xl overflow-hidden border border-slate-200/60 bg-white/90 backdrop-blur-sm shadow-sm">
          <img
            src={attached.previewUrl}
            alt={attached.file.name}
            className="w-full h-full object-cover"
          />
        </div>
      ) : (
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-200/60 bg-white/90 backdrop-blur-sm shadow-sm max-w-[160px]">
          <svg
            className="w-5 h-5 text-slate-400 flex-shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0121 9.414V19a2 2 0 01-2 2z"
            />
          </svg>
          <div className="min-w-0">
            <p className="text-xs font-medium text-slate-700 truncate">{attached.file.name}</p>
            <p className="text-xs text-slate-400">{sizeLabel}</p>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => onRemove(attached.id)}
        className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full
                   bg-white text-slate-500 border border-slate-200 shadow-sm
                   flex items-center justify-center
                   opacity-0 group-hover:opacity-100
                   transition-opacity duration-150
                   hover:bg-red-50 hover:text-red-500 hover:border-red-200"
        aria-label={`移除 ${attached.file.name}`}
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

function AskBar({ onSend, onFileDrop, disabled = false, filterPills }: AskBarProps) {
  const [message, setMessage] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [removingIds, setRemovingIds] = useState<Set<string>>(new Set());
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((files: File[]) => {
    const newAttached: AttachedFile[] = files.map((file) => {
      const id = `${Date.now()}-${Math.random()}`;
      const previewUrl = file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined;
      return { id, file, previewUrl };
    });
    setAttachedFiles((prev) => [...prev, ...newAttached]);
  }, []);

  const removeFile = useCallback((id: string) => {
    setRemovingIds((prev) => new Set(prev).add(id));
    setTimeout(() => {
      setAttachedFiles((prev) => {
        const target = prev.find((f) => f.id === id);
        if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
        return prev.filter((f) => f.id !== id);
      });
      setRemovingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, 100);
  }, []);

  const handleFileSelect = () => {
    fileInputRef.current?.click();
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length > 0) {
      addFiles(files);
      onFileDrop?.(files);
    }
    e.target.value = '';
  };

  const canSend = (message.trim().length > 0 || attachedFiles.length > 0) && !disabled;

  const handleSend = () => {
    if (!canSend) return;
    onSend(message.trim(), attachedFiles.map((a) => a.file));
    setMessage('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    attachedFiles.forEach((f) => {
      if (f.previewUrl) URL.revokeObjectURL(f.previewUrl);
    });
    setAttachedFiles([]);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setMessage(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  const hasFilterPills = filterPills && filterPills.length > 0;

  return (
    <div className="relative w-full">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileInputChange}
        accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt"
      />

      <div
        className={[
          'rounded-2xl border shadow-sm',
          'backdrop-blur-sm bg-white/80',
          'border-slate-200/60',
          'focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20',
          'transition-[border-color,box-shadow] duration-150',
          disabled ? 'opacity-50 cursor-not-allowed' : '',
        ].join(' ')}
      >
        {/* AttachmentRow：有附件时显示 */}
        {attachedFiles.length > 0 && (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {attachedFiles.map((attached) => (
              <AttachmentBubble
                key={attached.id}
                attached={attached}
                onRemove={removeFile}
                removing={removingIds.has(attached.id)}
              />
            ))}
          </div>
        )}

        {/* TextareaAutoResize */}
        <textarea
          ref={textareaRef}
          value={message}
          onChange={handleTextareaChange}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="向木兰提问..."
          rows={1}
          className={[
            'w-full resize-none bg-transparent px-4 py-3',
            'text-sm text-slate-900 placeholder:text-slate-400',
            'focus:outline-none',
            'min-h-[48px] max-h-[200px] overflow-y-auto',
          ].join(' ')}
        />

        {/* FilterPillsRow：有 pills 时显示 */}
        {hasFilterPills && (
          <div className="flex flex-wrap gap-1.5 px-3 pb-2">
            {filterPills!.map((pill) => (
              <button
                key={pill.label}
                type="button"
                onClick={pill.onClick}
                className={[
                  'px-2.5 py-1 rounded-full text-xs font-medium border',
                  'transition-colors duration-150',
                  pill.active
                    ? 'text-blue-700 bg-blue-50 border-blue-200/40'
                    : 'text-slate-500 bg-slate-50 border-slate-200/60 hover:bg-slate-100',
                ].join(' ')}
              >
                {pill.label}
              </button>
            ))}
          </div>
        )}

        {/* ToolbarRow */}
        <div className="flex items-center justify-between px-3 pb-2.5">
          <div className="flex items-center gap-1">
            {/* AttachButton */}
            <button
              type="button"
              onClick={handleFileSelect}
              disabled={disabled}
              className="w-8 h-8 rounded-full flex items-center justify-center
                         text-slate-400 hover:text-slate-600 hover:bg-slate-100
                         transition-colors duration-150 disabled:opacity-50"
              aria-label="上传文件"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                />
              </svg>
            </button>
          </div>

          {/* SendButton */}
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend}
            className={[
              'w-8 h-8 rounded-full flex items-center justify-center',
              'transition-colors duration-150',
              canSend
                ? 'bg-blue-700 hover:bg-blue-800 text-white'
                : 'bg-slate-100 text-slate-300 cursor-not-allowed',
            ].join(' ')}
            aria-label="发送"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

export default React.memo(AskBar);
