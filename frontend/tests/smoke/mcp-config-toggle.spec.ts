import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 切换 MCP 配置启用状态
 * 路径：/system/mcp-configs
 */
test.describe('MCP 配置管理 - 启用/禁用', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('切换 MCP 配置启用状态', async ({ page }) => {
    await page.goto('/system/mcp-configs');

    // 等待列表加载
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    // 获取第一个配置的行
    const firstRow = page.locator('tbody tr').first();

    // 找到启用/禁用开关并点击
    const toggleBtn = firstRow.locator('button').first();
    await toggleBtn.click();

    // 等待状态更新
    await page.waitForTimeout(500);
  });
});
