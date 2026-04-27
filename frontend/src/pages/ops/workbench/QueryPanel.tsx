/**
 * QueryPanel -- 问数模式面板
 *
 * 右侧内容区：显示 NL-to-query 界面
 * 复用首页的 AskBar + MessageList 模式
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { useScope } from '../../home/context/ScopeContext';
import { useStreamingChat } from '../../../hooks/useStreamingChat';
import MessageList from '../../home/components/MessageList';
import AskBar from '../../home/components/AskBar';
import type { SearchAnswer } from '../../../api/search';

export interface QueryPanelProps {
  /** 从侧边栏选中的会话 ID */
  selectedSessionId?: string | null;
}

export function QueryPanel({ selectedSessionId: _selectedSessionId }: QueryPanelProps) {
  const { connectionId } = useScope();
  const { messages: streamingMessages, isStreaming, sendMessage, abort } = useStreamingChat();

  const [lastQuestion, setLastQuestion] = useState('');
  const lastQuestionRef = useRef('');
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);

  // 流结束后推进页面状态
  const [hasResult, setHasResult] = useState(false);
  useEffect(() => {
    if (!isStreaming && streamingMessages.length > 0) {
      setHasResult(true);
    }
  }, [isStreaming, streamingMessages.length]);

  const handleAskBarResult = useCallback((_r: SearchAnswer) => {
    setHasResult(true);
  }, []);

  const handleError = useCallback((_err: { code: string; message: string }) => {
    setHasResult(true);
  }, []);

  const handleLoading = useCallback((loading: boolean) => {
    if (loading) {
      const connId = connectionId ? Number(connectionId) : undefined;
      void sendMessage(lastQuestionRef.current, connId, currentConversationId);
    }
  }, [connectionId, sendMessage, currentConversationId]);

  const handleRegenerate = useCallback(() => {
    const question = lastQuestionRef.current;
    if (!question || isStreaming) return;
    const connId = connectionId ? Number(connectionId) : undefined;
    void sendMessage(question, connId, currentConversationId);
  }, [isStreaming, connectionId, sendMessage, currentConversationId]);

  return (
    <div className="flex flex-col h-full">
      {/* 消息区 */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {streamingMessages.length === 0 && !hasResult && (
          <div className="flex flex-col items-center justify-center h-full text-slate-400">
            <i className="ri-question-answer-line text-4xl mb-3" />
            <p className="text-sm">在下方输入问题开始问数</p>
            <p className="text-xs mt-1">支持自然语言查询 Tableau 数据</p>
          </div>
        )}
        {streamingMessages.length > 0 && (
          <MessageList
            messages={streamingMessages}
            mockContent=""
            isMockStreaming={false}
            lastQuestion={lastQuestion}
            onRegenerate={handleRegenerate}
            historyMessages={[]}
          />
        )}
      </div>

      {/* 底部输入区 */}
      <div className="shrink-0 border-t border-slate-100 bg-white px-6 py-3">
        <AskBar
          onResult={handleAskBarResult}
          onError={handleError}
          onLoading={handleLoading}
          onQuestionChange={(q) => { setLastQuestion(q); lastQuestionRef.current = q; }}
          conversationId={currentConversationId ?? undefined}
          connectionId={connectionId}
          isStreaming={isStreaming}
          onAbort={abort}
          useMock={false}
          onStreamToken={() => {}}
        />
        <p className="mt-1.5 text-center text-[11px] text-slate-400">
          回答由 AI 生成，请核对关键数据后使用
        </p>
      </div>
    </div>
  );
}
