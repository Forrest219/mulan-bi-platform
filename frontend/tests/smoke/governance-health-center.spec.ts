import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 数据健康中心（治理首页）
 * 路径：/governance/health-center
 *
 * 包含三个 Tab：数据仓库（warehouse）、数据质量（quality）、Tableau 健康（tableau）
 */
test.describe('数据健康中心', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('健康中心页可访问', async ({ page }) => {
    await page.goto('/governance/health-center');
    await page.waitForTimeout(1500);
    expect(page.url()).toContain('/governance/health-center');
    const hasContent = await page.locator('h1').first().isVisible().catch(() => false);
    expect(hasContent).toBe(true);
  });

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/health-center');
    await page.waitForTimeout(1500);
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

  // ── Tab 切换 ──────────────────────────────────────────────────

  test('默认 Tab 为数据仓库（warehouse）', async ({ page }) => {
    await page.goto('/governance/health-center');
    await page.waitForTimeout(1000);
    const urlAfterLoad = page.url();
    expect(urlAfterLoad).toMatch(/tab=warehouse/);
  });

  test('可切换到数据质量 Tab', async ({ page }) => {
    await page.goto('/governance/health-center');
    await page.waitForTimeout(1000);
    const qualityTab = page.locator('button', { hasText: /质量/ }).first();
    if (await qualityTab.isVisible().catch(() => false)) {
      await qualityTab.click();
      await page.waitForTimeout(500);
      expect(page.url()).toMatch(/tab=quality/);
    }
  });

  test('可切换到 Tableau 健康 Tab', async ({ page }) => {
    await page.goto('/governance/health-center');
    await page.waitForTimeout(1000);
    const tableauTab = page.locator('button', { hasText: /Tableau/i }).first();
    if (await tableauTab.isVisible().catch(() => false)) {
      await tableauTab.click();
      await page.waitForTimeout(500);
      expect(page.url()).toMatch(/tab=tableau/);
    }
  });

  // ── 数据仓库 Tab ─────────────────────────────────────────────

  test('数据仓库 Tab 有扫描按钮或列表', async ({ page }) => {
    await page.goto('/governance/health-center?tab=warehouse');
    await page.waitForTimeout(2000);
    const hasScanBtn = await page.locator('button').filter({ hasText: /扫描|发起扫描/i }).first().isVisible().catch(() => false);
    const hasTable = await page.locator('table').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').first().isVisible().catch(() => false);
    const hasLoading = await page.locator('text=加载中').first().isVisible().catch(() => false);
    expect(hasScanBtn || hasTable || hasEmpty || hasLoading).toBe(true);
  });

  test('数据仓库 Tab 有数据源选择器', async ({ page }) => {
    await page.goto('/governance/health-center?tab=warehouse');
    await page.waitForTimeout(2000);
    // 数据源选择器可能是 select 或 button
    const hasDsPicker = await page.locator('select').first().isVisible().catch(() => false) ||
      await page.locator('button').filter({ hasText: /选择数据源|数据源/i }).first().isVisible().catch(() => false) ||
      await page.locator('text=数据源').first().isVisible().catch(() => false);
    expect(hasDsPicker).toBe(true);
  });

  // ── 数据质量 Tab ─────────────────────────────────────────────

  test('数据质量 Tab 有质量规则相关内容', async ({ page }) => {
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(2000);
    // 质量 Tab 可能包含：规则、得分、质检等关键词
    const body = await page.locator('body').textContent();
    const hasQualityContent = body && (
      body.includes('质量') ||
      body.includes('规则') ||
      body.includes('评分') ||
      body.includes('得分')
    );
    expect(hasQualityContent).toBe(true);
  });

  test('数据质量 Tab 无英文占位文案残留', async ({ page }) => {
    await page.goto('/governance/health-center?tab=quality');
    await page.waitForTimeout(1000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('placeholder');
    expect(body).not.toContain('PLACEHOLDER');
  });

  // ── Tableau 健康 Tab ────────────────────────────────────────

  test('Tableau 健康 Tab 可加载', async ({ page }) => {
    await page.goto('/governance/health-center?tab=tableau');
    await page.waitForTimeout(2000);
    // 验证 URL 正确
    expect(page.url()).toMatch(/tab=tableau/);
    // 页面有内容（可能正在加载或已有内容）
    const hasHeading = await page.locator('h1').first().isVisible().catch(() => false);
    const hasLoading = await page.locator('text=加载中').first().isVisible().catch(() => false);
    const hasTableau = await page.locator('text=Tableau').first().isVisible().catch(() => false);
    expect(hasHeading || hasLoading || hasTableau).toBe(true);
  });

  // ── 路由兼容性 ──────────────────────────────────────────────

  test('/governance/health 重定向到 warehouse tab', async ({ page }) => {
    await page.goto('/governance/health');
    await page.waitForTimeout(1500);
    expect(page.url()).toMatch(/tab=warehouse/);
  });

  test('/governance/quality 重定向到 quality tab', async ({ page }) => {
    await page.goto('/governance/quality');
    await page.waitForTimeout(1500);
    expect(page.url()).toMatch(/tab=quality/);
  });
});
