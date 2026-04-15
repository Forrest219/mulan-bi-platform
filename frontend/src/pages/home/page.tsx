import { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { LOGO_URL } from '../../config';
import { AskBar } from './components/AskBar';
import { SearchResult } from './components/SearchResult';
import { ExamplePrompts } from './components/ExamplePrompts';
import type { SearchAnswer } from '../../api/search';

type Phase = 'idle' | 'loading' | 'showing_result' | 'showing_error';

export default function HomePage() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [result, setResult] = useState<SearchAnswer | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [lastQuestion, setLastQuestion] = useState('');
  const { user, isAdmin, hasPermission } = useAuth();

  const features = [
    { icon: 'ri-database-2-line', label: '数据库', path: '/governance/health', show: hasPermission('database_monitor') || isAdmin },
    { icon: 'ri-shield-check-line', label: 'DDL检查', path: '/dev/ddl-validator', show: hasPermission('ddl_check') || isAdmin },
    { icon: 'ri-settings-line', label: '规则配置', path: '/dev/rule-config', show: hasPermission('rule_config') || isAdmin },
    { icon: 'ri-user-settings-line', label: '用户管理', path: '/system/users', show: isAdmin },
    { icon: 'ri-group-line', label: '用户组', path: '/system/groups', show: isAdmin },
  ].filter(f => f.show);

  const handleResult = (r: SearchAnswer) => {
    setResult(r);
    setError(null);
    setPhase('showing_result');
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
    // Trigger AskBar submission
    import('./components/AskBar').then(() => {
      // Re-trigger by simulating submit
      setPhase('loading');
    });
    // Actually call the API directly
    import('../../api/search').then(({ askQuestion }) => {
      askQuestion({ question })
        .then(handleResult)
        .catch((err: Error) => handleError({ code: (err as { code?: string }).code || 'UNKNOWN', message: err.message }));
    });
  };

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return '☀️ 早上好';
    if (hour < 18) return '🌤️ 下午好';
    return '🌙 晚上好';
  };

  // ── Unauthenticated ──────────────────────────────────────────────────────
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

  // ── Authenticated ────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50">
      <div className="max-w-4xl mx-auto px-8 pt-16">

        {/* Welcome */}
        <div className="text-center mb-6">
          <h1 className="text-4xl font-bold text-slate-600">
            {getGreeting()}，{user?.display_name}
          </h1>
        </div>

        {/* AskBar */}
        <div className="mb-6">
          <AskBar
            onResult={handleResult}
            onError={handleError}
            onLoading={handleLoading}
          />
        </div>

        {/* Loading */}
        {phase === 'loading' && (
          <div className="flex justify-center py-8">
            <div className="flex items-center gap-3 text-slate-400 text-sm">
              <div className="w-5 h-5 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
              正在分析您的问题...
            </div>
          </div>
        )}

        {/* Result */}
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

        {/* Error */}
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

        {/* Example Prompts */}
        <div className="mb-8">
          <ExamplePrompts onPick={handleExamplePick} />
        </div>

        {/* Feature Icons */}
        <div className="flex justify-center items-center gap-6">
          {features.map((feature) => (
            <a
              key={feature.label}
              href={feature.path}
              className="flex flex-col items-center gap-1 group"
            >
              <div className="w-10 h-10 rounded-full bg-white/80 flex items-center justify-center group-hover:bg-white group-hover:shadow-sm transition-all">
                <i className={`${feature.icon} text-lg text-slate-400 group-hover:text-blue-500`} />
              </div>
              <span className="text-xs text-slate-400 group-hover:text-slate-600">{feature.label}</span>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
