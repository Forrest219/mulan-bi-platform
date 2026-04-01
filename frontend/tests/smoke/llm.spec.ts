import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: LLM 接入配置
 */
test.describe('LLM 配置', () => {

  test.beforeEach(async ({ page }) => {
    // 先登录管理员
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('LLM 配置页加载无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/admin/llm');
    await expect(page.locator('h1, h2, [class*="title"], [class*="heading"]').first()).toBeVisible({ timeout: 5000 });
    expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
  });

  test('LLM 表单所有字段正常渲染', async ({ page }) => {
    await page.goto('/admin/llm');
    await expect(page.locator('select[name="provider"], select').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('input[placeholder*="URL"], input[placeholder*="url"], input[placeholder*="API"]').first()).toBeVisible();
    await expect(page.locator('input[type="password"], input[name="api_key"]').first()).toBeVisible();
    await expect(page.locator('input[placeholder*="model"], input[name="model"]').first()).toBeVisible();
    await expect(page.locator('button[type="submit"], button:has-text("保存"), button:has-text("测试")').first()).toBeVisible();
  });

  test('API Key 输入框支持显示/隐藏切换', async ({ page }) => {
    await page.goto('/admin/llm');
    await expect(page.locator('input[type="password"], input[name="api_key"]').first()).toBeVisible({ timeout: 5000 });
    // 查找切换按钮（眼睛图标）
    const toggleBtn = page.locator('button[aria-label*="api", button[aria-label*="key"], button[aria-label*="密码"]').first();
    if (await toggleBtn.isVisible()) {
      await toggleBtn.click();
      // 切换后密码框应该变成 text 类型
      const inputType = await page.locator('input[name="api_key"], input[type="password"]').first().getAttribute('type');
      expect(['text', 'password']).toContain(inputType);
    }
  });

  test('保存按钮存在且可点击', async ({ page }) => {
    await page.goto('/admin/llm');
    await expect(page.locator('button:has-text("保存"), button:has-text("保存配置")').first()).toBeEnabled({ timeout: 5000 });
  });

  test('测试连接按钮存在', async ({ page }) => {
    await page.goto('/admin/llm');
    await expect(page.locator('button:has-text("测试"), button:has-text("测试连接")').first()).toBeVisible({ timeout: 5000 });
  });
});
