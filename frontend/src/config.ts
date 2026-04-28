export const API_BASE = '';

// @deprecated 请使用 PlatformSettingsContext.settings.logo_url，此常量仅作 fallback
export const LOGO_URL = 'https://public.readdy.ai/ai/img_res/d9bf8fa2-dfff-4c50-98cf-7b635309e7d6.png';

export const AVATAR_GRADIENTS = [
  'from-blue-500 to-blue-600',
  'from-emerald-500 to-emerald-600',
  'from-purple-500 to-purple-600',
  'from-orange-500 to-orange-600',
  'from-pink-500 to-pink-600',
  'from-cyan-500 to-cyan-600',
];

export function getAvatarGradient(name: string) {
  const index = name.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0) % AVATAR_GRADIENTS.length;
  return AVATAR_GRADIENTS[index];
}

export const ASSET_TYPE_LABELS: Record<string, string> = {
  workbook: '工作簿',
  dashboard: '仪表板',
  view: '视图',
  datasource: '数据源',
};

/** 启用运维工作台（Ops Workbench）完整功能 */
export const ENABLE_OPS_WORKBENCH = true;
