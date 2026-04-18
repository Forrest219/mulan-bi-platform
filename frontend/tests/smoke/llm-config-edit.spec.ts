import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 编辑 LLM 配置
 * 路径：/system/llm-configs
 */
test.describe('LLM 配置管理 - 编辑配置', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('编辑现有 LLM 配置', async ({ page }) => {
    await page.goto('/system/llm-configs');

    // 等待列表加载
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    // 点击第一个配置的编辑按钮
    const editBtn = page.locator('button').filter({ hasText: '编辑' }).first();
    await editBtn.click();

    // 修改显示名称
    const displayNameInput = page.locator('input[placeholder="GPT-4o Mini (General)"]');
    await displayNameInput.clear();
    await displayNameInput.fill('MiniMax Updated');

    // 保存
    await page.getByRole('button', { name: /保存修改/i }).click();

    // 验证更新成功
    await expect(page.locator('h1')).toContainText('LLM 多配置管理', { timeout: 5000 });
    await expect(page.locator('table')).toContainText('MiniMax Updated');
  });
});
