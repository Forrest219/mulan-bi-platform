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

const ROLE_COLOR: Record<string, string> = {
  admin: 'bg-violet-100 text-violet-700',
  data_admin: 'bg-blue-100 text-blue-700',
  analyst: 'bg-cyan-100 text-cyan-700',
  user: 'bg-slate-100 text-slate-600',
};

function resizeToBase64(file: File, maxSize = 128): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const ratio = Math.min(maxSize / img.width, maxSize / img.height, 1);
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * ratio);
        canvas.height = Math.round(img.height * ratio);
        canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/jpeg', 0.85));
      };
      img.onerror = reject;
      img.src = e.target?.result as string;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function AccountProfilePage() {
  const { user, updateUser } = useAuth();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [avatarUploading, setAvatarUploading] = useState(false);

  const [form, setForm] = useState({
    display_name: user?.display_name ?? '',
    position: user?.position ?? '',
    department: user?.department ?? '',
    phone: user?.phone ?? '',
  });
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);

  const avatarGradient = getAvatarGradient(user?.display_name ?? 'A');
  const initial = form.display_name?.charAt(0)?.toUpperCase() || user?.display_name?.charAt(0)?.toUpperCase() || 'A';
  const displayAvatar = avatarPreview ?? user?.avatar_url ?? null;

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    setAvatarPreview(prev => { if (prev) URL.revokeObjectURL(prev); return url; });
    setAvatarFile(file);
    e.target.value = '';
  };

  const handleSave = async () => {
    setSaving(true);
    setToast(null);
    try {
      let avatarUrl: string | undefined;
      if (avatarFile) {
        setAvatarUploading(true);
        avatarUrl = await resizeToBase64(avatarFile);
        setAvatarUploading(false);
      }
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          display_name: form.display_name || undefined,
          position: form.position || undefined,
          department: form.department || undefined,
          phone: form.phone || undefined,
          avatar_url: avatarUrl,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setToast({ type: 'error', msg: data.detail || '保存失败，请重试' });
        return;
      }
      updateUser(data);
      setAvatarFile(null);
      if (avatarPreview) { URL.revokeObjectURL(avatarPreview); setAvatarPreview(null); }
      setToast({ type: 'success', msg: '个人资料已更新' });
    } catch {
      setToast({ type: 'error', msg: '网络错误，请重试' });
    } finally {
      setSaving(false);
      setAvatarUploading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-3xl mx-auto">
          <h1 className="text-base font-semibold text-slate-900">个人中心</h1>
          <p className="text-xs text-slate-400 mt-0.5">查看和管理你的个人信息</p>
        </div>
      </div>
      <div className="px-8 py-7">
        <div className="max-w-3xl mx-auto">

      {toast && (
        <div className={`mb-3 px-3 py-2 rounded-md text-sm border ${
          toast.type === 'success'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-red-50 border-red-200 text-red-600'
        }`}>
          {toast.msg}
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden flex">

        {/* 左侧：身份面板 */}
        <div className="w-48 shrink-0 border-r border-slate-100 bg-slate-50/60 flex flex-col items-center py-6 px-4 gap-3">
          {/* 头像 */}
          <div className="relative group">
            {displayAvatar ? (
              <img src={displayAvatar} alt="头像"
                className="w-20 h-20 rounded-full object-cover ring-2 ring-slate-200" />
            ) : (
              <div className={`w-20 h-20 rounded-full bg-gradient-to-br ${avatarGradient} flex items-center justify-center ring-2 ring-slate-200`}>
                <span className="text-white text-3xl font-bold">{initial}</span>
              </div>
            )}
            {avatarUploading && (
              <div className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center">
                <i className="ri-loader-4-line text-white text-lg animate-spin" />
              </div>
            )}
            {!avatarUploading && (
              <button
                onClick={() => fileInputRef.current?.click()}
                className="absolute inset-0 rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
                aria-label="更换头像"
              >
                <i className="ri-camera-line text-white text-lg" />
              </button>
            )}
          </div>

          <div className="text-center">
            <p className="text-sm font-semibold text-slate-800 leading-snug">{form.display_name || user?.display_name}</p>
            <p className="text-[11px] text-slate-400 mt-0.5">@{user?.username}</p>
          </div>

          <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${ROLE_COLOR[user?.role ?? 'user'] ?? 'bg-slate-100 text-slate-600'}`}>
            {ROLE_LABEL[user?.role ?? ''] ?? user?.role}
          </span>

          <button
            onClick={() => fileInputRef.current?.click()}
            className="text-[11px] text-blue-500 hover:text-blue-600 transition-colors"
          >
            更换头像
          </button>
          <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
        </div>

        {/* 右侧：表单 */}
        <div className="flex-1 flex flex-col p-5">
          <div className="flex-1 space-y-2.5">
            <LockedField label="账号 ID" value={user?.username ?? '—'} />

            <Field label="姓名" required>
              <input type="text" value={form.display_name}
                onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))}
                className={INPUT_CLS} placeholder="请输入姓名" />
            </Field>

            <Field label="职位">
              <input type="text" value={form.position}
                onChange={e => setForm(f => ({ ...f, position: e.target.value }))}
                className={INPUT_CLS} placeholder="如：BI 总监" />
            </Field>

            <Field label="所属部门">
              <input type="text" value={form.department}
                onChange={e => setForm(f => ({ ...f, department: e.target.value }))}
                className={INPUT_CLS} placeholder="如：BI 中心" />
            </Field>

            <ReadOnlyField label="系统角色" value={ROLE_LABEL[user?.role ?? ''] ?? user?.role ?? '—'} />

            <ReadOnlyField
              label="注册时间"
              value={user?.created_at ? new Date(user.created_at).toLocaleDateString('zh-CN') : '—'}
            />

            <div className="border-t border-slate-100 my-1" />

            <Field label="手机号">
              <input type="tel" value={form.phone}
                onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                className={INPUT_CLS} placeholder="请输入手机号" />
            </Field>

            {/* 企业邮箱只读 */}
            <div className="flex items-center gap-3">
              <span className="text-sm text-slate-500 w-16 shrink-0 text-right">企业邮箱</span>
              <div className="flex-1 flex items-center gap-2">
                <span className="flex-1 text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-md px-3 py-1.5 select-none truncate">
                  {user?.email ?? '—'}
                </span>
                <div className="relative group shrink-0">
                  <i className="ri-information-line text-slate-400 text-base cursor-default" />
                  <div className="absolute right-0 bottom-full mb-2 px-2.5 py-1.5 bg-slate-700 text-white text-[11px] rounded-md leading-snug opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                    如需修改请联系管理员
                    <span className="absolute top-full right-2.5 border-4 border-transparent border-t-slate-700" />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 保存按钮 */}
          <div className="flex justify-end pt-4 mt-3 border-t border-slate-100">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? (
                <span className="flex items-center gap-1.5">
                  <i className="ri-loader-4-line animate-spin text-sm" />
                  保存中…
                </span>
              ) : '保存修改'}
            </button>
          </div>
        </div>
      </div>
        </div>
      </div>
    </div>
  );
}

const INPUT_CLS =
  'w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 bg-white ' +
  'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 transition-colors duration-150';

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <label className="text-sm text-slate-500 w-16 shrink-0 text-right">
        {label}{required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-slate-500 w-16 shrink-0 text-right">{label}</span>
      <span className="flex-1 text-sm text-slate-400 px-3 py-1.5">{value}</span>
    </div>
  );
}

function LockedField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-slate-500 w-16 shrink-0 text-right">{label}</span>
      <div className="flex-1 flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-md px-3 py-1.5">
        <i className="ri-lock-2-line text-slate-400 text-xs shrink-0" />
        <span className="text-sm text-slate-500 font-mono select-none">{value}</span>
      </div>
    </div>
  );
}
