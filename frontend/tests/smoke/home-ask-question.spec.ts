import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 首页问答功能
 * 路径：/
 */
test.describe('首页 - 问答功能', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('首页显示问答输入框', async ({ page }) => {
    await page.goto('/');
    // 查找 textarea（AskBar）
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await expect(askBarInput).toBeVisible();
  });

  test('输入问题后可以发送', async ({ page }) => {
    await page.goto('/');

    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('查询销售额最高的产品');

    // 点击发送按钮
    const sendBtn = page.locator('button[aria-label="发送"]');
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();

    // 验证输入框被清空
    await expect(askBarInput).toHaveValue('');
  });

  test('回车键可以发送问题', async ({ page }) => {
    await page.goto('/');

    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('查询本月收入');

    // 按 Enter 发送
    await askBarInput.press('Enter');

    // 验证输入框被清空
    await expect(askBarInput).toHaveValue('');
  });
});
