/**
 * HomePage — 对话式问数首页（P0 重构）
 *
 * URL 保持 /，结果原地展示，不跳转（C1）
 *
 * idle 态：WelcomeHero + SuggestionGrid + AskBar
 * 有结果态：SearchResult（WelcomeHero 下方）+ AskBar 保持可用
 *
 * 对话历史存 localStorage（C2），由 HomeLayout 提供的 ConversationProvider 管理。
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { LOGO_URL } from '../../config';
import AskBar from './components/AskBar';
import { SearchResult } from './components/SearchResult';
import { WelcomeHero } from './components/WelcomeHero';
import { SuggestionGrid } from './components/SuggestionGrid';
import { useConversations } from '../../store/conversationStore';
import type { SearchAnswer } from '../../api/search';
import { ScopeProvider, useScope } from './context/ScopeContext';
import { ScopePicker } from './components/ScopePicker';
import { AssetInspectorDrawer } from './components/AssetInspectorDrawer';
import { useHomeUrlState } from './hooks/useHomeUrlState';
import { conversationsApi } from '../../api/conversations';
// Gap-05: SSE streaming hook — state 与 AskBar 完全隔离（§11 陷阱6）
import { useStreamingChat } from '../../hooks/useStreamingChat';
import MessageList from './components/MessageList';

type HomeUiState = 'HOME_IDLE' | 'HOME_SUBMITTING' | 'HOME_RESULT' | 'HOME_ERROR' | 'HOME_OFFLINE';

// 后端就绪后改为 false
const USE_MOCK = false;

function HomePageInner() {
  const [homeState, setHomeState] = useState<HomeUiState>('HOME_IDLE');
  const stateBeforeOfflineRef = useRef<HomeUiState>('HOME_IDLE');
  const [result, setResult] = useState<SearchAnswer | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [lastQuestion, setLastQuestion] = useState('');
  const lastQuestionRef = useRef('');
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [historyMessages, setHistoryMessages] = useState<Array<{role: 'user'|'assistant'; content: string}>>([]);

  const { user, hasPermission } = useAuth();
  const { addConversation, appendMessage } = useConversations();
  const { assetId, tab, connectionId, closeAsset, selectedConvId } = useHomeUrlState();
  const { connections: scopeConnections, connectionsLoading } = useScope();
  const noConnection = !connectionsLoading && scopeConnections.length === 0;

  // Gap-05: streaming state 完全独立，不与 AskBar 的 input/loading state 共享
  const { messages: streamingMessages, isStreaming, sendMessage, abort } = useStreamingChat();

  // Task 1: URL conv= 参数驱动历史消息恢复
  const loadConvHistory = useCallback(async (convId: string) => {
    try {
      const detail = await conversationsApi.get(convId);
      const msgs = detail.messages.map((m) => ({ role: m.role, content: m.content }));
      setHistoryMessages(msgs);
      setCurrentConversationId(convId);
      setHomeState('HOME_RESULT');
    } catch {
      setHistoryMessages([]);
      setHomeState('HOME_ERROR');
      setError({ code: 'LOAD_HISTORY_FAILED', message: '历史对话加载失败，请刷新重试' });
    }
  }, []);

  // Mock 流路径：onStreamToken 逐 token 追加到此 state 用于展示
  const [mockStreamingContent, setMockStreamingContent] = useState('');
  const [isMockStreaming, setIsMockStreaming] = useState(false);

  // Task 1: 监听 URL ?conv= 变化，加载历史对话
  // 当切换到新对话（无 conv 参数）时同时重置会话状态
  useEffect(() => {
    if (selectedConvId) {
      void loadConvHistory(selectedConvId);
    } else {
      setHistoryMessages([]);
      setCurrentConversationId(null);
      savedMessageCountRef.current = 0;
    }
  }, [selectedConvId, loadConvHistory]);

  useEffect(() => {
    if (homeState !== 'HOME_OFFLINE') {
      stateBeforeOfflineRef.current = homeState;
    }
  }, [homeState]);

  useEffect(() => {
    const handleOffline = () => {
      setHomeState('HOME_OFFLINE');
    };
    const handleOnline = () => {
      setHomeState(stateBeforeOfflineRef.current);
    };

    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);

    if (!navigator.onLine) {
      handleOffline();
    }

    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, []);

  // 真实 SSE 路径：流结束后推进页面状态
  useEffect(() => {
    if (!USE_MOCK && !isStreaming && streamingMessages.length > 0) {
      setHomeState('HOME_RESULT');
    }
  }, [isStreaming, streamingMessages.length]);

  // 真实 SSE 路径：流结束后将新消息持久化到 conversationStore
  const savedMessageCountRef = useRef(0);
  const currentConversationIdRef = useRef<string | null>(null);
  currentConversationIdRef.current = currentConversationId;
  const streamingMessagesRef = useRef(streamingMessages);
  streamingMessagesRef.current = streamingMessages;
  const addConversationRef = useRef(addConversation);
  addConversationRef.current = addConversation;
  const appendMessageRef = useRef(appendMessage);
  appendMessageRef.current = appendMessage;

  useEffect(() => {
    if (USE_MOCK || isStreaming || streamingMessagesRef.current.length <= savedMessageCountRef.current) return;
    const newMessages = streamingMessagesRef.current.slice(savedMessageCountRef.current);
    savedMessageCountRef.current = streamingMessagesRef.current.length;
    void (async () => {
      let convId = currentConversationIdRef.current;
      if (!convId) {
        convId = await addConversationRef.current();
        currentConversationIdRef.current = convId;
        setCurrentConversationId(convId);
      }
      for (const msg of newMessages) {
        appendMessageRef.current(convId, { role: msg.role, content: msg.content });
      }
    })();
  }, [isStreaming, streamingMessages.length]);

  // ── 未登录态 ─────────────────────────────────────────────────────────────
  if (!user) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="bg-white rounded-xl border border-slate-200 p-10 w-full max-w-md text-center">
          <img src={LOGO_URL} alt="Mulan Platform Logo" className="w-14 h-14 object-contain mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-slate-800 mb-2">Mulan Platform</h1>
          <p className="text-sm text-slate-400 mb-8">数据建模与治理平台</p>
          <p className="text-slate-500 mb-6">请先登录以访问平台功能</p>
          <Link
            to="/login"
            className="inline-block w-full py-2.5 bg-blue-700 text-white rounded-lg text-sm font-semibold hover:bg-blue-800 transition-colors"
          >
            登录
          </Link>
          <div className="mt-4">
            <Link to="/register" className="text-sm text-blue-600 hover:text-blue-700">
              没有账号？去注册
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // ── 事件处理 ──────────────────────────────────────────────────────────────

  const handleResult = async (r: SearchAnswer, question: string) => {
    setResult(r);
    setError(null);
    setHomeState('HOME_RESULT');

    // 追加到对话历史（C2）
    // 非 Mock 路径：conversation 在 useEffect（streaming 结束时）已创建，这里只追加消息
    // Mock 路径：需要自己创建 conversation
    const convId = currentConversationId;
    if (!convId) {
      if (USE_MOCK) {
        const id = await addConversation();
        setCurrentConversationId(id);
        appendMessage(id, { role: 'user', content: question });
        const answerText =
          r.type === 'text' ? r.answer :
          r.type === 'error' ? `[错误] ${r.detail ?? r.reason ?? ''}` :
          r.type === 'number' ? String(r.data) :
          JSON.stringify(r.data ?? r.answer ?? '');
        appendMessage(id, { role: 'assistant', content: answerText });
      }
      // 非 Mock 路径：streaming 结束后 useEffect 会创建 conversation，无需在此创建
      return;
    }
    appendMessage(convId, { role: 'user', content: question });
    const answerText =
      r.type === 'text' ? r.answer :
      r.type === 'error' ? `[错误] ${r.detail ?? r.reason ?? ''}` :
      r.type === 'number' ? String(r.data) :
      JSON.stringify(r.data ?? r.answer ?? '');
    appendMessage(convId, { role: 'assistant', content: answerText });
  };

  const handleError = (err: { code: string; message: string }) => {
    setError(err);
    setResult(null);
    setHomeState('HOME_ERROR');
  };

  const handleLoading = (loading: boolean) => {
    if (loading) {
      setHomeState('HOME_SUBMITTING');
      // Mock 路径由 AskBar 内部的 mockStreamAskData 驱动，不走 sendMessage（后端未就绪）
      // 非 Mock 路径才走 useStreamingChat 的 sendMessage
      if (!USE_MOCK) {
        const connId = connectionId ? Number(connectionId) : undefined;
        void sendMessage(lastQuestionRef.current, connId);
      } else {
        setMockStreamingContent('');
        setIsMockStreaming(true);
      }
    }
  };

  const handleExamplePick = (question: string) => {
    if (noConnection) {
      handleError({ code: 'NLQ_012', message: '暂无可用数据源，请先配置数据连接' });
      return;
    }
    setLastQuestion(question);
    lastQuestionRef.current = question;
    setHomeState('HOME_SUBMITTING');
    setResult(null);
    setError(null);
    import('../../api/search').then(({ askQuestion }) => {
      askQuestion({ question })
        .then((r) => void handleResult(r, question))
        .catch((err: unknown) => {
          if (err instanceof Error) {
            handleError({ code: (err as { code?: string }).code || 'UNKNOWN', message: err.message });
          } else {
            handleError({ code: 'UNKNOWN', message: String(err) });
          }
        });
    });
  };

  // AskBar 回调包装：拦截 onResult 注入 lastQuestion
  const handleAskBarResult = (r: SearchAnswer) => {
    setIsMockStreaming(false);
    void handleResult(r, lastQuestion);
  };

  const handleRegenerate = () => {
    const question = lastQuestionRef.current;
    if (!question || isStreaming) return;
    const connId = connectionId ? Number(connectionId) : undefined;
    void sendMessage(question, connId);
  };

  // ── 渲染 ──────────────────────────────────────────────────────────────────
  return (
    <div className="relative flex flex-col min-h-screen bg-white">

      {/* ScopePicker：所有非 offline 态显示 */}
      {homeState !== 'HOME_OFFLINE' && (
        <div className={[
          'w-full px-6',
          homeState === 'HOME_IDLE'
            ? 'pt-4 pb-2'
            : 'pt-4 pb-2 border-b border-slate-100',
        ].join(' ')}>
          <div className="max-w-3xl mx-auto">
            <ScopePicker variant={homeState === 'HOME_IDLE' ? 'idle' : 'default'} />
          </div>
        </div>
      )}

      {/* 主内容区：idle 态垂直居中，其他态顶部对齐 */}
      <main
        className={[
          'flex-1 flex flex-col w-full',
          homeState === 'HOME_IDLE' ? 'items-center justify-center' : '',
          'pb-40',
        ].join(' ')}
      >
        <div
          className={[
            'w-full max-w-4xl mx-auto px-6',
            homeState === 'HOME_IDLE' ? 'space-y-8' : 'pt-6 space-y-6',
          ].join(' ')}
        >

          {/* WelcomeHero：仅 idle 态展示 */}
          {homeState === 'HOME_IDLE' && <WelcomeHero />}

          {/* 离线提示 */}
          {homeState === 'HOME_OFFLINE' && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
              当前网络不可用，恢复后将继续显示上次状态。
            </div>
          )}

          {/* Gap-05: 消息展示区（真实 SSE 路径 + Mock 路径 + 历史恢复 统一由 MessageList 渲染） */}
          {(streamingMessages.length > 0 || isMockStreaming || mockStreamingContent || historyMessages.length > 0) && (
            <div className="flex-1 overflow-y-auto">
              <MessageList
                messages={streamingMessages}
                mockContent={mockStreamingContent}
                isMockStreaming={isMockStreaming}
                lastQuestion={lastQuestion}
                onRegenerate={handleRegenerate}
                historyMessages={historyMessages}
              />
            </div>
          )}

          {/* SearchResult（非流式路径，流式激活后完全隐藏） */}
          {homeState === 'HOME_RESULT' && result && !isStreaming && streamingMessages.length === 0 && !USE_MOCK && (
            <SearchResult
              result={result}
              onRetry={() => { if (lastQuestion) handleExamplePick(lastQuestion); }}
            />
          )}
          {homeState === 'HOME_ERROR' && error && !isStreaming && streamingMessages.length === 0 && (
            <SearchResult
              result={{
                type: 'error',
                answer: '',
                reason: error.code,
                detail: error.message,
              }}
              onRetry={() => { if (lastQuestion) handleExamplePick(lastQuestion); }}
            />
          )}

          {/* SuggestionGrid：仅 idle 态 */}
          {homeState === 'HOME_IDLE' && (
            <SuggestionGrid onPick={handleExamplePick} />
          )}

        </div>
      </main>

      {/* AskBar 固定底部容器 */}
      <div
        className="fixed bottom-0 right-0 z-20 pointer-events-none"
        style={{ left: 'var(--sidebar-width)', transition: 'left 300ms' }}
      >
        {/* 上缘渐变过渡条（纯装饰） */}
        <div className="h-3 w-full bg-gradient-to-t from-white to-white/0" aria-hidden="true" />
        {/* AskBar 实际容器 */}
        <div className="bg-white pt-2 pb-5 pointer-events-auto">
          <div className="max-w-3xl mx-auto px-6">
            <AskBar
              onResult={handleAskBarResult}
              onError={handleError}
              onLoading={(loading) => { handleLoading(loading); }}
              onQuestionChange={(q) => { setLastQuestion(q); lastQuestionRef.current = q; }}
              conversationId={currentConversationId ?? undefined}
              connectionId={connectionId}
              isStreaming={USE_MOCK ? isMockStreaming : isStreaming}
              onAbort={USE_MOCK ? () => { setIsMockStreaming(false); } : abort}
              useMock={USE_MOCK}
              onStreamToken={(token) => {
                setMockStreamingContent((prev) => prev + token);
              }}
            />
            <p className="mt-2 text-center text-[11px] text-slate-400">
              回答由 AI 生成，请核对关键数据后使用
            </p>
          </div>
        </div>
      </div>

      {/* 资产检查器抽屉 */}
      {hasPermission('tableau') && (
        <AssetInspectorDrawer
          assetId={assetId}
          tab={tab}
          onClose={closeAsset}
        />
      )}
    </div>
  );
}

export default function HomePage() {
  return (
    <ScopeProvider>
      <HomePageInner />
    </ScopeProvider>
  );
}
