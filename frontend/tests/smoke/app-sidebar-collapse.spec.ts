import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: AppSidebar 折叠/展开回归防护
 *
 * 回归场景：折叠后展开按钮被挤出视口，用户无法恢复侧边栏。
 * 根因：56px 折叠宽度放不下 logo + 平台名 + 按钮的水平布局。
 */
test.describe('AppSidebar 折叠/展开', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.evaluate(() => localStorage.removeItem('mulan-sidebar-collapsed'));
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('折叠后展开按钮仍可见且可点击', async ({ page }) => {
    await page.goto('/system/platform-settings');
    await page.waitForLoadState('networkidle');

    const sidebar = page.locator('aside').first();
    await expect(sidebar).toBeVisible();

    // 找到折叠按钮并点击
    const foldBtn = sidebar.locator('button').filter({ has: page.locator('i.ri-sidebar-fold-line') });
    await expect(foldBtn).toBeVisible();
    await foldBtn.click();

    // 折叠后：侧边栏宽度应缩小
    await expect(sidebar).toHaveCSS('width', '56px', { timeout: 3000 });

    // 核心断言：展开按钮在折叠态仍然可见且在视口内
    await expect(foldBtn).toBeVisible();
    const box = await foldBtn.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.y).toBeGreaterThanOrEqual(0);

    // 点击展开按钮恢复
    await foldBtn.click();
    await expect(sidebar).not.toHaveCSS('width', '56px', { timeout: 3000 });
  });

  test('折叠态刷新后展开按钮仍可见', async ({ page }) => {
    // 预设折叠态
    await page.evaluate(() => localStorage.setItem('mulan-sidebar-collapsed', 'true'));
    await page.goto('/system/platform-settings');
    await page.waitForLoadState('networkidle');

    const sidebar = page.locator('aside').first();
    await expect(sidebar).toHaveCSS('width', '56px', { timeout: 3000 });

    // 展开按钮必须可见
    const foldBtn = sidebar.locator('button').filter({ has: page.locator('i.ri-sidebar-fold-line') });
    await expect(foldBtn).toBeVisible();
    const box = await foldBtn.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);

    // 清理
    await page.evaluate(() => localStorage.removeItem('mulan-sidebar-collapsed'));
  });
});
