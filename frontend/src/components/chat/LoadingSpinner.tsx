/**
 * LoadingSpinner — 统一加载状态组件（Spec 25 Phase 2 Batch 4）
 *
 * 提供多种加载状态变体，适用于聊天场景：
 * - Spinner: 内联旋转指示器（替代分散的 animate-spin）
 * - ChatLoading: 聊天场景的三点加载动画
 */
import React from 'react';

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

/**
 * 通用旋转加载指示器
 * size: sm=16px, md=20px, lg=24px
 */
export function Spinner({ size = 'md', className = '' }: SpinnerProps) {
  const sizeClasses = {
    sm: 'w-4 h-4 border-2',
    md: 'w-5 h-5 border-2',
    lg: 'w-6 h-6 border-[2.5px]',
  };

  return (
    <span
      className={`inline-block border-slate-300 border-t-slate-600 rounded-full animate-spin ${sizeClasses[size]} ${className}`}
      role="status"
      aria-label="加载中"
    />
  );
}

/**
 * 聊天场景三点加载动画（替代流式气泡内的内联样式）
 */
export function ChatLoadingDots({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`} role="status" aria-label="正在思考">
      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:0ms]" />
      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:150ms]" />
      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:300ms]" />
    </span>
  );
}

/**
 * 全屏加载遮罩（用于页面级加载状态）
 */
export function FullPageLoader({ message = '加载中...' }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3">
      <Spinner size="lg" />
      <span className="text-sm text-slate-400">{message}</span>
    </div>
  );
}

/**
 * 按钮内置加载状态（替代直接写死的内联 spinner）
 */
export function ButtonSpinner({ label = '加载中' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
      {label && <span>{label}</span>}
    </span>
  );
}

export default Spinner;
