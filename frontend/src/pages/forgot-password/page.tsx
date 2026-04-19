import { useState } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE, LOGO_URL } from '../../config';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/api/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email }),
      });

      if (response.status === 429) {
        setError('请求过于频繁，请稍后再试');
        setLoading(false);
        return;
      }

      const data = await response.json();

      if (!response.ok) {
        setError(data.detail || '请求失败，请重试');
        setLoading(false);
        return;
      }

      setSubmitted(true);
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

          {!submitted ? (
            <>
              <div className="mb-6">
                <h2 className="text-lg font-semibold text-slate-800 mb-1">忘记密码</h2>
                <p className="text-sm text-slate-500">输入账号邮箱，管理员将中转重置链接给您</p>
              </div>

              {error && (
                <div className="mb-4 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-red-600 text-sm">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1">
                    电子邮件
                  </label>
                  <input
                    type="email"
                    id="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                               text-slate-900 placeholder:text-slate-400 bg-white
                               focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                               transition-colors duration-150"
                    placeholder="请输入注册邮箱"
                  />
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-blue-700 hover:bg-blue-800 text-white font-medium
                             text-sm py-2.5 rounded-md transition-colors duration-150
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loading ? '提交中...' : '发送重置请求'}
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
            </>
          ) : (
            <>
              <div className="mb-6 text-center">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-emerald-50 mb-4">
                  <svg className="w-6 h-6 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <h2 className="text-lg font-semibold text-slate-800 mb-2">请求已提交</h2>
                <p className="text-sm text-slate-500">如果邮箱存在，已发送重置链接</p>
              </div>

              <Link
                to="/login"
                className="block w-full text-center bg-blue-700 hover:bg-blue-800 text-white font-medium
                           text-sm py-2.5 rounded-md transition-colors duration-150"
              >
                返回登录
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
