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
import { useAuth } from '../../context/AuthContext';
import { LOGO_URL } from '../../config';
import { AskBar } from './components/AskBar';
import { SearchResult } from './components/SearchResult';
import { WelcomeHero } from './components/WelcomeHero';
import { SuggestionGrid } from './components/SuggestionGrid';
import { useConversations } from '../../store/conversationStore';
import type { SearchAnswer } from '../../api/search';

type HomeUiState = 'HOME_IDLE' | 'HOME_SUBMITTING' | 'HOME_RESULT' | 'HOME_ERROR' | 'HOME_OFFLINE';

export default function HomePage() {
  const [homeState, setHomeState] = useState<HomeUiState>('HOME_IDLE');
  const stateBeforeOfflineRef = useRef<HomeUiState>('HOME_IDLE');
  const [result, setResult] = useState<SearchAnswer | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [lastQuestion, setLastQuestion] = useState('');
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);

  const { user } = useAuth();
  const { addConversation, appendMessage } = useConversations();

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
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50 flex items-center justify-center">
        <div className="bg-white rounded-xl border border-slate-200 p-10 w-full max-w-md text-center">
          <img src={LOGO_URL} alt="Mulan Platform Logo" className="w-14 h-14 object-contain mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-slate-800 mb-2">Mulan Platform</h1>
          <p className="text-sm text-slate-400 mb-8">数据建模与治理平台</p>
          <p className="text-slate-500 mb-6">请先登录以访问平台功能</p>
          <a
            href="/login"
            className="inline-block w-full py-2.5 bg-slate-900 text-white rounded-lg text-sm font-semibold hover:bg-slate-700 transition-colors"
          >
            登录
          </a>
          <div className="mt-4">
            <a href="/register" className="text-sm text-blue-600 hover:text-blue-700">
              没有账号？去注册
            </a>
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
    }
  };

  const handleExamplePick = (question: string) => {
    setLastQuestion(question);
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
    <div className="min-h-screen">
      <div className="max-w-3xl mx-auto px-6 pb-36">

        {/* WelcomeHero（始终展示） */}
        <WelcomeHero />

        {homeState === 'HOME_OFFLINE' && (
          <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            当前网络不可用，恢复后将继续显示上次状态。
          </div>
        )}

        {/* SearchResult（有结果/错误时） */}
        {homeState === 'HOME_RESULT' && result && (
          <div className="mb-6">
            <SearchResult
              result={result}
              onRetry={() => {
                if (lastQuestion) handleExamplePick(lastQuestion);
              }}
            />
          </div>
        )}
        {homeState === 'HOME_ERROR' && error && (
          <div className="mb-6">
            <SearchResult
              result={{
                type: 'error',
                answer: '',
                reason: error.code,
                detail: error.message,
              }}
              onRetry={() => {
                if (lastQuestion) handleExamplePick(lastQuestion);
              }}
            />
          </div>
        )}

        {/* Loading */}
        {homeState === 'HOME_SUBMITTING' && (
          <div className="flex justify-center py-6">
            <div className="flex items-center gap-3 text-slate-400 text-sm">
              <div className="w-5 h-5 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
              正在分析您的问题...
            </div>
          </div>
        )}

        {/* AskBar（始终可用，C1） */}
        <div className="fixed bottom-0 left-0 right-0 border-t border-slate-200 bg-white/95 backdrop-blur z-20">
          <div className="max-w-3xl mx-auto px-6 py-4">
            <AskBar
              onResult={handleAskBarResult}
              onError={handleError}
              onLoading={(loading) => {
                handleLoading(loading);
              }}
              onQuestionChange={(q) => setLastQuestion(q)}
              conversationId={currentConversationId ?? undefined}
            />
          </div>
        </div>

        {/* SuggestionGrid（idle 态展示） */}
        {homeState === 'HOME_IDLE' && (
          <SuggestionGrid onPick={handleExamplePick} />
        )}

      </div>
    </div>
  );
}
