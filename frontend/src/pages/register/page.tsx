import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { API_BASE, LOGO_URL } from '../../config';

export default function RegisterPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const togglePasswordVisibility = () => {
    setShowPassword(!showPassword);
  };

  const toggleConfirmPasswordVisibility = () => {
    setShowConfirmPassword(!showConfirmPassword);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!username.trim()) { setError('请输入用户名'); return; }
    if (!password) { setError('请输入密码'); return; }
    if (password !== confirmPassword) { setError('两次输入的密码不一致'); return; }
    if (password.length < 6) { setError('密码长度至少为6位'); return; }

    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          username,
          password,
          display_name: username
        })
      });

      if (response.ok) {
        navigate('/');
      } else {
        const data = await response.json();
        setError(data.detail || '注册失败');
      }
    } catch (_err) {
      setError('网络错误，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white p-8 rounded-lg shadow-md w-full max-w-sm">

        {/* Logo */}
        <div className="text-center mb-6">
          <img
            src={LOGO_URL}
            alt="Mulan Platform Logo"
            className="mx-auto h-10 w-auto"
          />
        </div>

        {/* Title and Subtitle */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-800 mb-2">注册账号</h1>
          <p className="text-sm text-gray-600">加入 Mulan Platform</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">
              {error}
            </div>
          )}

          {/* Username Field */}
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-800 mb-2">
              用户名
            </label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="block w-full px-4 py-3 border border-gray-300 rounded-md shadow-sm
                         placeholder-gray-600 text-gray-800
                         focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-600
                         sm:text-sm"
              placeholder="请输入用户名"
              required
            />
          </div>

          {/* Password Field with Show/Hide Toggle */}
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-800 mb-2">
              密码
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="block w-full pr-10 px-4 py-3 border border-gray-300 rounded-md shadow-sm
                           placeholder-gray-600 text-gray-800
                           focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-600
                           sm:text-sm"
                placeholder="至少6位"
                required
              />
              <button
                type="button"
                aria-label="Toggle password visibility"
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700
                           focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-600 rounded-r-md"
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

          {/* Confirm Password Field with Show/Hide Toggle */}
          <div>
            <label htmlFor="confirm-password" className="block text-sm font-medium text-gray-800 mb-2">
              确认密码
            </label>
            <div className="relative">
              <input
                type={showConfirmPassword ? 'text' : 'password'}
                id="confirm-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="block w-full pr-10 px-4 py-3 border border-gray-300 rounded-md shadow-sm
                           placeholder-gray-600 text-gray-800
                           focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-600
                           sm:text-sm"
                placeholder="再次输入密码"
                required
              />
              <button
                type="button"
                aria-label="Toggle password visibility"
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700
                           focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-600 rounded-r-md"
                onClick={toggleConfirmPasswordVisibility}
              >
                {showConfirmPassword ? (
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

          {/* Register Button */}
          <button
            type="submit"
            disabled={loading}
            className={`w-full flex justify-center py-3 px-6 border border-transparent rounded-md shadow-sm
                       text-base font-medium text-white bg-gray-900 hover:bg-gray-800
                       focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-600
                       ${loading ? 'bg-slate-100 text-slate-400 cursor-not-allowed' : ''}`}
          >
            {loading ? '注册中...' : '注册'}
          </button>
        </form>

        {/* Login Link */}
        <div className="mt-6 text-center">
          <p className="text-sm text-gray-600">
            已有账号？
            <Link
              to="/login"
              className="font-medium text-blue-600 hover:text-blue-500 underline
                         focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-600"
            >
              去登录
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
