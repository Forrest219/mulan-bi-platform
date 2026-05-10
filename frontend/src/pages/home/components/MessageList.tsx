import React, { useEffect, useRef } from 'react';
import MessageBubble from '../../../components/chat/MessageBubble';
import { MessageActions } from './MessageActions';
import type { StreamingMessage, TableData } from '../../../hooks/useStreamingChat';

interface HistoryMessage {
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
  response_type?: string | null;
  response_data?: unknown;
  trace_id?: string | null;
  sources_count?: number | null;
  top_sources?: string[] | null;
}

interface MessageListProps {
  messages: StreamingMessage[];
  mockContent?: string;
  isMockStreaming?: boolean;
  lastQuestion?: string;
  onRegenerate?: () => void;
  historyMessages?: HistoryMessage[];
  /** conversation_id for history messages — enables feedback via conversation_id alone */
  historyConversationId?: string | null;
  onSourceClick?: (sourceName: string) => void;
}

interface RenderItemOpts {
  key: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isError?: boolean;
  errorCode?: string;
  errorHint?: string;
  thinking?: string;
  traceId?: string | null;
  tableData?: TableData;
  chartData?: StreamingMessage['chartData'];
  sourcesCount?: number | null;
  topSources?: string[] | null;
  timestamp?: number | string | null;
  conversationId?: string | null;
  messageIndex?: number;
  question?: string;
  isLastAssistant?: boolean;
  onRegenerate?: () => void;
  onSourceClick?: (sourceName: string) => void;
}

function renderMessageItem(opts: RenderItemOpts) {
  const {
    key, role, content, isStreaming, isError, errorCode, errorHint, thinking,
    traceId, tableData, chartData, sourcesCount, topSources,
    timestamp, conversationId, messageIndex, question, isLastAssistant, onRegenerate, onSourceClick,
  } = opts;
  const timeStr = timestamp
    ? new Date(timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : null;
  const showActions = role === 'assistant' && !isStreaming && (traceId || conversationId);
  return (
    <div key={key} className="group">
      <MessageBubble
        role={role}
        content={content}
        isStreaming={isStreaming}
        isError={isError}
        errorCode={errorCode}
        errorHint={errorHint}
        thinking={thinking}
        traceId={traceId ?? undefined}
        tableData={tableData}
        chartData={chartData}
        sourcesCount={sourcesCount ?? undefined}
        topSources={topSources ?? undefined}
        onSourceClick={onSourceClick}
      />
      {/* Time + Actions in one flex row */}
      {(timeStr || showActions) && (
        <div className={`flex items-center mt-2 ${role === 'user' ? 'justify-end mr-2' : 'justify-between'}`}>
          {role === 'assistant' && timeStr && !isStreaming && (
            <p className="text-[10px] text-slate-400 ml-1">{timeStr}</p>
          )}
          {showActions && (
            <MessageActions
              content={content}
              conversationId={conversationId ?? null}
              messageIndex={messageIndex ?? 0}
              question={question ?? ''}
              traceId={traceId}
              onRegenerate={isLastAssistant ? onRegenerate : undefined}
            />
          )}
        </div>
      )}
      {role === 'user' && timeStr && !isStreaming && (
        <p className="text-[10px] text-slate-400 mt-1.5 text-right mr-2">{timeStr}</p>
      )}
    </div>
  );
}

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

function MessageList({ messages, mockContent, isMockStreaming, lastQuestion, onRegenerate, historyMessages, historyConversationId, onSourceClick }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

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
    <div className="max-w-5xl mx-auto w-full px-4">
      <div className="flex flex-col gap-4 py-6">

        {/* 历史消息（URL conv= 恢复） */}
        {historyMessages && historyMessages.length > 0 && (() => {
          const lastHistAssistantIdx = historyMessages.reduce(
            (acc, m, i) => (m.role === 'assistant' ? i : acc),
            -1
          );
          let lastHistUserQuestion = '';
          return historyMessages.map((msg, idx) => {
            if (msg.role === 'user') lastHistUserQuestion = msg.content;
            const q = lastHistUserQuestion;
            return renderMessageItem({
              key: `history-${idx}`,
              role: msg.role,
              content: msg.content,
              isStreaming: false,
              tableData: histTableData(msg),
              conversationId: historyConversationId ?? null,
              sourcesCount: msg.sources_count,
              topSources: msg.top_sources,
              timestamp: msg.created_at,
              messageIndex: idx,
              question: q,
              isLastAssistant: idx === lastHistAssistantIdx,
              onRegenerate,
              onSourceClick,
            });
          });
        })()}

        {/* 真实路径：遍历 SSE 流消息 */}
        {messages.length > 0 && (() => {
          const lastAssistantIndex = messages.reduce(
            (acc, m, i) => (m.role === 'assistant' ? i : acc),
            -1
          );
          let lastUserQuestion = '';
          return messages.map((msg, msgIndex) => {
            if (msg.role === 'user') lastUserQuestion = msg.content;
            const questionForAction = lastUserQuestion;
            return renderMessageItem({
              key: msg.id,
              role: msg.role,
              content: msg.content,
              isStreaming: msg.isStreaming,
              isError: msg.isError,
              errorCode: msg.errorCode,
              errorHint: msg.errorHint,
              thinking: msg.thinking,
              traceId: msg.traceId,
              tableData: msg.tableData,
              chartData: msg.chartData,
              sourcesCount: msg.metadata?.sources_count,
              topSources: msg.metadata?.top_sources,
              timestamp: msg.timestamp,
              conversationId: msg.conversationId,
              messageIndex: msgIndex,
              question: questionForAction,
              isLastAssistant: msgIndex === lastAssistantIndex,
              onRegenerate,
              onSourceClick,
            });
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
