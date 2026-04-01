import { test, expect } from '@playwright/test';

/**
 * Smoke Test: 未登录状态下访问受保护页面应跳转至登录页
 */
test.describe('权限重定向', () => {
  const protectedPages = [
    '/ddl-validator',
    '/rule-config',
    '/tableau/assets',
    '/semantic-maintenance/datasources',
    '/admin/users',
  ];

  for (const path of protectedPages) {
    test(`${path} 未登录时应跳转登录页`, async ({ page }) => {
      await page.goto(path);
      // 检查最终落在登录页
      await expect(page).toHaveURL(/\/login/);
    });
  }
});
