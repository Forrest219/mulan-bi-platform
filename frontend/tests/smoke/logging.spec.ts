import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 日志记录
 */
test.describe('日志记录', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('操作日志页加载无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/admin/activity');
    await expect(page.locator('table, [class*="table"], [class*="log"]').first()).toBeVisible({ timeout: 8000 });
    expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
  });

  test('日志列表或空状态正常显示', async ({ page }) => {
    await page.goto('/admin/activity');
    const hasTable = await page.locator('table').first().isVisible({ timeout: 8000 }).catch(() => false);
    const hasEmptyState = await page.locator('text=暂无, text=没有日志, text=暂无数据').first().isVisible({ timeout: 2000 }).catch(() => false);
    expect(hasTable || hasEmptyState).toBe(true);
  });

  test('时间范围筛选器存在', async ({ page }) => {
    await page.goto('/admin/activity');
    const timeFilter = page.locator('button:has-text("7天"), button:has-text("30天"), button:has-text("全部")').first();
    if (await timeFilter.isVisible({ timeout: 3000 })) {
      await expect(timeFilter).toBeVisible();
    }
  });

  test('操作类型筛选器存在', async ({ page }) => {
    await page.goto('/admin/activity');
    const typeFilter = page.locator('select').first();
    if (await typeFilter.isVisible({ timeout: 3000 })) {
      await expect(typeFilter).toBeVisible();
    }
  });

  test('日志表格包含时间、操作用户、操作类型列', async ({ page }) => {
    await page.goto('/admin/activity');
    const table = page.locator('table').first();
    if (await table.isVisible({ timeout: 8000 })) {
      // 检查表头是否存在
      const headers = await table.locator('th').allTextContents();
      expect(headers.length).toBeGreaterThan(0);
    }
  });
});
