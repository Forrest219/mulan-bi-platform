import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 数据质量页
 * 路径：/governance/health-center?tab=quality（由 /governance/quality 重定向）
 */
test.describe('数据质量', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('数据质量页可访问（重定向后）', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/quality');
    await page.waitForTimeout(2000);
    expect(page.url()).toMatch(/tab=quality/);
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('fetch') &&
      !e.includes('favicon') &&
      !e.includes('Failed to load resource') &&
      !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('页面加载后有内容或加载状态', async ({ page }) => {
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(2000);
    const hasTable = await page.locator('table').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').first().isVisible().catch(() => false);
    const hasLoading = await page.locator('text=加载中').first().isVisible().catch(() => false);
    const hasHeading = await page.locator('h1').first().isVisible().catch(() => false);
    expect(hasTable || hasEmpty || hasLoading || hasHeading).toBe(true);
  });

  // ── 质量 Tab 内容 ──────────────────────────────────────────────

  test('质量 Tab 包含质量相关内容', async ({ page }) => {
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent() ?? '';
    const hasQualityKeywords = [
      '质量', '规则', '评分', '得分',
      'quality', 'rule', 'score', '检查', '校验'
    ].some(kw => body.toLowerCase().includes(kw.toLowerCase()));
    expect(hasQualityKeywords).toBe(true);
  });

  test('页面无英文占位文案残留', async ({ page }) => {
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(1000);
    const body = await page.locator('body').textContent();
    const placeholderTexts = [
      'TODO', 'placeholder', 'PLACEHOLDER', 'FIXME',
      'Import Placeholder', 'New Connection (CTA)', 'option C shell'
    ];
    for (const text of placeholderTexts) {
      expect(body).not.toContain(text);
    }
  });

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(2000);
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('fetch') &&
      !e.includes('favicon') &&
      !e.includes('Failed to load resource') &&
      !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  // ── 操作入口（如有）──────────────────────────────────────────

  test('质量 Tab 展示质量相关内容或空状态', async ({ page }) => {
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(2000);
    // 页面应展示：质量内容、或空状态提示、或加载中，不能是空白页
    const hasContent = await page.locator('body').textContent();
    expect(hasContent && hasContent.trim().length > 0).toBe(true);
  });

  // ── Tab 间切换 ──────────────────────────────────────────────

  test('可从质量 Tab 切回数据仓库 Tab', async ({ page }) => {
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(1000);
    const warehouseTab = page.locator('button').filter({ hasText: /仓库|数据/i }).first();
    if (await warehouseTab.isVisible().catch(() => false)) {
      await warehouseTab.click();
      await page.waitForTimeout(500);
      expect(page.url()).toMatch(/tab=warehouse/);
    }
  });

  test('可从质量 Tab 切换到 Tableau 健康 Tab', async ({ page }) => {
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(1000);
    const tableauTab = page.locator('button', { hasText: /Tableau/i }).first();
    if (await tableauTab.isVisible().catch(() => false)) {
      await tableauTab.click();
      await page.waitForTimeout(500);
      expect(page.url()).toMatch(/tab=tableau/);
    }
  });
});
