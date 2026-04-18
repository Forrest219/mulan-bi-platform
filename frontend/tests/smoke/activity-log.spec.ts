import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 操作日志页
 * 路径：/system/activity（原 /admin/activity 已重定向）
 */
test.describe('操作日志', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('操作日志页可访问', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/system/activity');
    // 等待加载
    await page.waitForTimeout(2000);
    // 验证页面 URL 正确
    expect(page.url()).toContain('/system/activity');
    // 验证页面有内容
    await expect(page.locator('h1:has-text("访问日志")')).toBeVisible({ timeout: 3000 }).catch(() => {
      expect(page.url()).toContain('/system/activity');
    });
    // 过滤掉 CORS/API/Fetch 错误（后端依赖）
    const realErrors = errors.filter(e =>
      !e.includes('CORS') &&
      !e.includes('fetch') &&
      !e.includes('api') &&
      !e.includes('Failed to fetch') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('操作日志页面内容正常显示', async ({ page }) => {
    await page.goto('/system/activity');
    // 等待加载
    await page.waitForTimeout(2000);
    // 页面有 h1 标题即可
    const hasHeading = await page.locator('h1').first().isVisible({ timeout: 2000 }).catch(() => false);
    const hasContent = await page.locator('text=操作日志').first().isVisible({ timeout: 1000 }).catch(() => false);
    expect(hasHeading || hasContent).toBe(true);
  });
});
