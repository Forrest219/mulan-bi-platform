import React, { useEffect, useRef } from 'react';
import MessageBubble from '../../../components/chat/MessageBubble';
import { MessageActions } from './MessageActions';
import SourceCard from './SourceCard';
import type { StreamingMessage, TableData } from '../../../hooks/useStreamingChat';

interface HistoryMessage {
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
  response_type?: string | null;
  response_data?: unknown;
}

interface MessageListProps {
  messages: StreamingMessage[];
  mockContent?: string;
  isMockStreaming?: boolean;
  lastQuestion?: string;
  onRegenerate?: () => void;
  historyMessages?: HistoryMessage[];
}

function MessageList({ messages, mockContent, isMockStreaming, lastQuestion, onRegenerate, historyMessages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  /** Reconstruct TableData from a history message's persisted response_data. */
  function histTableData(msg: HistoryMessage): TableData | undefined {
    if (msg.response_type !== 'table' || !msg.response_data || typeof msg.response_data !== 'object') return undefined;
    const rd = msg.response_data as { fields?: string[]; rows?: (string | number | null)[][] };
    const { fields, rows } = rd;
    if (!fields?.length || !rows?.length) return undefined;
    const col_types = fields.map((_, i) => {
      const sample = rows!.slice(0, 5).map((r) => r[i]).filter((v) => v != null && v !== '');
      return sample.length > 0 && sample.every((v) => typeof v === 'number') ? 'numeric' : 'string';
    }) as ('numeric' | 'string')[];
    return { fields, rows: rows!, col_types };
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, mockContent]);

  const hasContent = (historyMessages?.length ?? 0) > 0 ||
    messages.length > 0 ||
    isMockStreaming ||
    !!mockContent;

  if (!hasContent) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-300 select-none">
        <i className="ri-chat-3-line text-4xl mb-3 opacity-50" />
        <p className="text-sm">输入问题开始对话</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto w-full px-4">
      <div className="flex flex-col gap-4 py-6">

        {/* 历史消息（URL conv= 恢复） */}
        {historyMessages && historyMessages.length > 0 && historyMessages.map((msg, idx) => (
          <div key={`history-${idx}`} className="group">
            <MessageBubble
              role={msg.role}
              content={msg.content}
              isStreaming={false}
              tableData={histTableData(msg)}
            />
            {msg.created_at && (
              <p className={`text-[10px] text-slate-400 mt-1 ${msg.role === 'user' ? 'text-right' : 'ml-1'}`}>
                {new Date(msg.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
              </p>
            )}
          </div>
        ))}

        {/* 真实路径：遍历 SSE 流消息 */}
        {messages.length > 0 && (() => {
          const lastAssistantIndex = messages.reduce(
            (acc, m, i) => (m.role === 'assistant' ? i : acc),
            -1
          );
          let lastUserQuestion = '';
          return messages.map((msg, msgIndex) => {
            if (msg.role === 'user') {
              lastUserQuestion = msg.content;
            }
            const questionForAction = lastUserQuestion;
            return (
              <div key={msg.id} className="group">
                <MessageBubble
                  role={msg.role}
                  content={msg.content}
                  isStreaming={msg.isStreaming}
                  isError={msg.isError}
                  thinking={msg.thinking}
                  traceId={msg.traceId}
                  tableData={msg.tableData}
                  chartData={msg.chartData}
                />
                {msg.timestamp && !msg.isStreaming && (
                  <p className={`text-[10px] text-slate-400 mt-1 ${msg.role === 'user' ? 'text-right' : 'ml-1'}`}>
                    {new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                  </p>
                )}
                {msg.role === 'assistant' && !msg.isStreaming && (
                  <>
                    {msg.metadata && msg.metadata.sources_count > 0 && (
                      <SourceCard
                        sourcesCount={msg.metadata.sources_count}
                        topSources={msg.metadata.top_sources}
                      />
                    )}
                    <MessageActions
                      content={msg.content}
                      conversationId={null}
                      messageIndex={msgIndex}
                      question={questionForAction}
                      traceId={msg.traceId}
                      onRegenerate={msgIndex === lastAssistantIndex ? onRegenerate : undefined}
                    />
                  </>
                )}
              </div>
            );
          });
        })()}

        {/* Mock 路径 */}
        {(isMockStreaming || mockContent) && (
          <>
            {lastQuestion && (
              <div className="flex justify-end">
                <div className="bg-blue-600 text-white rounded-xl px-4 py-3 max-w-[85%] text-sm">
                  <span className="whitespace-pre-wrap">{lastQuestion}</span>
                </div>
              </div>
            )}
            <div className="flex justify-start">
              <div className="max-w-[85%]">
                <div className="flex items-center gap-1 mb-1">
                  <i className="ri-robot-2-line w-4 h-4 text-slate-400" />
                  <span className="text-xs text-slate-400">木兰</span>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 text-sm leading-relaxed text-slate-800 shadow-sm">
                  {isMockStreaming && !mockContent && (
                    <span className="inline-flex items-center gap-1.5 text-slate-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:0ms]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:150ms]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:300ms]" />
                    </span>
                  )}
                  {mockContent && (
                    <span className="whitespace-pre-wrap">
                      {mockContent}
                      {isMockStreaming && (
                        <span className="inline-flex gap-0.5 ml-1 align-middle">
                          {[0, 150, 300].map((delay) => (
                            <span
                              key={delay}
                              className="w-1 h-1 rounded-full bg-slate-400 animate-bounce"
                              style={{ animationDelay: `${delay}ms` }}
                            />
                          ))}
                        </span>
                      )}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </>
        )}

        <div ref={bottomRef} />

      </div>
    </div>
  );
}

export default React.memo(MessageList);
