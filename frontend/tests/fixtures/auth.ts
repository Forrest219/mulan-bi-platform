import { expect, type Page } from '@playwright/test';

/**
 * Playwright fixture: 统一认证
 *
 * 提供 smoke_analyst 和 admin 两种身份的登录辅助。
 * 每次调用都会执行真实登录，并校验后端登录响应与前端跳转结果。
 *
 * 用法：
 *   import { auth } from '../fixtures/auth';
 *   test('...', async ({ page, auth }) => { await auth.asAnalyst(page); });
 */
export const auth = {
  /**
   * 以 smoke_analyst 身份登录
   * 用户仅有 database_monitor 权限
   */
  asAnalyst: async (page: Page) => {
    const username = process.env.SMOKE_ANALYST_USERNAME ?? 'smoke_analyst';
    const password = process.env.SMOKE_ANALYST_PASSWORD ?? 'analyst123';
    await doLogin(page, username, password);
  },

  /**
   * 以 admin 身份登录
   * 用户拥有所有权限 (adminOnly)
   */
  asAdmin: async (page: Page) => {
    const username = process.env.SMOKE_ADMIN_USERNAME ?? 'admin';
    const password = process.env.SMOKE_ADMIN_PASSWORD ?? 'admin123';
    await doLogin(page, username, password);
  },
};

async function doLogin(page: Page, username: string, password: string) {
  await page.goto('/login');
  await page.locator('input[type="text"]').fill(username);
  await page.locator('input[type="password"]').fill(password);

  const loginResponsePromise = page.waitForResponse(
    response => response.url().includes('/api/auth/login') && response.request().method() === 'POST',
    { timeout: 8000 },
  );

  await page.locator('button[type="submit"]').click();

  const loginResponse = await loginResponsePromise;
  expect(loginResponse.ok()).toBe(true);

  const loginResult = await loginResponse.json();
  expect(loginResult.success).toBe(true);
  expect(loginResult.mfa_required ?? false).toBe(false);
  expect(loginResult.user, '登录成功响应必须包含 user，避免只校验跳转').toBeTruthy();

  await expect(page).toHaveURL('/', { timeout: 8000 });
  await expect(page.getByText(/用户名或密码错误|登录失败|网络错误/)).toHaveCount(0);
}
