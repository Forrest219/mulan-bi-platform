import { test, expect, Page } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 首页基础可用性
 * 路由: /
 */
test.describe('首页基础可用性', () => {

  async function login(page: Page) {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 8000 });
  }

  test('首页 / 可访问，body 有内容', async ({ page }) => {
    await login(page);
    await page.waitForTimeout(1500);
    const body = await page.locator('body').textContent();
    expect(body?.length ?? 0).toBeGreaterThan(10);
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('首页无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await login(page);
    await page.waitForTimeout(2000);
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('fetch') &&
      !e.includes('favicon') &&
      !e.includes('Failed to load resource') &&
      !e.includes('net::ERR') &&
      !e.includes('Failed to fetch')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('首页无独立连接选择器（已嵌入 AskBar）', async ({ page }) => {
    await login(page);
    await page.waitForTimeout(1500);
    const topScopeLabel = page.locator('label[for="scope-connection"]');
    await expect(topScopeLabel).toHaveCount(0);
  });

  test('旧路由 /ops/workbench 重定向到 /', async ({ page }) => {
    await login(page);
    await page.goto('/ops/workbench');
    await page.waitForURL(url => !url.toString().includes('/ops/workbench'), { timeout: 5000 });
    expect(page.url()).not.toContain('/ops/workbench');
  });

  test('中文文案，无明显英文占位残留', async ({ page }) => {
    await login(page);
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent() ?? '';
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
    expect(body).not.toContain('Import Placeholder');
  });
});
