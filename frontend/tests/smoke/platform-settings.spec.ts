import { test, expect } from '@playwright/test';

/**
 * Smoke Test: 平台设置
 *
 * 验证平台设置页面的核心功能：
 * 1. 页面正常加载和渲染
 * 2. 修改设置后保存并验证持久化
 * 3. 实时预览和校验功能
 * 4. 权限控制（非 admin 不可访问）
 */

const ADMIN_USER = process.env.SMOKE_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.SMOKE_ADMIN_PASSWORD ?? 'admin123';

async function loginAsAdmin(page: any) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByPlaceholder('用户名').fill(ADMIN_USER);
  await page.getByPlaceholder('密码').fill(ADMIN_PASS);
  await page.getByRole('button', { name: '登录' }).click();
  await page.waitForURL('/', { timeout: 8000 });
}

async function readPlatformSettingsForm(page: any) {
  const inputs = page.locator('form input[type="text"], form input[type="url"]');
  return {
    platformName: await inputs.nth(0).inputValue(),
    platformSubtitle: await inputs.nth(1).inputValue(),
  };
}

async function savePlatformSettingsForm(
  page: any,
  settings: { platformName: string; platformSubtitle: string },
) {
  const inputs = page.locator('form input[type="text"], form input[type="url"]');
  await inputs.nth(0).fill(settings.platformName);
  await inputs.nth(1).fill(settings.platformSubtitle);
  await page.getByRole('button', { name: '保存设置' }).click();
}

test.describe('平台设置', () => {
  test.describe.configure({ mode: 'serial' });

  test('页面加载时正确显示平台设置表单', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/system/platform-settings');
    await page.waitForLoadState('networkidle');

    // 验证页面标题
    await expect(page.locator('h1')).toContainText('平台设置');

    // 验证表单元素存在
    await expect(page.locator('form')).toBeVisible();
    await expect(page.getByRole('button', { name: '保存设置' })).toBeVisible();

    // 验证 Logo 预览区域存在
    await expect(page.locator('img[alt="Logo 预览"]')).toBeVisible();

    // 验证配置说明区域
    await expect(page.locator('text=Logo 建议 1:1 PNG/SVG')).toBeVisible();
  });

  test('修改平台名称和副标题后保存成功并持久化', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/system/platform-settings');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('form input', { timeout: 5000 });

    const inputs = page.locator('form input[type="text"], form input[type="url"]');
    const originalSettings = await readPlatformSettingsForm(page);

    try {
      // 修改平台名称和副标题
      const testName = 'MULAN-TEST-' + Date.now();
      const testSubtitle = '测试副标题-' + Date.now();
      await inputs.nth(0).fill(testName);
      await inputs.nth(1).fill(testSubtitle);

      await page.getByRole('button', { name: '保存设置' }).click();
      await page.waitForTimeout(1500);

      // 验证保存成功提示
      await expect(page.locator('text=保存成功')).toBeVisible();

      // 刷新页面验证数据已持久化
      await page.reload();
      await page.waitForLoadState('networkidle');
      await page.waitForSelector('form input', { timeout: 5000 });

      const inputsAfter = page.locator('form input[type="text"], form input[type="url"]');
      await expect(inputsAfter.nth(0)).toHaveValue(testName);
      await expect(inputsAfter.nth(1)).toHaveValue(testSubtitle);
    } finally {
      await savePlatformSettingsForm(page, originalSettings);
    }
  });

  test('无效 Logo URL 实时显示格式错误', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/system/platform-settings');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('form input', { timeout: 5000 });

    const logoInput = page.locator('form input[type="url"]').first();

    // 输入无效 URL
    await logoInput.fill('not-a-valid-url');
    await page.waitForTimeout(300);

    // 验证即时显示错误提示
    await expect(page.locator('text=Logo URL 必须是有效的 HTTP(S) URL')).toBeVisible();

    // 修正为有效 URL
    await logoInput.fill('https://example.com/logo.png');
    await page.waitForTimeout(300);

    // 验证错误已清除
    await expect(page.locator('text=Logo URL 必须是有效的 HTTP(S) URL')).not.toBeVisible();
  });

  test('非 admin 用户访问被拒绝并跳转到 403', async ({ page }) => {
    // 使用普通用户登录
    await page.context().clearCookies();
    await page.goto('/login');
    await page.getByPlaceholder('用户名').fill('smoke_analyst');
    await page.getByPlaceholder('密码').fill('analyst123');
    await page.getByRole('button', { name: '登录' }).click();
    await page.waitForURL('/', { timeout: 8000 });

    // 访问平台设置
    await page.goto('/system/platform-settings');
    await page.waitForLoadState('networkidle');

    // 验证跳转到 403 页面
    await expect(page).toHaveURL(/\/403/);
    await expect(page.locator('text=权限不足')).toBeVisible();

    // 验证没有保存按钮
    await expect(page.getByRole('button', { name: '保存设置' })).not.toBeVisible();
  });

  test('空名称提交时显示校验错误', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/system/platform-settings');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('form input', { timeout: 5000 });

    const inputs = page.locator('form input[type="text"], form input[type="url"]');

    // 清空平台名称
    await inputs.nth(0).fill('');

    await page.getByRole('button', { name: '保存设置' }).click();
    await page.waitForTimeout(500);

    // 验证错误提示
    await expect(page.locator('text=平台名称不能为空')).toBeVisible();
  });

  test('修改 Logo URL 后实时预览生效', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/system/platform-settings');
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('form input', { timeout: 5000 });

    const logoInput = page.locator('form input[type="url"]').first();

    // 输入新的 Logo URL
    const newLogoUrl = 'https://public.readdy.ai/ai/img_res/abc123.png';
    await logoInput.fill(newLogoUrl);

    // 等待预览图片 src 更新
    const previewImg = page.locator('img[alt="Logo 预览"]');
    await expect(previewImg).toHaveAttribute('src', newLogoUrl, { timeout: 3000 });
  });
});
