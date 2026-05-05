import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 侧边栏 UI 回归防护
 *
 * 首页（ConversationBar）和后台页面（AppSidebar）的 logo 区域必须保持视觉一致。
 */
test.describe('首页 - 侧边栏头部回归防护', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.evaluate(() => localStorage.removeItem('mulan-home-sidebar-collapsed'));
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('侧边栏头部包含 Logo 图片和平台名称', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('#sidebar');
    await expect(sidebar).toBeVisible();

    const logo = sidebar.locator('img').first();
    await expect(logo).toBeVisible();
    await expect(logo).toHaveClass(/h-7/);

    const brand = sidebar.locator('span').filter({ hasText: /\S/ }).first();
    await expect(brand).toBeVisible();
  });

  test('侧边栏头部包含折叠按钮', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('#sidebar');
    const collapseBtn = sidebar.locator('i.ri-sidebar-fold-line');
    await expect(collapseBtn).toBeVisible();
  });

  test('首页对话栏与 AppSidebar 同时可见（统一布局）', async ({ page }) => {
    await page.goto('/');
    const convBar = page.locator('#sidebar');
    await expect(convBar).toBeVisible();

    // AppSidebar 也应该同时可见（统一布局）
    const appSidebar = page.locator('aside').first();
    await expect(appSidebar).toBeVisible();

    // ConversationBar 包含 logo 和折叠按钮
    const convLogo = convBar.locator('img').first();
    await expect(convLogo).toBeVisible();
    const convFold = convBar.locator('i.ri-sidebar-fold-line');
    await expect(convFold).toBeVisible();
  });

});

test.describe('首页 - 侧边栏收起/展开', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.evaluate(() => localStorage.removeItem('mulan-home-sidebar-collapsed'));
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('点击折叠按钮可收起侧边栏，再点展开按钮可恢复', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('#sidebar');
    await expect(sidebar).toBeVisible();

    // 折叠
    const collapseBtn = sidebar.locator('button').filter({ has: page.locator('i.ri-sidebar-fold-line') });
    await expect(collapseBtn).toBeVisible();
    await collapseBtn.click();
    await expect(sidebar).not.toBeVisible({ timeout: 3000 });

    // 展开按钮出现
    const expandBtn = page.locator('button[aria-label="展开侧边栏"]');
    await expect(expandBtn).toBeVisible({ timeout: 3000 });

    // 点击展开，侧边栏恢复
    await expandBtn.click();
    await expect(sidebar).toBeVisible({ timeout: 3000 });
    await expect(expandBtn).not.toBeVisible();
  });

  test('收起状态下页面主内容区仍可交互', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.setItem('mulan-home-sidebar-collapsed', 'true'));
    await page.reload();

    const askBarInput = page.locator('textarea[data-askbar-input]');
    await expect(askBarInput).toBeVisible();
  });

});
