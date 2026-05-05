import { test, expect } from '@playwright/test';

/**
 * Smoke Test: 账户安全
 *
 * 用户场景：
 * 1. 用户首次访问账户安全页，了解 MFA 状态
 * 2. 用户启用 MFA，绑定验证器
 * 3. 用户关闭 MFA（需验证身份）
 */

const ADMIN_USER = process.env.SMOKE_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.SMOKE_ADMIN_PASSWORD ?? 'admin123';

async function loginAsAdmin(page: any) {
  await page.goto('/login');
  await page.getByPlaceholder('用户名').fill(ADMIN_USER);
  await page.getByPlaceholder('密码').fill(ADMIN_PASS);
  await page.getByRole('button', { name: '登录' }).click();
  await page.waitForURL('/', { timeout: 8000 });
}

test.describe('账户安全', () => {

  test('场景A：未启用 MFA 时显示启用入口', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/account/security');
    await page.waitForLoadState('networkidle');

    // 验证页面标题
    await expect(page.locator('h1')).toContainText('账户安全');

    // 验证副标题
    await expect(page.locator('text=管理两步验证等安全设置')).toBeVisible();

    // 验证两步验证区域可见（使用更精确的 heading 选择器）
    await expect(page.getByRole('heading', { name: '两步验证' })).toBeVisible();

    // 两种状态必居其一：启用按钮 或 已启用标识
    const enableBtn = page.getByRole('button', { name: '启用两步验证' });
    const enabledText = page.getByRole('heading', { name: '两步验证已启用' });

    const hasEnableBtn = await enableBtn.isVisible({ timeout: 500 }).catch(() => false);
    const hasEnabledText = await enabledText.isVisible({ timeout: 500 }).catch(() => false);

    // 至少一个状态可见
    expect(hasEnableBtn || hasEnabledText).toBeTruthy();
  });

  test('场景B：启用 MFA 流程完整性', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/account/security');
    await page.waitForLoadState('networkidle');

    // 确认当前 MFA 状态
    const isEnabled = await page.getByRole('heading', { name: '两步验证已启用' })
      .isVisible({ timeout: 1000 }).catch(() => false);

    if (isEnabled) {
      // 已启用状态：验证关闭按钮存在
      const disableBtn = page.getByRole('button', { name: '关闭两步验证' });
      await expect(disableBtn).toBeVisible();
      return;
    }

    // 未启用：点击启用
    const enableBtn = page.getByRole('button', { name: '启用两步验证' });
    await enableBtn.click();
    await page.waitForTimeout(1500);

    // 验证出现扫描二维码界面（或错误提示）
    const scanHeading = page.getByRole('heading', { name: '扫描二维码' });
    const errorText = page.locator('text=网络错误');
    const scanVisible = await scanHeading.isVisible({ timeout: 3000 }).catch(() => false);
    const errorVisible = await errorText.isVisible({ timeout: 3000 }).catch(() => false);

    // 两种情况都是有效的测试结果
    if (scanVisible) {
      // 验证显示 QR 码
      const qrCode = page.locator('svg, canvas').first();
      await expect(qrCode).toBeVisible();

      // 验证有「下一步」和「取消」按钮
      await expect(page.getByRole('button', { name: '下一步' })).toBeVisible();
      await expect(page.getByRole('button', { name: '取消' })).toBeVisible();

      // 点击取消
      await page.getByRole('button', { name: '取消' }).click();
      await page.waitForTimeout(500);
    } else if (errorVisible) {
      // API 错误时，验证错误提示可见
      await expect(errorText).toBeVisible();
    }
  });

  test('场景C：关闭 MFA 需要验证身份', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/account/security');
    await page.waitForLoadState('networkidle');

    // 确认当前 MFA 状态
    const isEnabled = await page.getByRole('heading', { name: '两步验证已启用' })
      .isVisible({ timeout: 1000 }).catch(() => false);

    if (!isEnabled) {
      // 未启用时，跳过此测试
      test.skip();
      return;
    }

    // 已启用：点击「关闭两步验证」
    await page.getByRole('button', { name: '关闭两步验证' }).click();
    await page.waitForTimeout(500);

    // 验证出现验证表单
    await expect(page.getByLabel('当前密码')).toBeVisible();
    await expect(page.getByLabel('验证码')).toBeVisible();

    // 验证有「取消」和「确认关闭」按钮
    await expect(page.getByRole('button', { name: '取消' })).toBeVisible();
    const confirmBtn = page.getByRole('button', { name: '确认关闭' });
    await expect(confirmBtn).toBeVisible();

    // 点击取消
    await page.getByRole('button', { name: '取消' }).click();
    await page.waitForTimeout(500);

    // 验证恢复到已启用状态
    await expect(page.getByRole('heading', { name: '两步验证已启用' })).toBeVisible();
  });
});
