/**
 * MessageList — 问数模块消息流
 *
 * - user 气泡：右对齐，蓝底白字
 * - assistant 气泡：左对齐，白底，Markdown 渲染（复用 MessageBubble）
 * - loading 态：显示 AI 思考中占位
 * - 新消息到达时自动滚动到底部
 * - 空态：居中提示
 *
 * Props 驱动，无业务状态
 */
import { memo, useEffect, useRef } from 'react';
import MessageBubble from '../chat/MessageBubble';
import type { QuerySessionMessage } from '../../hooks/useQuerySession';

interface MessageListProps {
  messages: QuerySessionMessage[];
  loading?: boolean;
}

// P1-1：React.memo 避免父组件非相关 state 变化引发的全量重渲染
const MessageList = memo(function MessageList({ messages, loading = false }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  if (messages.length === 0 && !loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-300 select-none">
        <i className="ri-database-2-line text-4xl mb-3 opacity-50" />
        <p className="text-sm">选择数据源，开始自然语言问数</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto w-full px-4">
      <div className="flex flex-col py-6">
        {messages.map((msg) => (
          <div key={msg.id} className="relative">
            <MessageBubble
              role={msg.role}
              content={msg.content}
              isError={msg.isError}
            />
            {/* 流式光标：assistant 消息 isStreaming 为 true 时，文字末尾显示闪烁光标 */}
            {msg.role === 'assistant' && msg.isStreaming && (
              <span
                className="inline-block w-0.5 h-4 bg-slate-500 ml-0.5 align-middle animate-pulse"
                aria-hidden="true"
              />
            )}
          </div>
        ))}

        {/* AI 思考中占位：仅 loading 且最后一条不是正在流式输出的 assistant 消息时显示 */}
        {loading && !messages.some((m) => m.role === 'assistant' && m.isStreaming) && (
          <div className="flex justify-start mb-4">
            <div className="bg-white border border-slate-200 rounded-2xl px-4 py-3 shadow-sm">
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <span
                  className="inline-block w-2 h-2 bg-slate-300 rounded-full animate-bounce"
                  style={{ animationDelay: '0ms' }}
                />
                <span
                  className="inline-block w-2 h-2 bg-slate-300 rounded-full animate-bounce"
                  style={{ animationDelay: '150ms' }}
                />
                <span
                  className="inline-block w-2 h-2 bg-slate-300 rounded-full animate-bounce"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
});

export default MessageList;
