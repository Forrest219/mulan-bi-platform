import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { usePlatformSettings } from '../../context/PlatformSettingsContext';
import { API_BASE } from '../../config';

type LoginStep = 'credentials' | 'mfa';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, checkAuth } = useAuth();
  const { settings } = usePlatformSettings();

  const [step, setStep] = useState<LoginStep>('credentials');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [mfaCode, setMfaCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleCredentials = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    const result = await login(username, password);

    if (result.mfa_required) {
      setStep('mfa');
      setLoading(false);
      return;
    }

    if (result.success) {
      navigate('/');
    } else {
      setError(typeof result.message === 'string' ? result.message : '登录失败，请重试');
    }
    setLoading(false);
  };

  const handleMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/api/auth/mfa/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ code: mfaCode }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.detail || 'MFA 验证码不正确');
        setLoading(false);
        return;
      }

      // Gap-06 修复：MFA 验证通过后先刷新 AuthContext，再跳转
      // 否则首页仍显示未登录状态（需手动刷新）
      await checkAuth();
      navigate('/');
    } catch {
      setError('网络错误，请重试');
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md">

        {/* Logo 区 */}
        <div className="flex flex-col items-start mb-6">
          <img
            src={settings.logo_url}
            alt={`${settings.platform_name} Logo`}
            className="w-12 h-12 object-contain mb-3"
          />
          <h1 className="text-xl font-semibold text-slate-900 mb-1">{settings.platform_name}</h1>
          <p className="text-sm text-slate-600">{settings.platform_subtitle}</p>
        </div>

        {/* 卡片 */}
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8">

          {/* 错误提示 */}
          {typeof error === 'string' && error && (
            <div className="mb-4 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-red-600 text-sm">
              {error}
            </div>
          )}

          {/* 步骤 1：凭证 */}
          {step === 'credentials' && (
            <form onSubmit={handleCredentials} className="space-y-4">
              <div>
                <label htmlFor="username" className="block text-sm font-medium text-slate-700 mb-1">
                  用户名
                </label>
                <input
                  type="text"
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                             text-slate-900 placeholder:text-slate-400 bg-white
                             focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                             transition-colors duration-150"
                  placeholder="请输入用户名"
                />
              </div>

              <div>
                <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-1">
                  密码
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    id="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    className="w-full pr-10 rounded-md border border-slate-300 px-3 py-2 text-sm
                               text-slate-900 placeholder:text-slate-400 bg-white
                               focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                               transition-colors duration-150"
                    placeholder="请输入密码"
                  />
                  <button
                    type="button"
                    aria-label="切换密码显示"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400
                               hover:text-slate-600 focus:outline-none"
                  >
                    {showPassword ? (
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.542-7 1.274-4.057 5.064-7 9.542-7 1.54 0 2.97.354 4.236.968M14.932 9.068a3 3 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M1.39 1.39l21.22 21.22" />
                      </svg>
                    ) : (
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              <div className="flex justify-end">
                {/* 忘记密码使用 Link，不使用原生 <a href>（CLAUDE.md 陷阱 3） */}
                <Link
                  to="/forgot-password"
                  className="text-sm text-blue-600 hover:text-blue-700 transition-colors duration-150"
                >
                  忘记密码？
                </Link>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-blue-700 hover:bg-blue-800 text-white font-medium
                           text-sm py-2.5 rounded-md transition-colors duration-150
                           disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? '登录中...' : '登录'}
              </button>

              <div className="text-center">
                <Link
                  to="/register"
                  className="text-sm text-blue-600 hover:text-blue-700 transition-colors duration-150"
                >
                  注册新账号
                </Link>
              </div>
            </form>
          )}

          {/* 步骤 2：MFA 验证 */}
          {step === 'mfa' && (
            <form onSubmit={handleMfa} className="space-y-4">
              <div className="text-center mb-2">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-blue-50 mb-3">
                  <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                </div>
                <h2 className="text-base font-semibold text-slate-900">MFA 身份验证</h2>
                <p className="text-sm text-slate-500 mt-1">请输入认证器 App 中的 6 位验证码</p>
              </div>

              <div>
                <label htmlFor="mfaCode" className="block text-sm font-medium text-slate-700 mb-1">
                  验证码
                </label>
                <input
                  type="text"
                  id="mfaCode"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  maxLength={6}
                  required
                  autoFocus
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                             text-slate-900 placeholder:text-slate-400 bg-white text-center
                             tracking-widest font-mono
                             focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                             transition-colors duration-150"
                  placeholder="000000"
                />
              </div>

              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => { setStep('credentials'); setMfaCode(''); setError(''); }}
                  className="flex-1 bg-white border border-slate-300 text-slate-700 hover:bg-slate-50
                             font-medium text-sm py-2.5 rounded-md transition-colors duration-150"
                >
                  返回
                </button>
                <button
                  type="submit"
                  disabled={loading || mfaCode.length !== 6}
                  className="flex-1 bg-blue-700 hover:bg-blue-800 text-white font-medium
                             text-sm py-2.5 rounded-md transition-colors duration-150
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loading ? '验证中...' : '验证'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
