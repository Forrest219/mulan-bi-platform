import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';

const API_BASE = 'http://localhost:8000';

export default function RegisterPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!email.trim()) { setError('请输入邮箱'); return; }
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
          email,
          password,
          display_name: email.split('@')[0]
        })
      });

      if (response.ok) {
        navigate('/');
      } else {
        const data = await response.json();
        setError(data.detail || '注册失败');
      }
    } catch (err) {
      setError('网络错误，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="bg-white rounded-xl border border-slate-200 p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <img
            src="https://public.readdy.ai/ai/img_res/d9bf8fa2-dfff-4c50-98cf-7b635309e7d6.png"
            alt="Mulan Platform Logo"
            className="w-12 h-12 object-contain mx-auto mb-3"
          />
          <h1 className="text-xl font-semibold text-slate-800">注册账号</h1>
          <p className="text-sm text-slate-400 mt-1">加入 Mulan Platform</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1.5">
              邮箱
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              placeholder="your@email.com"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1.5">
              密码
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              placeholder="至少6位"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1.5">
              确认密码
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              placeholder="再次输入密码"
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-all ${
              loading
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            }`}
          >
            {loading ? '注册中...' : '注册'}
          </button>
        </form>

        <div className="mt-6 text-center">
          <Link to="/login" className="text-sm text-blue-600 hover:text-blue-700">
            已有账号？去登录
          </Link>
        </div>
      </div>
    </div>
  );
}
