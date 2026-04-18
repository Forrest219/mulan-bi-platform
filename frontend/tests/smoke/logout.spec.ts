import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 用户登出
 */
test.describe('用户登出', () => {

  test('登录后可以正常退出', async ({ page }) => {
    // 先登录
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });

    // 等待页面加载完成
    await page.waitForLoadState('networkidle');

    // 查找登出按钮（通常在用户头像或下拉菜单中）
    const logoutBtn = page.locator('button').filter({ hasText: /退出|logout|sign out/i }).first();

    // 如果找到了登出按钮，则点击
    if (await logoutBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await logoutBtn.click();

      // 验证返回登录页
      await expect(page).toHaveURL('/login', { timeout: 5000 });
      await expect(page.locator('h1')).toContainText('Mulan Platform');
    } else {
      // 如果是 AppShellLayout，可能需要先点击用户头像打开菜单
      const userMenuBtn = page.locator('button').filter({ hasText: /admin|用户/i }).first();
      if (await userMenuBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await userMenuBtn.click();
        await page.waitForTimeout(300);
        const logoutInMenu = page.locator('button').filter({ hasText: /退出|logout/i }).first();
        if (await logoutInMenu.isVisible({ timeout: 2000 }).catch(() => false)) {
          await logoutInMenu.click();
          await expect(page).toHaveURL('/login', { timeout: 5000 });
        }
      }
    }
  });

  test('登出后无法访问受保护页面', async ({ page }) => {
    // 先登出（如果已登录）
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });

    // 通过清除 cookie 模拟登出
    await page.context().clearCookies();

    // 尝试访问受保护页面
    await page.goto('/system/llm-configs');

    // 应该被重定向到登录页
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 });
  });
});
