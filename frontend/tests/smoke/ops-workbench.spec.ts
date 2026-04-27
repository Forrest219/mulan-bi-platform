import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 运维工作台
 * 路径：/ops/workbench
 * Split-Pane 布局：问数 / 资产 / 健康 三个模式
 */
test.describe('运维工作台', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('运维工作台可访问且显示中文标题', async ({ page }) => {
    await page.goto('/ops/workbench');
    await expect(page.locator('h1')).toContainText('运维工作台', { timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面结构完整 - 三个模式切换按钮可见', async ({ page }) => {
    await page.goto('/ops/workbench');
    await page.waitForTimeout(2000);

    // 三个模式按钮
    await expect(page.locator('button', { hasText: '问数' }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button', { hasText: '资产' }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button', { hasText: '健康' }).first()).toBeVisible({ timeout: 5000 });
  });

  test('默认加载问数模式', async ({ page }) => {
    await page.goto('/ops/workbench');
    await page.waitForTimeout(2000);

    // 侧边栏应显示 "最近会话" 或 "新建查询"
    const body = await page.locator('body').textContent() ?? '';
    const hasQueryContent = body.includes('最近会话') || body.includes('新建查询');
    expect(hasQueryContent).toBe(true);
  });

  // ── 模式切换 ──────────────────────────────────────────────────

  test('可切换到资产模式', async ({ page }) => {
    await page.goto('/ops/workbench');
    await page.waitForTimeout(2000);

    await page.locator('button', { hasText: '资产' }).first().click();
    await page.waitForTimeout(1000);

    // URL 应包含 mode=assets
    expect(page.url()).toContain('mode=assets');
    // 侧边栏应显示数据源相关内容
    const body = await page.locator('body').textContent() ?? '';
    const hasAssetContent = body.includes('数据源') || body.includes('搜索资产');
    expect(hasAssetContent).toBe(true);
  });

  test('可切换到健康模式', async ({ page }) => {
    await page.goto('/ops/workbench');
    await page.waitForTimeout(2000);

    await page.locator('button', { hasText: '健康' }).first().click();
    await page.waitForTimeout(1000);

    // URL 应包含 mode=health
    expect(page.url()).toContain('mode=health');
    // 侧边栏应显示健康相关分类
    const body = await page.locator('body').textContent() ?? '';
    const hasHealthContent = body.includes('健康分类') || body.includes('刷新健康数据');
    expect(hasHealthContent).toBe(true);
  });

  // ── 首页链接 ──────────────────────────────────────────────────

  test('页面包含首页返回链接', async ({ page }) => {
    await page.goto('/ops/workbench');
    await page.waitForTimeout(2000);

    await expect(page.locator('a', { hasText: '首页' })).toBeVisible();
  });

  // ── 无报错 ────────────────────────────────────────────────────

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/ops/workbench');
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
    await page.goto('/ops/workbench');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
    expect(body).not.toContain('Import Placeholder');
  });
});
