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
import { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { LOGO_URL } from '../../config';
import { AskBar } from './components/AskBar';
import { SearchResult } from './components/SearchResult';
import { WelcomeHero } from './components/WelcomeHero';
import { SuggestionGrid } from './components/SuggestionGrid';
import { useConversations } from '../../store/conversationStore';
import type { SearchAnswer } from '../../api/search';

type Phase = 'idle' | 'loading' | 'showing_result' | 'showing_error';

export default function HomePage() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [result, setResult] = useState<SearchAnswer | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [lastQuestion, setLastQuestion] = useState('');
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);

  const { user } = useAuth();
  const { addConversation, appendMessage } = useConversations();

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
    setPhase('showing_result');

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
    setPhase('showing_error');
  };

  const handleLoading = (loading: boolean) => {
    if (loading) setPhase('loading');
  };

  const handleExamplePick = (question: string) => {
    setLastQuestion(question);
    setPhase('loading');
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
      <div className="max-w-3xl mx-auto px-6 pb-16">

        {/* WelcomeHero（始终展示） */}
        <WelcomeHero />

        {/* SearchResult（有结果/错误时） */}
        {(phase === 'showing_result' || phase === 'showing_error') && result && (
          <div className="mb-6">
            <SearchResult
              result={result}
              onRetry={() => {
                if (lastQuestion) handleExamplePick(lastQuestion);
              }}
            />
          </div>
        )}
        {(phase === 'showing_error' || phase === 'showing_result') && error && (
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
        {phase === 'loading' && (
          <div className="flex justify-center py-6">
            <div className="flex items-center gap-3 text-slate-400 text-sm">
              <div className="w-5 h-5 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
              正在分析您的问题...
            </div>
          </div>
        )}

        {/* AskBar（始终可用，C1） */}
        <div className="mb-6">
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

        {/* SuggestionGrid（idle 态展示） */}
        {phase === 'idle' && (
          <SuggestionGrid onPick={handleExamplePick} />
        )}

      </div>
    </div>
  );
}
