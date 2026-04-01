import { test, expect } from '@playwright/test';

/**
 * Smoke Test: 首页能正常加载
 * 验证：
 * 1. 页面标题/欢迎语正常显示
 * 2. 搜索框存在
 * 3. 无 console.error
 */
test('首页正常加载', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });

  await page.goto('/');
  await expect(page).toHaveTitle(/Mulan/);

  // 搜索框存在
  const searchInput = page.locator('textarea');
  await expect(searchInput).toBeVisible();

  // 无 console error
  expect(errors).toHaveLength(0);
});

/**
 * Smoke Test: 登录页能正常加载
 */
test('登录页正常加载', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });

  await page.goto('/login');
  await expect(page.locator('input[type="text"], input[type="email"]')).toBeVisible();
  await expect(page.locator('input[type="password"]')).toBeVisible();

  expect(errors).toHaveLength(0);
});
