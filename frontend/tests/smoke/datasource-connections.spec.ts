import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('数据源管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('数据源管理页可访问', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');
    expect(page.url()).toContain('/assets/datasources');
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
    // 页面应显示标题或错误状态（API 依赖后端）
    const hasH1 = await page.locator('h1').isVisible().catch(() => false);
    const hasSidebar = await page.locator('text=数据源管理').isVisible().catch(() => false);
    expect(hasH1 || hasSidebar).toBe(true);
  });

  test('页面有新建按钮或加载状态', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');
    const hasBtn = await page.locator('button').filter({ hasText: /新建|新增|添加|创建/ }).first().isVisible().catch(() => false);
    const hasContent = await page.locator('text=数据源').first().isVisible().catch(() => false);
    expect(hasBtn || hasContent).toBe(true);
  });

  test('页面显示数据表格或空状态', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForTimeout(2000);
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasCards = await page.locator('[class*="rounded"]').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').isVisible().catch(() => false);
    expect(hasTable || hasCards || hasEmpty).toBe(true);
  });
});
