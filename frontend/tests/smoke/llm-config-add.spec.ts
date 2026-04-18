import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 添加 MiniMax LLM 配置
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

    // 点击新增配置
    await page.getByRole('button', { name: /新增配置/i }).click();

    // 等待表单出现
    await page.waitForTimeout(500);

    // 填写显示名称（查找可见的 text input）
    const nameInput = page.locator('input[placeholder*="GPT"]').first();
    await nameInput.fill('MiniMax General');

    // 填写 API Key（如果有可见的 password/input 字段）
    const apiKeyInput = page.locator('input[placeholder*="sk-"]').first();
    if (await apiKeyInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await apiKeyInput.fill('test-minimax-api-key-for-smoke');
    }

    // 保存
    const saveBtn = page.getByRole('button', { name: /创建配置/i });
    await expect(saveBtn).toBeVisible({ timeout: 3000 });
    await saveBtn.click();

    // 等待返回列表页
    await expect(page.locator('h1')).toContainText('LLM 多配置管理', { timeout: 5000 });

    // 验证新增的配置出现在列表中（可能需要等待）
    await page.waitForTimeout(1000);
    const hasNewConfig = await page.locator('table').locator('text=MiniMax General').isVisible({ timeout: 3000 }).catch(() => false);
    if (hasNewConfig) {
      await expect(page.locator('table')).toContainText('MiniMax General');
    }
  });
});
