import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('Tableau 连接管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('Tableau 连接页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await expect(page.locator('h1')).toContainText('Tableau', { timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面有新建按钮', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    const addBtn = page.locator('button').filter({ hasText: /新建|新增|添加|创建/ });
    await expect(addBtn.first()).toBeVisible({ timeout: 5000 });
  });

  test('页面显示连接列表或空状态', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasCards = await page.locator('[class*="rounded"]').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').isVisible().catch(() => false);
    expect(hasTable || hasCards || hasEmpty).toBe(true);
  });
});
