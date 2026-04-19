import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { API_BASE, LOGO_URL } from '../../config';

interface PasswordRule {
  label: string;
  test: (pw: string) => boolean;
}

const PASSWORD_RULES: PasswordRule[] = [
  { label: '至少 8 个字符', test: (pw) => pw.length >= 8 },
  { label: '包含大写字母', test: (pw) => /[A-Z]/.test(pw) },
  { label: '包含小写字母', test: (pw) => /[a-z]/.test(pw) },
  { label: '包含数字', test: (pw) => /\d/.test(pw) },
];

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const tokenFromUrl = searchParams.get('token') ?? '';

  const [token, setToken] = useState(tokenFromUrl);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const passwordValid = PASSWORD_RULES.every((r) => r.test(newPassword));
  const passwordsMatch = newPassword === confirmPassword && confirmPassword.length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!passwordValid) {
      setError('密码不符合复杂度要求');
      return;
    }

    if (!passwordsMatch) {
      setError('两次输入的密码不一致');
      return;
    }

    if (!token.trim()) {
      setError('请输入重置 Token');
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/api/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token.trim(), new_password: newPassword }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.detail || '重置失败，请检查 Token 是否有效');
        setLoading(false);
        return;
      }

      navigate('/login', { state: { successMessage: '密码已重置，请使用新密码登录' } });
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
            src={LOGO_URL}
            alt="Mulan Platform Logo"
            className="w-12 h-12 object-contain mb-3"
          />
          <h1 className="text-xl font-semibold text-slate-900 mb-1">Mulan Platform</h1>
          <p className="text-sm text-slate-600">数据建模与治理平台</p>
        </div>

        {/* 卡片 */}
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8">
          <div className="mb-6">
            <h2 className="text-lg font-semibold text-slate-800 mb-1">重置密码</h2>
            <p className="text-sm text-slate-500">输入管理员提供的重置 Token 和新密码</p>
          </div>

          {error && (
            <div className="mb-4 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-red-600 text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* 重置 Token 输入（URL 有参数时预填） */}
            <div>
              <label htmlFor="token" className="block text-sm font-medium text-slate-700 mb-1">
                重置 Token
              </label>
              <input
                type="text"
                id="token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                required
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                           text-slate-900 placeholder:text-slate-400 bg-white font-mono
                           focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                           transition-colors duration-150"
                placeholder="请输入管理员提供的重置 Token"
              />
            </div>

            {/* 新密码 */}
            <div>
              <label htmlFor="newPassword" className="block text-sm font-medium text-slate-700 mb-1">
                新密码
              </label>
              <input
                type="password"
                id="newPassword"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                           text-slate-900 placeholder:text-slate-400 bg-white
                           focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                           transition-colors duration-150"
                placeholder="请输入新密码"
              />

              {/* 密码强度实时提示 */}
              {newPassword.length > 0 && (
                <div className="mt-2 space-y-1">
                  {PASSWORD_RULES.map((rule) => {
                    const pass = rule.test(newPassword);
                    return (
                      <div key={rule.label} className="flex items-center gap-1.5">
                        {pass ? (
                          <svg className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                          </svg>
                        ) : (
                          <svg className="w-3.5 h-3.5 text-slate-300 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        )}
                        <span className={`text-xs ${pass ? 'text-emerald-600' : 'text-slate-400'}`}>
                          {rule.label}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 确认密码 */}
            <div>
              <label htmlFor="confirmPassword" className="block text-sm font-medium text-slate-700 mb-1">
                确认新密码
              </label>
              <input
                type="password"
                id="confirmPassword"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className={`w-full rounded-md border px-3 py-2 text-sm
                            text-slate-900 placeholder:text-slate-400 bg-white
                            focus:outline-none focus:ring-2 focus:border-blue-500
                            transition-colors duration-150 ${
                  confirmPassword.length > 0
                    ? passwordsMatch
                      ? 'border-emerald-400 focus:ring-emerald-500/30'
                      : 'border-red-300 focus:ring-red-500/30'
                    : 'border-slate-300 focus:ring-blue-500/30'
                }`}
                placeholder="再次输入新密码"
              />
              {confirmPassword.length > 0 && !passwordsMatch && (
                <p className="text-xs text-red-500 mt-1">两次输入的密码不一致</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading || !passwordValid || !passwordsMatch || !token.trim()}
              className="w-full bg-blue-700 hover:bg-blue-800 text-white font-medium
                         text-sm py-2.5 rounded-md transition-colors duration-150
                         disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? '重置中...' : '重置密码'}
            </button>
          </form>

          <div className="mt-4 text-center">
            <Link
              to="/login"
              className="text-sm text-blue-600 hover:text-blue-700 transition-colors duration-150"
            >
              返回登录
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
