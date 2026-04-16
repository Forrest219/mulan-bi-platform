/**
 * WelcomeHero — 首页欢迎区（idle 态展示）
 *
 * 居中：Logo + "Mulan Platform" + 副标题
 * 样式：slate/blue 浅色风格
 */
import { LOGO_URL } from '../../../config';

export function WelcomeHero() {
  return (
    <div className="flex flex-col items-center text-center pt-16 pb-8">
      <img
        src={LOGO_URL}
        alt="Mulan Platform Logo"
        className="w-16 h-16 object-contain mb-5"
      />
      <h1 className="text-3xl font-bold text-slate-700 mb-2">Mulan Platform</h1>
      <p className="text-slate-400 text-sm">数据建模与治理平台 — 用自然语言探索你的数据</p>
    </div>
  );
}
