import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 添加 LLM 配置
 * 路径：/system/llm-configs
 */
test.describe('LLM 配置管理 - 添加配置', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('添加 MiniMax API 配置', async ({ page }) => {
    await page.goto('/system/llm-configs');
    await page.getByRole('button', { name: /新增配置/i }).click();
    await expect(page.getByRole('heading', { name: '新增 LLM 配置' })).toBeVisible({ timeout: 5000 });

    // 填写显示名称（精确 placeholder）
    const nameInput = page.locator('input[placeholder="GPT-4o Mini (General)"]');
    await expect(nameInput).toBeVisible();
    await nameInput.fill(`MiniMax-Test-${Date.now()}`);

    // 填写 API Key（精确 placeholder="sk-..."）
    const apiKeyInput = page.locator('input[placeholder="sk-..."]');
    await expect(apiKeyInput).toBeVisible();
    await apiKeyInput.fill('sk-test-add-minimax-key-123456789');

    // 等待 API Key 输入完成后再点击保存
    await page.waitForTimeout(200);

    // 保存
    await page.getByRole('button', { name: /创建配置/i }).click();

    // 等待返回列表页（标题变为"LLM 多配置管理"）
    await expect(page.locator('h1')).toContainText('LLM 多配置管理', { timeout: 8000 });
  });
});
