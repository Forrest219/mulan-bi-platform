/**
 * WelcomeHero — 首页欢迎区（idle 态主视觉）
 *
 * 风格：贴近 open-webui，问候语为唯一主角；logo 作为 24px 徽标点缀。
 */
import { LOGO_URL } from '../../../config';
import { useAuth } from '../../../context/AuthContext';

function greetingByHour(): string {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 12) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

export function WelcomeHero() {
  const { user } = useAuth();
  const name = user?.display_name ?? user?.username ?? '';
  const greeting = name ? `${greetingByHour()}，${name}` : greetingByHour();

  return (
    <div className="flex flex-col items-center text-center">
      <img
        src={LOGO_URL}
        alt=""
        aria-hidden="true"
        className="w-6 h-6 object-contain mb-3 opacity-80"
      />
      <h1 className="text-2xl font-semibold text-slate-800 tracking-tight">
        {greeting}
      </h1>
      <p className="mt-2 text-sm text-slate-500">
        用自然语言向木兰提问，开始探索你的数据
      </p>
    </div>
  );
}
