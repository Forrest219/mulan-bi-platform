import { useState } from 'react';
import { API_BASE } from '../../../config';

export default function AccountPasswordForm() {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [toastMsg, setToastMsg] = useState('');

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(''), 3000);
  };

  const validate = (): string => {
    if (!oldPassword) return '请输入当前密码';
    if (newPassword.length < 8) return '新密码长度不能少于 8 位';
    if (newPassword !== confirmPassword) return '两次输入的新密码不一致';
    return '';
  };

  const toggleShow = (key: 'old' | 'new' | 'confirm') => {
    if (key === 'old') setShowOld(o => !o);
    if (key === 'new') setShowNew(n => !n);
    if (key === 'confirm') setShowConfirm(c => !c);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/change-password`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || '密码修改失败，请重试');
        setLoading(false);
        return;
      }
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      showToast('密码修改成功');
    } catch {
      setError('网络错误，请重试');
    }
    setLoading(false);
  };

  return (
    <>
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
            </svg>
          </div>
          <div className="flex-1">
            <h2 className="text-base font-semibold text-slate-900 mb-1">账户密码</h2>
            <p className="text-sm text-slate-500 mb-4">
              建议使用至少 8 位、包含字母和数字的强密码。
            </p>

            {error && (
              <div className="mb-4 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-red-600 text-sm">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="old-password" className="block text-sm font-medium text-slate-700 mb-1">
                  当前密码
                </label>
                <div className="relative">
                  <input
                    type={showOld ? 'text' : 'password'}
                    id="old-password"
                    value={oldPassword}
                    onChange={(e) => setOldPassword(e.target.value)}
                    required
                    autoFocus
                    className="w-full rounded-md border border-slate-300 px-3 py-2 pr-10 text-sm
                               text-slate-900 placeholder:text-slate-400 bg-white
                               focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                               transition-colors duration-150"
                    placeholder="请输入当前密码"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShow('old')}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                    aria-label={showOld ? '隐藏密码' : '显示密码'}
                  >
                    <i className={showOld ? 'ri-eye-off-line text-base' : 'ri-eye-line text-base'} />
                  </button>
                </div>
              </div>

              <div>
                <label htmlFor="new-password" className="block text-sm font-medium text-slate-700 mb-1">
                  新密码
                </label>
                <div className="relative">
                  <input
                    type={showNew ? 'text' : 'password'}
                    id="new-password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    className="w-full rounded-md border border-slate-300 px-3 py-2 pr-10 text-sm
                               text-slate-900 placeholder:text-slate-400 bg-white
                               focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                               transition-colors duration-150"
                    placeholder="至少 8 位"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShow('new')}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                    aria-label={showNew ? '隐藏密码' : '显示密码'}
                  >
                    <i className={showNew ? 'ri-eye-off-line text-base' : 'ri-eye-line text-base'} />
                  </button>
                </div>
              </div>

              <div>
                <label htmlFor="confirm-password" className="block text-sm font-medium text-slate-700 mb-1">
                  确认新密码
                </label>
                <div className="relative">
                  <input
                    type={showConfirm ? 'text' : 'password'}
                    id="confirm-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    className="w-full rounded-md border border-slate-300 px-3 py-2 pr-10 text-sm
                               text-slate-900 placeholder:text-slate-400 bg-white
                               focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                               transition-colors duration-150"
                    placeholder="再次输入新密码"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShow('confirm')}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                    aria-label={showConfirm ? '隐藏密码' : '显示密码'}
                  >
                    <i className={showConfirm ? 'ri-eye-off-line text-base' : 'ri-eye-line text-base'} />
                  </button>
                </div>
              </div>

              <div className="pt-1">
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium
                             rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loading ? '保存中...' : '保存修改'}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
