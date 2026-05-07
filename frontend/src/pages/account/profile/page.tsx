import { useRef, useState } from 'react';
import { useAuth } from '../../../context/AuthContext';
import { getAvatarGradient } from '../../../config';
import { API_BASE } from '../../../config';

const ROLE_LABEL: Record<string, string> = {
  admin: '系统管理员',
  data_admin: '数据管理员',
  analyst: '分析师',
  user: '普通用户',
};

export default function AccountProfilePage() {
  const { user, updateUser } = useAuth();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);

  const [form, setForm] = useState({
    display_name: user?.display_name ?? '',
    position: user?.position ?? '',
    department: user?.department ?? '',
    email: user?.email ?? '',
    phone: user?.phone ?? '',
  });
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);

  const avatarGradient = getAvatarGradient(user?.display_name ?? 'A');
  const initial = form.display_name?.charAt(0)?.toUpperCase() || user?.display_name?.charAt(0)?.toUpperCase() || 'A';

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    setAvatarPreview(prev => { if (prev) URL.revokeObjectURL(prev); return url; });
    e.target.value = '';
  };

  const handleSave = async () => {
    setSaving(true);
    setToast(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          display_name: form.display_name || undefined,
          position: form.position || undefined,
          department: form.department || undefined,
          email: form.email || undefined,
          phone: form.phone || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setToast({ type: 'error', msg: data.detail || '保存失败，请重试' });
        return;
      }
      updateUser(data);
      setToast({ type: 'success', msg: '个人信息已保存' });
    } catch {
      setToast({ type: 'error', msg: '网络错误，请重试' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      <h1 className="text-lg font-semibold text-slate-900 mb-1">个人中心</h1>
      <p className="text-sm text-slate-500 mb-6">查看和管理你的个人信息</p>

      {toast && (
        <div className={`mb-4 px-3 py-2 rounded-md text-sm border ${
          toast.type === 'success'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-red-50 border-red-200 text-red-600'
        }`}>
          {toast.msg}
        </div>
      )}

      {/* 基本信息 */}
      <div className="bg-white border border-slate-200 rounded-lg p-6 mb-4">
        <h2 className="text-sm font-semibold text-slate-700 mb-5">基本信息</h2>

        {/* 头像 */}
        <div className="flex items-center gap-5 mb-6 pb-6 border-b border-slate-100">
          <div className="relative group shrink-0">
            {avatarPreview ? (
              <img
                src={avatarPreview}
                alt="头像预览"
                className="w-16 h-16 rounded-full object-cover ring-2 ring-slate-200"
              />
            ) : (
              <div className={`w-16 h-16 rounded-full bg-gradient-to-br ${avatarGradient} flex items-center justify-center ring-2 ring-slate-200`}>
                <span className="text-white text-2xl font-bold">{initial}</span>
              </div>
            )}
            <button
              onClick={() => fileInputRef.current?.click()}
              className="absolute inset-0 rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
              aria-label="更换头像"
            >
              <i className="ri-camera-line text-white text-lg" />
            </button>
          </div>
          <div>
            <p className="text-sm font-medium text-slate-800">{form.display_name || user?.display_name}</p>
            <p className="text-xs text-slate-400 mt-0.5">{user?.username}</p>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="mt-2 text-xs text-blue-600 hover:text-blue-700 transition-colors"
            >
              更换头像
            </button>
          </div>
          <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
        </div>

        {/* 可编辑字段 */}
        <div className="space-y-4">
          <Field label="姓名" required>
            <input
              type="text"
              value={form.display_name}
              onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))}
              className={INPUT_CLS}
              placeholder="请输入姓名"
            />
          </Field>
          <Field label="职位">
            <input
              type="text"
              value={form.position}
              onChange={e => setForm(f => ({ ...f, position: e.target.value }))}
              className={INPUT_CLS}
              placeholder="如：BI 总监"
            />
          </Field>
          <Field label="所属部门">
            <input
              type="text"
              value={form.department}
              onChange={e => setForm(f => ({ ...f, department: e.target.value }))}
              className={INPUT_CLS}
              placeholder="如：BI 中心"
            />
          </Field>
          <ReadOnlyField label="系统角色" value={ROLE_LABEL[user?.role ?? ''] ?? user?.role ?? '—'} />
          <ReadOnlyField
            label="注册时间"
            value={user?.created_at ? new Date(user.created_at).toLocaleDateString('zh-CN') : '—'}
          />
        </div>
      </div>

      {/* 联系方式 */}
      <div className="bg-white border border-slate-200 rounded-lg p-6 mb-6">
        <h2 className="text-sm font-semibold text-slate-700 mb-5">联系方式</h2>
        <div className="space-y-4">
          <Field label="手机号">
            <input
              type="tel"
              value={form.phone}
              onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
              className={INPUT_CLS}
              placeholder="请输入手机号"
            />
          </Field>
          <Field label="企业邮箱" required>
            <input
              type="email"
              value={form.email}
              onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              className={INPUT_CLS}
              placeholder="请输入企业邮箱"
            />
          </Field>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? '保存中…' : '保存修改'}
        </button>
      </div>
    </div>
  );
}

const INPUT_CLS =
  'w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 bg-white ' +
  'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 transition-colors duration-150';

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-4">
      <label className="text-sm text-slate-500 w-20 shrink-0 text-right">
        {label}{required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-4">
      <span className="text-sm text-slate-500 w-20 shrink-0 text-right">{label}</span>
      <span className="flex-1 text-sm text-slate-400 px-3 py-2">{value}</span>
    </div>
  );
}
