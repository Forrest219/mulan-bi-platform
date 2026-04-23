/**
 * ChatInput — 问数模块输入框
 *
 * 功能：
 *   - 自动增高 textarea（最高 200px）
 *   - Enter 发送，Shift+Enter 换行
 *   - 发送中禁用（disabled state）
 *   - 字符计数上限 1000
 *
 * Props 驱动，无业务状态（仅 input value 和 textarea 高度是内部状态）
 */
import { useState, useRef, useEffect, useCallback } from 'react';

const MAX_LENGTH = 1000;

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function ChatInput({ onSend, disabled = false, placeholder = '输入问题...' }: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 自动调整高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue('');
    // 重置高度
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, disabled, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div className="flex items-end gap-2 bg-white border border-slate-200 rounded-2xl px-4 py-3 shadow-sm focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-400 transition-all">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value.slice(0, MAX_LENGTH))}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder}
        rows={1}
        className="flex-1 resize-none bg-transparent text-sm text-slate-800 placeholder-slate-400 focus:outline-none min-h-[24px] max-h-[200px] leading-relaxed disabled:opacity-50"
        aria-label="输入问题"
      />

      <div className="flex items-center gap-2 shrink-0">
        {/* 字符计数（接近上限时显示） */}
        {value.length > MAX_LENGTH * 0.8 && (
          <span className={`text-xs ${value.length >= MAX_LENGTH ? 'text-red-500' : 'text-slate-400'}`}>
            {value.length}/{MAX_LENGTH}
          </span>
        )}

        {/* 发送按钮 */}
        <button
          onClick={handleSend}
          disabled={!canSend}
          aria-label="发送"
          className={`w-8 h-8 flex items-center justify-center rounded-xl transition-colors ${
            canSend
              ? 'bg-blue-700 hover:bg-blue-800 text-white'
              : 'bg-slate-100 text-slate-300 cursor-not-allowed'
          }`}
        >
          {disabled ? (
            <i className="ri-loader-4-line text-sm animate-spin" />
          ) : (
            <i className="ri-send-plane-fill text-sm" />
          )}
        </button>
      </div>
    </div>
  );
}
