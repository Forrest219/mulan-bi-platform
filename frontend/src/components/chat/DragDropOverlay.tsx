import { useState, useEffect, useCallback, useRef } from 'react';

interface DragDropOverlayProps {
  onFilesDropped: (files: File[]) => void;
  disabled?: boolean;
}

export default function DragDropOverlay({ onFilesDropped, disabled = false }: DragDropOverlayProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [visible, setVisible] = useState(false);
  const dragCounterRef = useRef(0);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showOverlay = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
    setIsDragging(true);
    setVisible(true);
  }, []);

  const hideOverlay = useCallback(() => {
    setVisible(false);
    hideTimerRef.current = setTimeout(() => {
      setIsDragging(false);
    }, 100);
  }, []);

  const handleDragEnter = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (disabled) return;
      dragCounterRef.current += 1;
      if (dragCounterRef.current === 1) {
        showOverlay();
      }
    },
    [disabled, showOverlay]
  );

  const handleDragLeave = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounterRef.current -= 1;
      if (dragCounterRef.current === 0) {
        hideOverlay();
      }
    },
    [hideOverlay]
  );

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounterRef.current = 0;
      hideOverlay();
      if (disabled) return;
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length > 0) {
        onFilesDropped(files);
      }
    },
    [disabled, onFilesDropped, hideOverlay]
  );

  useEffect(() => {
    window.addEventListener('dragenter', handleDragEnter);
    window.addEventListener('dragleave', handleDragLeave);
    window.addEventListener('dragover', handleDragOver);
    window.addEventListener('drop', handleDrop);
    return () => {
      window.removeEventListener('dragenter', handleDragEnter);
      window.removeEventListener('dragleave', handleDragLeave);
      window.removeEventListener('dragover', handleDragOver);
      window.removeEventListener('drop', handleDrop);
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, [handleDragEnter, handleDragLeave, handleDragOver, handleDrop]);

  if (!isDragging) return null;

  return (
    <div
      className={[
        'fixed inset-0 z-50 bg-slate-50/90 backdrop-blur-sm',
        'transition-opacity',
        visible ? 'duration-150 ease-out opacity-100' : 'duration-100 ease-in opacity-0',
      ].join(' ')}
      onDragEnter={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounterRef.current = 0;
        hideOverlay();
        if (disabled) return;
        const files = Array.from(e.dataTransfer?.files ?? []);
        if (files.length > 0) {
          onFilesDropped(files);
        }
      }}
    >
      <div className="flex items-center justify-center h-full p-8">
        <div
          className="flex flex-col items-center justify-center gap-4
                      border-2 border-dashed border-blue-300 rounded-2xl p-12
                      bg-white/60 w-full max-w-2xl max-h-96"
        >
          {/* CloudArrowUpIcon */}
          <div className="w-16 h-16 rounded-full bg-blue-50 flex items-center justify-center">
            <svg
              className="w-8 h-8 text-blue-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M12 16v-8m0 0l-3 3m3-3l3 3M6.5 19a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19H6.5z"
              />
            </svg>
          </div>

          <div className="text-center">
            <p className="text-base font-semibold text-slate-700">释放文件以上传</p>
            <p className="text-sm text-slate-400 mt-1">支持图片、PDF、文档等格式</p>
          </div>
        </div>
      </div>
    </div>
  );
}
