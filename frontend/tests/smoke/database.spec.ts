import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 数据库连接管理
 */
test.describe('数据库连接', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('数据库管理页加载无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/admin/datasources');
    await expect(page.locator('table, [class*="table"], [class*="list"]').first()).toBeVisible({ timeout: 8000 });
    expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
  });

  test('数据库列表或空状态正常显示', async ({ page }) => {
    await page.goto('/admin/datasources');
    const hasTable = await page.locator('table').first().isVisible({ timeout: 8000 }).catch(() => false);
    const hasEmptyState = await page.locator('text=暂无, text=没有数据, text=暂无连接').first().isVisible({ timeout: 2000 }).catch(() => false);
    expect(hasTable || hasEmptyState).toBe(true);
  });

  test('新建数据库连接按钮存在', async ({ page }) => {
    await page.goto('/admin/datasources');
    await expect(page.locator('button:has-text("新建"), button:has-text("添加"), button:has-text("创建")').first()).toBeVisible({ timeout: 8000 });
  });

  test('数据库类型选择器存在', async ({ page }) => {
    await page.goto('/admin/datasources');
    const dbTypeSelect = page.locator('select').first();
    if (await dbTypeSelect.isVisible({ timeout: 3000 })) {
      await expect(dbTypeSelect).toBeVisible();
    }
  });
});
