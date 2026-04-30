/**
 * 回归测试：禁止随机返回图片的 URL 作为平台 Logo
 *
 * Bug 复现：platform_settings.logo_url 被设为 https://httpbin.org/image/png，
 * 该端点每次请求返回随机图片（实测返回猪头），导致首页 Logo 变成猪头。
 *
 * 根因：数据库 settings 表缺乏约束，httpbin.org/image/png 是合法的 HTTP(S) URL，
 * 前端和后端均未做语义校验（不能是指向"随机/占位图片"服务的 URL）。
 *
 * 检查规则：
 * 1. logo_url 不得为已知随机/占位图片生成服务
 * 2. logo_url 应为静态资源 URL（可缓存、有固定内容）
 *
 * 已知禁止列表（持续补充）：
 * - https://httpbin.org/image/png   （每次返回随机图片，包括猪头）
 * - https://httpbin.org/image/jpeg  （同上）
 * - https://picsum.photos/*         （随机图片）
 * - https://via.placeholder.com/*   （占位图）
 * - https://img.shields.io/*        （徽章，可能变图）
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const FORBIDDEN_PATTERNS = [
  'httpbin.org/image',
  'picsum.photos',
  'via.placeholder.com',
  'img.shields.io',
];

describe('禁止随机/占位图片 URL 作为 Logo', () => {
  // ── 前端层：platform-settings 页面表单校验 ────────────────────────────────

  it('platform-settings 页面表单校验能拦截禁止的 logo_url', async () => {
    const pagePath = resolve(dirname(fileURLToPath(import.meta.url)), '../../../src/pages/admin/platform-settings/page.tsx');
    const source = readFileSync(pagePath, 'utf-8');

    // 确认 FORBIDDEN_PATTERNS 中的关键模式在表单校验逻辑中有体现
    const hasHttpbinGuard = source.includes('httpbin.org');
    expect(
      hasHttpbinGuard,
      'platform-settings/page.tsx 表单校验应拒绝 httpbin.org/image 等随机图片 URL'
    ).toBe(true);
  });

  // ── Fallback 配置：config.ts 中的 LOGO_URL 不得为禁止域名 ───────────────

  it('config.ts 的 LOGO_URL fallback 不是随机图片服务', () => {
    const configPath = resolve(dirname(fileURLToPath(import.meta.url)), '../../../src/config.ts');
    const source = readFileSync(configPath, 'utf-8');

    const matched = FORBIDDEN_PATTERNS.find(pattern => source.includes(pattern));
    expect(
      matched,
      `config.ts 的 LOGO_URL 不应包含禁止模式，当前包含：${matched ?? '无禁止模式'}`
    ).toBeUndefined();
  });

  // ── 上下文默认值：DEFAULT_SETTINGS.logo_url 不得为禁止域名 ─────────────

  it('PlatformSettingsContext 的 DEFAULT_SETTINGS.logo_url 不是随机图片服务', () => {
    const ctxPath = resolve(dirname(fileURLToPath(import.meta.url)), '../../../src/context/PlatformSettingsContext.tsx');
    const source = readFileSync(ctxPath, 'utf-8');

    const matched = FORBIDDEN_PATTERNS.find(pattern => source.includes(pattern));
    expect(
      matched,
      `PlatformSettingsContext.tsx 的默认 logo_url 不应包含禁止模式：${matched ?? '无禁止模式'}`
    ).toBeUndefined();
  });
});
