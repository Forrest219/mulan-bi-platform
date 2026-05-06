/**
 * WelcomeHero — 首页欢迎区（idle 态主视觉）
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
      <h1 className="text-2xl font-semibold text-slate-700 mb-1">
        嗨，我是木兰，
      </h1>
      <p className="text-2xl font-semibold text-slate-400 mb-10">
        想探索哪方面的数据洞察？
      </p>
    </div>
  );
}
