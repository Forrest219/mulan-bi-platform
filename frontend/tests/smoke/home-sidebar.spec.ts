import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 侧边栏 UI 回归防护
 *
 * 以下问题已被修复 3+ 次，每次回归原因是 spec/coder 重新加入被删除的元素。
 * 本测试文件作为永久防护屏障：任何 coder 执行 spec 后都必须通过这些用例。
 */
test.describe('首页 - 侧边栏头部回归防护', () => {

  test.beforeEach(async ({ page }) => {
    // 确保 localStorage 中侧边栏为展开状态，避免上一轮测试残留
    await page.goto('/login');
    await page.evaluate(() => localStorage.removeItem('mulan-home-sidebar-collapsed'));
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('侧边栏头部不含 Logo 图标（<img> 元素）', async ({ page }) => {
    await page.goto('/');
    // sidebar 元素内不能有任何 img
    const sidebarImgs = page.locator('#sidebar img');
    await expect(sidebarImgs).toHaveCount(0);
  });

  test('侧边栏头部不含折叠按钮（aria-label="折叠侧边栏"）', async ({ page }) => {
    await page.goto('/');
    const collapseBtn = page.locator('button[aria-label="折叠侧边栏"]');
    await expect(collapseBtn).toHaveCount(0);
  });

  test('侧边栏头部显示"木兰平台"文字', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#sidebar')).toContainText('木兰平台');
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

  test('收起后左上角出现展开按钮，点击可恢复', async ({ page }) => {
    await page.goto('/');

    // 通过 localStorage 触发收起状态后刷新（模拟用户上次收起后再访问）
    await page.evaluate(() => localStorage.setItem('mulan-home-sidebar-collapsed', 'true'));
    await page.reload();

    // 展开按钮必须在左上角可见
    const expandBtn = page.locator('button[aria-label="展开侧边栏"]');
    await expect(expandBtn).toBeVisible({ timeout: 3000 });

    // 点击后侧边栏恢复，展开按钮消失，"木兰平台"文字重新可见
    await expandBtn.click();
    await expect(expandBtn).toHaveCount(0);
    await expect(page.locator('#sidebar')).toContainText('木兰平台');
  });

  test('收起状态下页面主内容区仍可交互（不完全空白）', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.setItem('mulan-home-sidebar-collapsed', 'true'));
    await page.reload();

    // 展开按钮存在，证明页面不是完全空白
    const expandBtn = page.locator('button[aria-label="展开侧边栏"]');
    await expect(expandBtn).toBeVisible({ timeout: 3000 });

    // 主内容区的问答输入框也应可见
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await expect(askBarInput).toBeVisible();
  });

});
