/**
 * PlatformSettingsPage — /admin/platform-settings
 *
 * admin-only 平台基础设置管理页。
 *
 * 功能：
 * - 展示/编辑平台名称（platform_name）
 * - 展示/编辑平台副标题（platform_subtitle）
 * - 展示/编辑 Logo URL（logo_url）
 * - 展示/编辑 Favicon URL（favicon_url）
 * - 实时预览 Logo
 * - 仅 admin 可见
 *
 * 后端 API：
 *   GET    /api/platform-settings  → PlatformSettings
 *   PUT    /api/platform-settings  → PlatformSettings
 */
import { useState, useEffect } from 'react';
import { useAuth } from '../../../context/AuthContext';
import { usePlatformSettings, type PlatformSettings } from '../../../context/PlatformSettingsContext';

interface SettingsForm {
  platform_name: string;
  platform_subtitle: string;
  logo_url: string;
  favicon_url: string;
}

const LOGO_URL_RE = /^https?:\/\/.+/i;

// 禁止将随机/占位图片服务设为 Logo（每次请求返回不同图片）
const FORBIDDEN_LOGO_PATTERNS = [
  'httpbin.org/image',
  'picsum.photos',
  'via.placeholder.com',
  'img.shields.io',
];

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
    errors.logo_url = 'Logo URL 不能使用随机/占位图片服务（如 httpbin.org/image、picsum.photos 等）';
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
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function PlatformSettingsPage() {
  const { isAdmin } = useAuth();
  const { settings, isLoading, updateSettings, previewSettings } = usePlatformSettings();

  const [form, setForm] = useState<SettingsForm>({
    platform_name: '',
    platform_subtitle: '',
    logo_url: '',
    favicon_url: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [logoPreviewError, setLogoPreviewError] = useState(false);

  // 当 settings 加载完成后填充表单
  useEffect(() => {
    if (!isLoading) {
      setForm({
        platform_name: settings.platform_name || '',
        platform_subtitle: settings.platform_subtitle || '',
        logo_url: settings.logo_url || '',
        favicon_url: settings.favicon_url || '',
      });
    }
  }, [isLoading, settings]);

  // Logo 预览错误重置
  useEffect(() => {
    setLogoPreviewError(false);
  }, [form.logo_url]);

  const handleChange = (field: keyof SettingsForm, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }));
    // 清除该字段错误
    if (errors[field]) {
      setErrors(prev => { const next = { ...prev }; delete next[field]; return next; });
    }
    // 实时预览：同步更新 Context（不调 API）
    previewSettings({ [field]: value });
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
      console.log('[LogoSettings] Submitting:', form.platform_name, form.logo_url);
      await updateSettings({
        platform_name: form.platform_name.trim(),
        platform_subtitle: form.platform_subtitle.trim() || null,
        logo_url: form.logo_url.trim(),
        favicon_url: form.favicon_url.trim() || null,
      });
      console.log('[LogoSettings] updateSettings returned successfully');
      setSaveMsg({ type: 'success', text: '保存成功' });
    } catch (err) {
      console.error('[LogoSettings] updateSettings threw:', err);
      setSaveMsg({ type: 'error', text: err instanceof Error ? err.message : '保存失败' });
    } finally {
      setSaving(false);
    }
  };

  // 仅 admin 可见
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <span className="w-6 h-6 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
        <span className="ml-2 text-slate-500">加载中…</span>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-800">平台设置</h1>
        <p className="text-sm text-slate-500 mt-1">配置平台 Logo 和名称，修改后全站实时生效</p>
      </div>

      {/* 设置表单 */}
      <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-5">
        {/* 平台名称 */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1.5">
            平台名称 <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={form.platform_name}
            onChange={e => handleChange('platform_name', e.target.value)}
            placeholder="例如：木兰 BI 平台"
            maxLength={128}
            className={`w-full px-3 py-2 border rounded-lg text-sm text-slate-800 bg-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 transition ${errors.platform_name ? 'border-red-400 bg-red-50' : 'border-slate-200'}`}
          />
          <div className="flex justify-between mt-1">
            {errors.platform_name ? (
              <p className="text-xs text-red-500">{errors.platform_name}</p>
            ) : (
              <span />
            )}
            <p className="text-xs text-slate-400">{form.platform_name.length}/128</p>
          </div>
        </div>

        {/* 平台副标题 */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1.5">
            平台副标题
            <span className="text-xs text-slate-400 font-normal ml-1">可选</span>
          </label>
          <input
            type="text"
            value={form.platform_subtitle}
            onChange={e => handleChange('platform_subtitle', e.target.value)}
            placeholder="例如：数据建模与治理平台"
            maxLength={256}
            className={`w-full px-3 py-2 border rounded-lg text-sm text-slate-800 bg-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 transition ${errors.platform_subtitle ? 'border-red-400 bg-red-50' : 'border-slate-200'}`}
          />
          <div className="flex justify-between mt-1">
            {errors.platform_subtitle ? (
              <p className="text-xs text-red-500">{errors.platform_subtitle}</p>
            ) : (
              <span />
            )}
            <p className="text-xs text-slate-400">{form.platform_subtitle.length}/256</p>
          </div>
        </div>

        {/* Logo URL */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1.5">
            Logo URL <span className="text-red-500">*</span>
          </label>
          <input
            type="url"
            value={form.logo_url}
            onChange={e => handleChange('logo_url', e.target.value)}
            placeholder="https://example.com/logo.png"
            maxLength={512}
            className={`w-full px-3 py-2 border rounded-lg text-sm text-slate-800 bg-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 transition font-mono ${errors.logo_url ? 'border-red-400 bg-red-50' : 'border-slate-200'}`}
          />
          <div className="flex justify-between mt-1">
            {errors.logo_url ? (
              <p className="text-xs text-red-500">{errors.logo_url}</p>
            ) : (
              <p className="text-xs text-slate-400">支持 http:// 和 https://</p>
            )}
            <p className="text-xs text-slate-400">{form.logo_url.length}/512</p>
          </div>
          {/* Logo 实时预览 */}
          <div className="mt-3 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center overflow-hidden border border-slate-200 shrink-0">
              {form.logo_url && !logoPreviewError ? (
                <img
                  src={form.logo_url}
                  alt="Logo 预览"
                  className="w-full h-full object-contain"
                  onError={() => setLogoPreviewError(true)}
                />
              ) : (
                <i className="ri-image-line text-lg text-slate-400" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-700 truncate">
                {form.platform_name || '平台名称'}
                {form.platform_subtitle && (
                  <span className="text-xs text-slate-400 font-normal ml-2">{form.platform_subtitle}</span>
                )}
              </p>
              {logoPreviewError && (
                <p className="text-xs text-red-500">Logo 无法加载，请检查 URL</p>
              )}
            </div>
          </div>
        </div>

        {/* Favicon URL */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1.5">
            Favicon URL
            <span className="text-xs text-slate-400 font-normal ml-1">可选</span>
          </label>
          <input
            type="url"
            value={form.favicon_url}
            onChange={e => handleChange('favicon_url', e.target.value)}
            placeholder="https://example.com/favicon.ico"
            className={`w-full px-3 py-2 border rounded-lg text-sm text-slate-800 bg-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 transition font-mono ${errors.favicon_url ? 'border-red-400 bg-red-50' : 'border-slate-200'}`}
          />
          {errors.favicon_url && (
            <p className="text-xs text-red-500 mt-1">{errors.favicon_url}</p>
          )}
        </div>

        {/* 提交按钮 */}
        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2"
          >
            {saving && <span className="w-4 h-4 border-2 border-white/50 border-t-white rounded-full animate-spin" />}
            {saving ? '保存中…' : '保存设置'}
          </button>
          {saveMsg && (
            <span className={`text-sm ${saveMsg.type === 'success' ? 'text-emerald-600' : 'text-red-500'}`}>
              {saveMsg.type === 'success' ? (
                <i className="ri-check-line mr-1" />
              ) : (
                <i className="ri-error-warning-line mr-1" />
              )}
              {saveMsg.text}
            </span>
          )}
        </div>
      </form>

      {/* 辅助信息 */}
      <div className="mt-5 bg-slate-50 border border-slate-200 rounded-xl p-4">
        <h3 className="text-sm font-medium text-slate-600 mb-2">配置说明</h3>
        <ul className="text-xs text-slate-500 space-y-1">
          <li>· Logo 建议使用 1:1 比例的 PNG/SVG 图片</li>
          <li>· Logo URL 变更后，预览即时更新，无需保存</li>
          <li>· 上次更新：
            <span className="font-mono text-slate-400 ml-1">{formatDate(settings.updated_at)}</span>
          </li>
        </ul>
      </div>
    </div>
  );
}
