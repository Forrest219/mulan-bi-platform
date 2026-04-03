import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { LOGO_URL } from '../../config';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    const result = await login(username, password);

    if (result.success) {
      navigate('/');
    } else {
      setError(result.message);
    }
    setLoading(false);
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
            <a
              href="/forgot-password"
              className="text-sm font-medium text-blue-600 hover:text-blue-700
                         focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-white rounded-md"
            >
              忘记密码？
            </a>
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
