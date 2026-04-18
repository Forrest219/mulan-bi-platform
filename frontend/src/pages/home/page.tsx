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
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { LOGO_URL } from '../../config';
import { AskBar } from './components/AskBar';
import { SearchResult } from './components/SearchResult';
import { WelcomeHero } from './components/WelcomeHero';
import { SuggestionGrid } from './components/SuggestionGrid';
import { useConversations } from '../../store/conversationStore';
import type { SearchAnswer } from '../../api/search';
import { ScopeProvider } from './context/ScopeContext';
import { ScopePicker } from './components/ScopePicker';
import { AssetInspectorDrawer } from './components/AssetInspectorDrawer';
import { useHomeUrlState } from './hooks/useHomeUrlState';
// Gap-05: SSE streaming hook — state 与 AskBar 完全隔离（§11 陷阱6）
import { useStreamingChat } from '../../hooks/useStreamingChat';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type HomeUiState = 'HOME_IDLE' | 'HOME_SUBMITTING' | 'HOME_RESULT' | 'HOME_ERROR' | 'HOME_OFFLINE';

function HomePageInner() {
  const [homeState, setHomeState] = useState<HomeUiState>('HOME_IDLE');
  const stateBeforeOfflineRef = useRef<HomeUiState>('HOME_IDLE');
  const [result, setResult] = useState<SearchAnswer | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [lastQuestion, setLastQuestion] = useState('');
  const lastQuestionRef = useRef('');
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);

  const { user, hasPermission } = useAuth();
  const { addConversation, appendMessage } = useConversations();
  const { assetId, tab, connectionId, closeAsset, openAsset } = useHomeUrlState();

  // Gap-05: streaming state 完全独立，不与 AskBar 的 input/loading state 共享
  const { messages: streamingMessages, isStreaming, sendMessage } = useStreamingChat();

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
    let convId = currentConversationId;
    if (!convId) {
      convId = await addConversation();
      setCurrentConversationId(convId);
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
      // Gap-05: 使用 ref 同步读取最新问题（state 更新是异步的，ref 在同一 tick 已更新）
      const connId = connectionId ? Number(connectionId) : undefined;
      void sendMessage(lastQuestionRef.current, connId);
    }
  };

  const handleExamplePick = (question: string) => {
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
    void handleResult(r, lastQuestion);
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
            'w-full max-w-3xl mx-auto px-6',
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

          {/* Gap-05: SSE 流式消息展示区 */}
          {streamingMessages.length > 0 && (
            <div className="space-y-3">
              {streamingMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-slate-100 text-slate-700 ml-8'
                      : 'bg-white border border-slate-200 text-slate-800'
                  }`}
                >
                  {msg.role === 'assistant' && msg.isStreaming && !msg.content && (
                    <span className="inline-flex items-center gap-1.5 text-slate-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:0ms]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:150ms]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:300ms]" />
                    </span>
                  )}
                  {msg.content && (
                    <div className={msg.role === 'assistant' ? 'prose prose-sm max-w-none prose-slate' : ''}>
                      {msg.role === 'assistant' ? (
                        <>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                          {msg.isStreaming && (
                            <span className="inline-block w-0.5 h-4 ml-0.5 bg-slate-600 animate-pulse align-text-bottom" />
                          )}
                        </>
                      ) : (
                        <span className="whitespace-pre-wrap">
                          {msg.content}
                          {msg.isStreaming && (
                            <span className="inline-block w-0.5 h-4 ml-0.5 bg-slate-600 animate-pulse align-text-bottom" />
                          )}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* SearchResult（非流式路径） */}
          {homeState === 'HOME_RESULT' && result && !isStreaming && (
            <SearchResult
              result={result}
              onRetry={() => { if (lastQuestion) handleExamplePick(lastQuestion); }}
            />
          )}
          {homeState === 'HOME_ERROR' && error && !isStreaming && (
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

          {/* Loading 指示器（流式内容尚未开始时） */}
          {homeState === 'HOME_SUBMITTING' && streamingMessages.length === 0 && (
            <div className="flex justify-center py-6">
              <div className="flex items-center gap-3 text-slate-400 text-sm">
                <div className="w-5 h-5 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
                正在分析您的问题...
              </div>
            </div>
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
        style={{ left: 'var(--conv-bar-w)', transition: 'left 200ms' }}
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
