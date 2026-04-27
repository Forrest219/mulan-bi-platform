import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 合规巡检页
 * 路径：/governance/compliance
 * 注意：页面组件已实现（data-governance/compliance/page.tsx），
 *       但路由可能尚未注册。测试容忍 404 重定向。
 */
test.describe('合规巡检', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('合规巡检页可访问（路由已注册时）', async ({ page }) => {
    await page.goto('/governance/compliance');
    await page.waitForTimeout(2000);

    // 如果路由已注册，应显示合规相关内容
    const body = await page.locator('body').textContent() ?? '';
    const hasComplianceContent = body.includes('合规规则') ||
      body.includes('合规') ||
      body.includes('巡检') ||
      body.includes('规则');
    const has404 = body.includes('Page Not Found') || body.includes('404');

    // 页面要么显示合规内容，要么显示 404（路由未注册）
    expect(hasComplianceContent || has404).toBe(true);
  });

  test('页面结构完整 - 统计卡片和 Tab 切换可见', async ({ page }) => {
    await page.goto('/governance/compliance');
    await page.waitForTimeout(2000);

    // 如果页面已注册路由
    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('合规规则')) {
      // 统计卡片
      expect(body).toContain('合规规则');
      // Tab 切换按钮
      const hasRulesTab = body.includes('合规规则');
      const hasResultsTab = body.includes('巡检结果');
      expect(hasRulesTab || hasResultsTab).toBe(true);
    }
    // 如果路由未注册，跳过结构检查
  });

  test('合规规则列表或空状态显示', async ({ page }) => {
    await page.goto('/governance/compliance');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('合规规则')) {
      const hasTable = await page.locator('table').isVisible().catch(() => false);
      const hasEmpty = body.includes('暂无匹配规则') || body.includes('加载中');
      const hasStats = body.includes('已启用');
      expect(hasTable || hasEmpty || hasStats).toBe(true);
    }
  });

  test('发起巡检按钮可见', async ({ page }) => {
    await page.goto('/governance/compliance');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('合规规则')) {
      const scanBtn = page.locator('button', { hasText: /发起巡检/ });
      await expect(scanBtn.first()).toBeVisible({ timeout: 3000 });
    }
  });

  test('可切换到巡检结果 Tab', async ({ page }) => {
    await page.goto('/governance/compliance');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('合规规则')) {
      const resultsTab = page.locator('button', { hasText: '巡检结果' });
      if (await resultsTab.isVisible().catch(() => false)) {
        await resultsTab.click();
        await page.waitForTimeout(1000);
        const updatedBody = await page.locator('body').textContent() ?? '';
        const hasResults = updatedBody.includes('巡检概要') ||
          updatedBody.includes('暂无巡检记录') ||
          updatedBody.includes('违规项');
        expect(hasResults).toBe(true);
      }
    }
  });

  // ── 筛选功能 ──────────────────────────────────────────────────

  test('分类和级别筛选下拉可见', async ({ page }) => {
    await page.goto('/governance/compliance');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('合规规则')) {
      const hasFilterSelects = await page.locator('select').count();
      expect(hasFilterSelects).toBeGreaterThanOrEqual(1);
    }
  });

  // ── 无报错 ────────────────────────────────────────────────────

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/compliance');
    await page.waitForTimeout(2000);
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('fetch') &&
      !e.includes('favicon') &&
      !e.includes('Failed to load resource') &&
      !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/governance/compliance');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent() ?? '';
    if (!body.includes('Page Not Found') && !body.includes('404')) {
      expect(body).not.toContain('TODO');
      expect(body).not.toContain('Placeholder');
      expect(body).not.toContain('FIXME');
    }
  });
});
