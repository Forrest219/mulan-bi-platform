import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValidEmail) return;
    setLoading(true);
    try {
      await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
    } finally {
      setLoading(false);
      setSubmitted(true);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50">
      <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8 w-full max-w-md">
        <h1 className="text-xl font-semibold text-slate-900 mb-1">重置密码</h1>
        <p className="text-sm text-slate-500 mb-6">输入您的账号邮箱，我们将发送重置说明。</p>

        {submitted ? (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg p-4 text-sm mb-6">
            我们已向您的邮箱发送重置说明，请查收。
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">邮箱地址</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500"
              />
            </div>
            <button
              type="submit"
              disabled={!isValidEmail || loading}
              className="w-full py-2.5 bg-blue-700 hover:bg-blue-800 disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-lg text-sm font-medium transition-colors"
            >
              {loading ? '提交中...' : '提交'}
            </button>
          </form>
        )}

        <button
          onClick={() => navigate('/login')}
          className="mt-4 text-sm text-blue-600 hover:text-blue-700 transition-colors"
        >
          ← 返回登录
        </button>
      </div>
    </div>
  );
}
