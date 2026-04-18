import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { API_BASE, LOGO_URL } from '../../config';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaLoading, setMfaLoading] = useState(false);
  const [mfaCode, setMfaCode] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    const result = await login(username, password);

    if (result.mfa_required) {
      // MFA enabled — show MFA code input step
      setMfaRequired(true);
      setLoading(false);
      return;
    }

    if (result.success) {
      navigate('/');
    } else {
      setError(result.message);
    }
    setLoading(false);
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setMfaLoading(true);

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
        setMfaLoading(false);
        return;
      }

      navigate('/');
    } catch {
      setError('网络错误，请重试');
    }
    setMfaLoading(false);
  };

  const handleBackToLogin = () => {
    setMfaRequired(false);
    setMfaCode('');
    setError('');
  };

  const togglePasswordVisibility = () => {
    setShowPassword(!showPassword);
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-lg shadow-md p-8 w-full max-w-md">

        {/* Card Header - 左对齐修复 */}
        <div className="flex flex-col items-start mb-6">
          <img
            src={LOGO_URL}
            alt="Mulan Platform Logo"
            className="w-12 h-12 object-contain mb-3"
          />
          <h1 className="text-xl font-semibold text-gray-900 mb-1">Mulan Platform</h1>
          <p className="text-sm text-gray-700">数据建模与治理平台</p>
        </div>

        {/* Step 1: Normal Login Form */}
        {!mfaRequired && (
          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">
                {error}
              </div>
            )}

            {/* Username Field */}
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-2">
                用户名
              </label>
              <input
                type="text"
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="block w-full px-4 py-2 border border-gray-400 rounded-md shadow-sm text-gray-900
                           placeholder:text-gray-600
                           focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
                           sm:text-sm"
                placeholder="请输入用户名"
                required
              />
            </div>

            {/* Password Field with Show/Hide Toggle */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-2">
                密码
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="block w-full pr-10 px-4 py-2 border border-gray-400 rounded-md shadow-sm text-gray-900
                             placeholder:text-gray-600
                             focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
                             sm:text-sm"
                  placeholder="请输入密码"
                  required
                />
                {/* Show/Hide Toggle Button */}
                <button
                  type="button"
                  aria-label="Toggle password visibility"
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-500 hover:text-gray-700
                             focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 rounded-r-md"
                  onClick={togglePasswordVisibility}
                >
                  {showPassword ? (
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.542-7 1.274-4.057 5.064-7 9.542-7 1.54 0 2.97.354 4.236.968M14.932 9.068a3 3 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M1.39 1.39l21.22 21.22" />
                    </svg>
                  ) : (
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            {/* Forgot Password Link */}
            <div className="flex justify-end mt-2 mb-4">
              <Link
                to="/forgot-password"
                className="text-sm font-medium text-blue-600 hover:text-blue-700
                           focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-white rounded-md"
              >
                忘记密码？
              </Link>
            </div>

            {/* Login Button */}
            <button
              type="submit"
              disabled={loading}
              className={`w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-base font-medium text-white bg-blue-700 hover:bg-blue-800
                         focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 focus:ring-offset-white
                         ${loading ? 'bg-slate-100 text-slate-400 cursor-not-allowed' : ''}`}
            >
              {loading ? '登录中...' : '登录'}
            </button>
          </form>
        )}

        {/* Step 2: MFA Verification */}
        {mfaRequired && (
          <form onSubmit={handleMfaSubmit} className="space-y-5">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">
                {error}
              </div>
            )}

            <div className="text-center mb-4">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-blue-100 mb-3">
                <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold text-gray-900">MFA 身份验证</h2>
              <p className="text-sm text-gray-500 mt-1">请输入 authenticator 应用中的验证码</p>
            </div>

            {/* MFA Code Field */}
            <div>
              <label htmlFor="mfaCode" className="block text-sm font-medium text-gray-700 mb-2">
                验证码
              </label>
              <input
                type="text"
                id="mfaCode"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className="block w-full px-4 py-2 border border-gray-400 rounded-md shadow-sm text-gray-900 text-center text-lg tracking-widest
                           placeholder:text-gray-400 placeholder:tracking-normal
                           focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
                           sm:text-sm"
                placeholder="000000"
                maxLength={6}
                required
                autoFocus
              />
            </div>

            {/* MFA Buttons */}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleBackToLogin}
                className="flex-1 flex justify-center py-2 px-4 border border-gray-400 rounded-md shadow-sm text-base font-medium text-gray-700 bg-white hover:bg-gray-50
                           focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                返回
              </button>
              <button
                type="submit"
                disabled={mfaLoading || mfaCode.length < 6}
                className={`flex-1 flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-base font-medium text-white bg-blue-700 hover:bg-blue-800
                           focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 focus:ring-offset-white
                           ${mfaLoading || mfaCode.length < 6 ? 'bg-slate-100 text-slate-400 cursor-not-allowed' : ''}`}
              >
                {mfaLoading ? '验证中...' : '验证'}
              </button>
            </div>
          </form>
        )}

        {/* Register Link */}
        <div className="mt-6 text-center">
          <Link
            to="/register"
            className="text-sm font-medium text-blue-600 hover:text-blue-700
                       focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-white rounded-md"
          >
            注册新账号
          </Link>
        </div>
      </div>
    </div>
  );
}
