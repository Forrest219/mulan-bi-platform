/**
 * WelcomeHero — 首页欢迎区（idle 态主视觉）
 *
 * 风格：贴近open-webui，Mulan Platform 品牌展示为主；logo 作为 56px 徽标居中。
 */
import { usePlatformSettings } from '../../../context/PlatformSettingsContext';

export function WelcomeHero() {
  const { settings } = usePlatformSettings();

  return (
    <div className="flex flex-col items-center text-center">
      <img
        src={settings.logo_url}
        alt=""
        aria-hidden="true"
        className="w-14 h-14 object-contain rounded-xl mb-4 opacity-80"
      />
      <h1 className="text-2xl font-bold text-slate-800 mb-1">
        {settings.platform_name || 'Mulan Platform'}
      </h1>
      <p className="text-sm text-slate-400 mb-10">
        {settings.platform_subtitle || '通过对话完成数据查询、建模检查与治理工作'}
      </p>
    </div>
  );
}
