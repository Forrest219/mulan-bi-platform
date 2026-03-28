import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
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

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="bg-white rounded-xl border border-slate-200 p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <img
            src="https://public.readdy.ai/ai/img_res/d9bf8fa2-dfff-4c50-98cf-7b635309e7d6.png"
            alt="Mulan Platform Logo"
            className="w-12 h-12 object-contain mx-auto mb-3"
          />
          <h1 className="text-xl font-semibold text-slate-800">Mulan Platform</h1>
          <p className="text-sm text-slate-400 mt-1">数据建模与治理平台</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1.5">
              用户名
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-slate-400 focus:ring-1 focus:ring-slate-400"
              placeholder="请输入用户名"
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
              className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-slate-400 focus:ring-1 focus:ring-slate-400"
              placeholder="请输入密码"
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-all ${
              loading
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : 'bg-slate-900 text-white hover:bg-slate-700'
            }`}
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>

        <div className="mt-6 text-center space-y-2">
          <Link to="/register" className="block text-sm text-blue-600 hover:text-blue-700">
            注册新账号
          </Link>
          <p className="text-xs text-slate-400">默认管理员: admin / admin123</p>
        </div>
      </div>
    </div>
  );
}
