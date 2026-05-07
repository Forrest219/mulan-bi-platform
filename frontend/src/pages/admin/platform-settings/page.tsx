/**
 * PlatformSettingsPage — /admin/platform-settings
 *
 * admin-only 平台设置管理页。
 *
 * 功能：
 * - 基础设置 Tab：平台名称、副标题、Logo URL、Favicon URL
 * - 邮件通知 Tab：SMTP 配置、测试邮件、发送记录
 * - 仅 admin 可见
 *
 * 后端 API：
 *   GET    /api/platform-settings          → PlatformSettings
 *   PUT    /api/platform-settings          → PlatformSettings
 *   GET    /api/platform-settings/smtp     → SmtpConfigResponse
 *   PUT    /api/platform-settings/smtp     → SmtpConfigResponse
 *   POST   /api/platform-settings/smtp/test → { success, message }
 *   GET    /api/platform-settings/email-logs → { items, total, page, page_size }
 */
import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../../../context/AuthContext';
import { usePlatformSettings } from '../../../context/PlatformSettingsContext';

/* =====================================================================
   基础设置
   ===================================================================== */

interface SettingsForm {
  platform_name: string;
  platform_subtitle: string;
  logo_url: string;
  favicon_url: string;
}

const LOGO_URL_RE = /^https?:\/\/.+/i;
const FORBIDDEN_LOGO_PATTERNS = ['httpbin.org/image', 'picsum.photos', 'via.placeholder.com', 'img.shields.io'];

function validateForm(form: SettingsForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.platform_name.trim()) {
    errors.platform_name = '平台名称不能为空';
  } else if (form.platform_name.length > 128) {
    errors.platform_name = '平台名称不能超过 128 字符';
  }
  if (!form.logo_url.trim()) {
    errors.logo_url = 'Logo URL 不能为空';
  } else if (!LOGO_URL_RE.test(form.logo_url.trim())) {
    errors.logo_url = 'Logo URL 必须是有效的 HTTP(S) URL';
  } else if (form.logo_url.length > 512) {
    errors.logo_url = 'Logo URL 不能超过 512 字符';
  } else if (FORBIDDEN_LOGO_PATTERNS.some(p => form.logo_url.includes(p))) {
    errors.logo_url = 'Logo URL 不能使用随机/占位图片服务';
  }
  if (form.platform_subtitle.length > 256) {
    errors.platform_subtitle = '平台副标题不能超过 256 字符';
  }
  if (form.favicon_url && !LOGO_URL_RE.test(form.favicon_url.trim())) {
    errors.favicon_url = 'Favicon URL 必须是有效的 HTTP(S) URL';
  } else if (form.favicon_url && form.favicon_url.length > 512) {
    errors.favicon_url = 'Favicon URL 不能超过 512 字符';
  }
  return errors;
}

function formatDate(isoStr: string): string {
  if (!isoStr) return '—';
  return new Date(isoStr).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

/* =====================================================================
   邮件通知
   ===================================================================== */

interface SmtpForm {
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password: string;
  smtp_from_addr: string;
  smtp_use_tls: boolean;
}

interface EmailLog {
  id: number;
  email_type: string;
  recipient: string;
  from_addr: string;
  subject: string;
  status: 'enqueued' | 'sent' | 'permanent_failed';
  error_detail: string | null;
  attempt_count: number;
  scheduled_at: string | null;
  sent_at: string | null;
  created_at: string;
}

const EMAIL_TYPE_LABELS: Record<string, string> = {
  password_reset: '密码重置',
  test_email: '测试邮件',
};

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  enqueued:         { label: '排队中',  color: 'bg-blue-100 text-blue-700' },
  sent:             { label: '已发送',  color: 'bg-emerald-100 text-emerald-700' },
  permanent_failed: { label: '失败',    color: 'bg-red-100 text-red-700' },
};

function validateSmtpForm(form: SmtpForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.smtp_host.trim()) errors.smtp_host = 'SMTP 主机不能为空';
  if (!form.smtp_port || form.smtp_port < 1 || form.smtp_port > 65535) {
    errors.smtp_port = '端口必须在 1-65535 之间';
  }
  if (!form.smtp_user.trim()) errors.smtp_user = '用户名不能为空';
  if (!form.smtp_from_addr.trim()) {
    errors.smtp_from_addr = '发件人地址不能为空';
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.smtp_from_addr)) {
    errors.smtp_from_addr = '发件人地址格式无效';
  }
  return errors;
}

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err?.detail;
    const msg = typeof detail === 'string'
      ? detail
      : detail != null && typeof detail === 'object'
        ? JSON.stringify(detail)
        : `请求失败 (${res.status})`;
    throw new Error(msg || `请求失败 (${res.status})`);
  }
  return res.json();
}

/* =====================================================================
   共用 UI 辅助
   ===================================================================== */

const CLS = (err?: string) =>
  `w-full rounded-md border px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 bg-white ` +
  `focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 transition-colors duration-150 ` +
  (err ? 'border-red-400 bg-red-50' : 'border-slate-300');

function Field({
  label, required, error, children,
}: {
  label: string; required?: boolean; error?: string; children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <label className="text-sm text-slate-500 w-20 shrink-0 text-right">
        {label}{required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      <div className="flex-1">
        {children}
        {error && <p className="text-xs text-red-500 mt-0.5">{error}</p>}
      </div>
    </div>
  );
}

/* ── 密码输入框（带显示/隐藏切换） ── */
function PasswordField({
  value, onChange, placeholder, className = '',
}: {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
  className?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <input
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className={`w-full px-3 py-1.5 pr-9 border rounded-md text-sm text-slate-800 bg-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 transition-colors ${className}`}
      />
      <button
        type="button"
        onClick={() => setVisible(v => !v)}
        className="absolute inset-y-0 right-2.5 flex items-center text-slate-400 hover:text-slate-600 transition"
        tabIndex={-1}
      >
        <i className={visible ? 'ri-eye-off-line' : 'ri-eye-line'} />
      </button>
    </div>
  );
}

/* =====================================================================
   页面组件
   ===================================================================== */

type TabKey = 'general' | 'email';

export default function PlatformSettingsPage() {
  const { isAdmin } = useAuth();
  const { settings, isLoading: settingsLoading, updateSettings, previewSettings } = usePlatformSettings();

  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get('tab') as TabKey | null) ?? 'general';
  const setActiveTab = (tab: TabKey) => setSearchParams({ tab }, { replace: true });

  /* ── 基础设置表单 ── */
  const [form, setForm] = useState<SettingsForm>({
    platform_name: '', platform_subtitle: '', logo_url: '', favicon_url: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [logoPreviewError, setLogoPreviewError] = useState(false);

  /* ── 邮件表单 ── */
  const [smtpForm, setSmtpForm] = useState<SmtpForm>({
    smtp_host: '', smtp_port: 465, smtp_user: '', smtp_password: '',
    smtp_from_addr: '', smtp_use_tls: true,
  });
  const [smtpErrors, setSmtpErrors] = useState<Record<string, string>>({});
  const [smtpLoading, setSmtpLoading] = useState(false);
  const [smtpSaveMsg, setSmtpSaveMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [smtpSaving, setSmtpSaving] = useState(false);
  const [testEmail, setTestEmail] = useState('');
  const [testSending, setTestSending] = useState(false);
  const [testMsg, setTestMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  /* ── 邮件日志 ── */
  const [emailLogs, setEmailLogs] = useState<EmailLog[]>([]);
  const [logsTotal, setLogsTotal] = useState(0);
  const [logsLoading, setLogsLoading] = useState(false);
  const [emailLogsError, setEmailLogsError] = useState<string | null>(null);

  useEffect(() => {
    if (!settingsLoading) {
      setForm({
        platform_name: settings.platform_name || '',
        platform_subtitle: settings.platform_subtitle || '',
        logo_url: settings.logo_url || '',
        favicon_url: settings.favicon_url || '',
      });
    }
  }, [settingsLoading, settings]);

  const loadSmtpConfig = useCallback(async () => {
    setSmtpLoading(true);
    setSmtpSaveMsg(null);
    try {
      const cfg = await apiFetch<{
        smtp_host: string; smtp_port: number; smtp_user: string;
        smtp_password: string; smtp_from_addr: string; smtp_use_tls: boolean;
      }>('/api/platform-settings/smtp');
      setSmtpForm({
        smtp_host: cfg.smtp_host || '',
        smtp_port: cfg.smtp_port || 465,
        smtp_user: cfg.smtp_user || '',
        smtp_password: '',
        smtp_from_addr: cfg.smtp_from_addr || '',
        smtp_use_tls: cfg.smtp_use_tls ?? true,
      });
      if (cfg.smtp_password && cfg.smtp_password !== '***') {
        setSmtpForm(prev => ({ ...prev, smtp_password: cfg.smtp_password }));
      }
    } catch (e) {
      setSmtpSaveMsg({ type: 'error', text: e instanceof Error ? e.message : '加载失败' });
    } finally {
      setSmtpLoading(false);
    }
  }, []);

  const loadEmailLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const data = await apiFetch<{ items: EmailLog[]; total: number }>(
        '/api/platform-settings/email-logs?page=1&page_size=50'
      );
      setEmailLogs(data.items || []);
      setLogsTotal(data.total || 0);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setEmailLogsError(msg || '加载失败');
    } finally {
      setLogsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'email') {
      loadSmtpConfig();
      loadEmailLogs();
    }
  }, [activeTab, loadSmtpConfig, loadEmailLogs]);

  useEffect(() => { setLogoPreviewError(false); }, [form.logo_url]);

  const handleChange = (field: keyof SettingsForm, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors(prev => { const n = { ...prev }; delete n[field]; return n; });
    }
    previewSettings({ [field]: value });
    const singleFieldErrors = validateForm({ ...form, [field]: value });
    if (singleFieldErrors[field]) {
      setErrors(prev => ({ ...prev, [field]: singleFieldErrors[field] }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationErrors = validateForm(form);
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }
    setSaving(true);
    setSaveMsg(null);
    try {
      await updateSettings({
        platform_name: form.platform_name.trim(),
        platform_subtitle: form.platform_subtitle.trim() || null,
        logo_url: form.logo_url.trim(),
        favicon_url: form.favicon_url.trim() || null,
      });
      setSaveMsg({ type: 'success', text: '保存成功' });
    } catch (err) {
      setSaveMsg({ type: 'error', text: err instanceof Error ? err.message : '保存失败' });
    } finally {
      setSaving(false);
    }
  };

  const handleSmtpChange = (field: keyof SmtpForm, value: string | number | boolean) => {
    setSmtpForm(prev => ({ ...prev, [field]: value }));
    if (smtpErrors[field]) {
      setSmtpErrors(prev => { const n = { ...prev }; delete n[field]; return n; });
    }
  };

  const handleSaveSmtp = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationErrors = validateSmtpForm(smtpForm);
    if (Object.keys(validationErrors).length > 0) {
      setSmtpErrors(validationErrors);
      return;
    }
    setSmtpSaveMsg(null);
    setSmtpSaving(true);
    try {
      await apiFetch('/api/platform-settings/smtp', {
        method: 'PUT',
        body: JSON.stringify({
          smtp_host: smtpForm.smtp_host.trim(),
          smtp_port: smtpForm.smtp_port,
          smtp_user: smtpForm.smtp_user.trim(),
          smtp_password: smtpForm.smtp_password || undefined,
          smtp_from_addr: smtpForm.smtp_from_addr.trim(),
          smtp_use_tls: smtpForm.smtp_use_tls,
        }),
      });
      setSmtpSaveMsg({ type: 'success', text: '保存成功' });
    } catch (err) {
      setSmtpSaveMsg({ type: 'error', text: err instanceof Error ? err.message : '保存失败' });
    } finally {
      setSmtpSaving(false);
    }
  };

  const handleSendTestEmail = async () => {
    if (!testEmail.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(testEmail)) {
      setTestMsg({ type: 'error', text: '请输入有效的收件人邮箱' });
      return;
    }
    setTestSending(true);
    setTestMsg(null);
    try {
      const res = await apiFetch<{ success: boolean; message: string }>(
        '/api/platform-settings/smtp/test',
        { method: 'POST', body: JSON.stringify({ recipient_email: testEmail.trim() }) }
      );
      setTestMsg({ type: 'success', text: res.message || '测试邮件已发送' });
      loadEmailLogs();
    } catch (err) {
      setTestMsg({ type: 'error', text: err instanceof Error ? err.message : '发送失败' });
    } finally {
      setTestSending(false);
    }
  };

  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <i className="ri-lock-line text-5xl text-slate-300 mb-4 block" />
          <h2 className="text-xl font-semibold text-slate-700 mb-2">无权限访问</h2>
          <p className="text-slate-500">仅管理员可管理平台设置</p>
        </div>
      </div>
    );
  }

  if (settingsLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <span className="w-6 h-6 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
        <span className="ml-2 text-slate-500">加载中…</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-base font-semibold text-slate-900">平台设置</h1>
          <p className="text-xs text-slate-400 mt-0.5">配置平台 Logo、名称和邮件通知设置</p>
        </div>
      </div>
      <div className="px-8 py-6">
        <div className="max-w-4xl mx-auto">

      {/* Tab 切换 */}
      <div className="flex border-b border-slate-200 mb-5">
        {([
          ['general', '基础设置'],
          ['email', '邮件通知'],
        ] as [TabKey, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
              activeTab === key
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ========== 基础设置 Tab ========== */}
      {activeTab === 'general' && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden flex">
          {/* 左侧：Logo 预览面板 */}
          <div className="w-44 shrink-0 border-r border-slate-100 bg-slate-50/60 flex flex-col items-center py-6 px-4 gap-3">
            <div className="w-16 h-16 rounded-xl bg-slate-100 flex items-center justify-center overflow-hidden border border-slate-200">
              {form.logo_url && !logoPreviewError ? (
                <img
                  src={form.logo_url}
                  alt="Logo 预览"
                  className="w-full h-full object-contain"
                  onError={() => setLogoPreviewError(true)}
                />
              ) : (
                <i className="ri-image-line text-2xl text-slate-400" />
              )}
            </div>
            <div className="text-center max-w-full">
              <p className="text-sm font-semibold text-slate-800 leading-snug truncate max-w-[140px]">
                {form.platform_name || '平台名称'}
              </p>
              {form.platform_subtitle && (
                <p className="text-[11px] text-slate-400 mt-0.5 truncate max-w-[140px]">
                  {form.platform_subtitle}
                </p>
              )}
            </div>
            {logoPreviewError && (
              <p className="text-[10px] text-red-500 text-center">Logo 无法加载</p>
            )}
            <div className="mt-auto text-[10px] text-slate-400 text-center leading-relaxed">
              <p>Logo 建议 1:1 PNG/SVG</p>
              <p className="mt-1">上次更新</p>
              <p className="font-mono text-[9px] mt-0.5">{formatDate(settings.updated_at)}</p>
            </div>
          </div>

          {/* 右侧：表单 */}
          <form onSubmit={handleSubmit} className="flex-1 flex flex-col p-5">
            <div className="flex-1 space-y-2.5">
              <Field label="平台名称" required error={errors.platform_name}>
                <input
                  type="text"
                  value={form.platform_name}
                  onChange={e => handleChange('platform_name', e.target.value)}
                  placeholder="例如：木兰 BI 平台"
                  maxLength={128}
                  className={CLS(errors.platform_name)}
                />
              </Field>
              <Field label="副标题" error={errors.platform_subtitle}>
                <input
                  type="text"
                  value={form.platform_subtitle}
                  onChange={e => handleChange('platform_subtitle', e.target.value)}
                  placeholder="例如：数据建模与治理平台"
                  maxLength={256}
                  className={CLS(errors.platform_subtitle)}
                />
              </Field>
              <Field label="Logo URL" required error={errors.logo_url}>
                <input
                  type="url"
                  value={form.logo_url}
                  onChange={e => handleChange('logo_url', e.target.value)}
                  placeholder="https://example.com/logo.png"
                  maxLength={512}
                  className={CLS(errors.logo_url) + ' font-mono'}
                />
              </Field>
              <Field label="Favicon" error={errors.favicon_url}>
                <input
                  type="url"
                  value={form.favicon_url}
                  onChange={e => handleChange('favicon_url', e.target.value)}
                  placeholder="https://example.com/favicon.ico"
                  className={CLS(errors.favicon_url) + ' font-mono'}
                />
              </Field>
            </div>
            <div className="flex items-center gap-3 pt-4 mt-3 border-t border-slate-100">
              <button
                type="submit"
                disabled={saving}
                className="px-5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
              >
                {saving && <span className="w-3.5 h-3.5 border-2 border-white/50 border-t-white rounded-full animate-spin" />}
                {saving ? '保存中…' : '保存设置'}
              </button>
              {saveMsg && (
                <span className={`text-sm ${saveMsg.type === 'success' ? 'text-emerald-600' : 'text-red-500'}`}>
                  <i className={`ri-${saveMsg.type === 'success' ? 'check-line' : 'error-warning-line'} mr-1`} />
                  {saveMsg.text}
                </span>
              )}
            </div>
          </form>
        </div>
      )}

      {/* ========== 邮件通知 Tab ========== */}
      {activeTab === 'email' && (
        <>
          {smtpLoading ? (
            <div className="flex items-center justify-center min-h-[160px]">
              <span className="w-6 h-6 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
              <span className="ml-2 text-slate-500">加载中…</span>
            </div>
          ) : (
            <form onSubmit={handleSaveSmtp} className="bg-white border border-slate-200 rounded-xl overflow-hidden mb-4">
              <div className="flex divide-x divide-slate-100">
                {/* 左列：服务器配置 */}
                <div className="flex-1 p-5 space-y-2.5">
                  <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-3">服务器</p>
                  <Field label="SMTP 主机" required error={smtpErrors.smtp_host}>
                    <input
                      type="text"
                      value={smtpForm.smtp_host}
                      onChange={e => handleSmtpChange('smtp_host', e.target.value)}
                      placeholder="smtp.example.com"
                      className={CLS(smtpErrors.smtp_host) + ' font-mono'}
                    />
                  </Field>
                  <Field label="端口" required error={smtpErrors.smtp_port}>
                    <input
                      type="number"
                      value={smtpForm.smtp_port}
                      onChange={e => handleSmtpChange('smtp_port', parseInt(e.target.value) || 465)}
                      min={1}
                      max={65535}
                      className={CLS(smtpErrors.smtp_port)}
                    />
                  </Field>
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-slate-500 w-20 shrink-0 text-right">TLS 加密</span>
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        id="smtp_use_tls"
                        checked={smtpForm.smtp_use_tls}
                        onChange={e => handleSmtpChange('smtp_use_tls', e.target.checked)}
                        className="w-4 h-4 rounded border-slate-300 text-blue-600"
                      />
                      <label htmlFor="smtp_use_tls" className="text-sm text-slate-600">启用</label>
                      <span className="text-[11px] text-slate-400">（465 SSL / 587 TLS）</span>
                    </div>
                  </div>
                </div>

                {/* 右列：账户信息 */}
                <div className="flex-1 p-5 space-y-2.5">
                  <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-3">账户</p>
                  <Field label="用户名" required error={smtpErrors.smtp_user}>
                    <input
                      type="text"
                      value={smtpForm.smtp_user}
                      onChange={e => handleSmtpChange('smtp_user', e.target.value)}
                      placeholder="your@email.com"
                      className={CLS(smtpErrors.smtp_user)}
                    />
                  </Field>
                  <Field label="密码" error={smtpErrors.smtp_password}>
                    <PasswordField
                      value={smtpForm.smtp_password}
                      onChange={e => handleSmtpChange('smtp_password', e.target.value)}
                      placeholder={smtpForm.smtp_password === '' ? '留空保持不变' : '输入新密码'}
                      className={smtpErrors.smtp_password ? 'border-red-400 bg-red-50' : 'border-slate-300'}
                    />
                  </Field>
                  <Field label="发件人" required error={smtpErrors.smtp_from_addr}>
                    <input
                      type="email"
                      value={smtpForm.smtp_from_addr}
                      onChange={e => handleSmtpChange('smtp_from_addr', e.target.value)}
                      placeholder="no-reply@example.com"
                      className={CLS(smtpErrors.smtp_from_addr)}
                    />
                  </Field>
                </div>
              </div>

              {/* 底部：测试邮件 + 保存 */}
              <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/40 flex items-center gap-2.5 flex-wrap">
                <span className="text-sm text-slate-500 shrink-0">测试邮件</span>
                <input
                  type="email"
                  value={testEmail}
                  onChange={e => setTestEmail(e.target.value)}
                  placeholder="收件人邮箱"
                  className="w-52 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 transition-colors"
                />
                <button
                  type="button"
                  onClick={handleSendTestEmail}
                  disabled={testSending}
                  className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 shrink-0"
                >
                  {testSending && <span className="w-3 h-3 border-2 border-slate-400/50 border-t-slate-600 rounded-full animate-spin" />}
                  发送
                </button>
                {testMsg && (
                  <span className={`text-xs shrink-0 ${testMsg.type === 'success' ? 'text-emerald-600' : 'text-red-500'}`}>
                    {testMsg.text}
                  </span>
                )}
                <div className="flex-1" />
                <button
                  type="submit"
                  disabled={smtpSaving}
                  className="px-5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 shrink-0"
                >
                  {smtpSaving && <span className="w-3.5 h-3.5 border-2 border-white/50 border-t-white rounded-full animate-spin" />}
                  {smtpSaving ? '保存中…' : '保存设置'}
                </button>
                {smtpSaveMsg && (
                  <span className={`text-sm shrink-0 ${smtpSaveMsg.type === 'success' ? 'text-emerald-600' : 'text-red-500'}`}>
                    {smtpSaveMsg.text}
                  </span>
                )}
              </div>
            </form>
          )}

          {/* 发送记录 */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium text-slate-700">发送记录</h3>
                <p className="text-xs text-slate-400 mt-0.5">最近 {logsTotal} 条</p>
              </div>
              <button
                onClick={loadEmailLogs}
                className="text-xs text-slate-500 hover:text-slate-700 transition"
              >
                <i className="ri-refresh-line mr-1" />刷新
              </button>
            </div>
            {logsLoading ? (
              <div className="flex items-center justify-center py-6">
                <span className="w-5 h-5 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
              </div>
            ) : emailLogsError ? (
              <div className="flex flex-col items-center py-6 text-red-500">
                <i className="ri-error-warning-line text-2xl mb-1" />
                <p className="text-sm">{emailLogsError}</p>
                <button onClick={loadEmailLogs} className="mt-1 text-xs text-blue-500 hover:underline">重试</button>
              </div>
            ) : emailLogs.length === 0 ? (
              <div className="flex flex-col items-center py-6 text-slate-400">
                <i className="ri-mail-line text-2xl mb-1" />
                <p className="text-sm">暂无发送记录</p>
              </div>
            ) : (
              <div className="overflow-x-auto max-h-52 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-slate-50">
                    <tr className="text-left text-slate-500 border-b border-slate-100">
                      <th className="px-4 py-2 font-medium">类型</th>
                      <th className="px-4 py-2 font-medium">收件人</th>
                      <th className="px-4 py-2 font-medium">主题</th>
                      <th className="px-4 py-2 font-medium">状态</th>
                      <th className="px-4 py-2 font-medium">发送时间</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {emailLogs.map(log => (
                      <tr key={log.id} className="hover:bg-slate-50/50">
                        <td className="px-4 py-2 text-slate-600">
                          {EMAIL_TYPE_LABELS[log.email_type] || log.email_type}
                        </td>
                        <td className="px-4 py-2 text-slate-600 max-w-[160px] truncate" title={log.recipient}>
                          {log.recipient}
                        </td>
                        <td className="px-4 py-2 text-slate-600 max-w-[180px] truncate" title={log.subject || ''}>
                          {log.subject || '—'}
                        </td>
                        <td className="px-4 py-2">
                          {(() => {
                            const s = STATUS_LABELS[log.status] || { label: log.status, color: 'bg-slate-100 text-slate-600' };
                            return (
                              <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${s.color}`}>
                                {s.label}
                              </span>
                            );
                          })()}
                          {log.attempt_count > 1 && (
                            <span className="ml-1 text-slate-400">×{log.attempt_count}</span>
                          )}
                          {log.error_detail && (
                            <p className="text-[10px] text-red-400 mt-0.5 max-w-[160px] truncate" title={log.error_detail}>
                              {log.error_detail}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-2 text-slate-400 whitespace-nowrap">
                          {log.sent_at ? formatDate(log.sent_at) : (log.created_at ? formatDate(log.created_at) : '—')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
        </div>
      </div>
    </div>
  );
}
