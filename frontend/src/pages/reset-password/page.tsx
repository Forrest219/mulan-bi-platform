import { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token') || '';

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('重置链接无效或已过期，请重新发起密码重置请求。');
    }
  }, [token]);

  const isValidPassword = password.length >= 8;
  const isMatch = password === confirmPassword && confirmPassword.length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValidPassword || !isMatch || !token) return;

    setLoading(true);
    setMessage('');
    try {
      const res = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await res.json();
      if (res.ok) {
        setStatus('success');
        setMessage('密码重置成功，请使用新密码登录。');
        // 3 秒后跳转登录页
        setTimeout(() => navigate('/login'), 3000);
      } else {
        setStatus('error');
        setMessage(data.detail || '重置失败，请稍后重试。');
      }
    } catch {
      setStatus('error');
      setMessage('网络错误，请稍后重试。');
    } finally {
      setLoading(false);
    }
  };

  if (status === 'error' && !token) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-50">
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8 w-full max-w-md text-center">
          <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mx-auto mb-4">
            <i className="ri-error-warning-line text-2xl text-red-400" />
          </div>
          <h2 className="text-xl font-semibold text-slate-900 mb-2">链接无效</h2>
          <p className="text-sm text-slate-500 mb-6">{message}</p>
          <button
            onClick={() => navigate('/forgot-password')}
            className="px-4 py-2 bg-blue-700 hover:bg-blue-800 text-white text-sm font-medium rounded-lg transition-colors"
          >
            重新发起重置请求
          </button>
        </div>
      </div>
    );
  }

  if (status === 'success') {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-50">
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8 w-full max-w-md text-center">
          <div className="w-12 h-12 rounded-full bg-emerald-50 flex items-center justify-center mx-auto mb-4">
            <i className="ri-check-line text-2xl text-emerald-500" />
          </div>
          <h2 className="text-xl font-semibold text-slate-900 mb-2">密码重置成功</h2>
          <p className="text-sm text-slate-500 mb-6">{message}</p>
          <p className="text-xs text-slate-400">正在跳转至登录页…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50">
      <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8 w-full max-w-md">
        <h1 className="text-xl font-semibold text-slate-900 mb-1">设置新密码</h1>
        <p className="text-sm text-slate-500 mb-6">请输入您的新密码。</p>

        {status === 'error' && message && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4 text-sm mb-4">
            {message}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">新密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 8 位"
              minLength={8}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500"
            />
            {password.length > 0 && !isValidPassword && (
              <p className="text-xs text-red-500 mt-1">密码长度至少为 8 位</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">确认新密码</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="再次输入新密码"
              className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 ${
                confirmPassword.length > 0 && !isMatch
                  ? 'border-red-400 bg-red-50'
                  : 'border-slate-300'
              }`}
            />
            {confirmPassword.length > 0 && !isMatch && (
              <p className="text-xs text-red-500 mt-1">两次输入的密码不一致</p>
            )}
          </div>

          <button
            type="submit"
            disabled={!isValidPassword || !isMatch || loading || !token}
            className="w-full py-2.5 bg-blue-700 hover:bg-blue-800 disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-lg text-sm font-medium transition-colors"
          >
            {loading ? '提交中…' : '确认重置'}
          </button>
        </form>

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
