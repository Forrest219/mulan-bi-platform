import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: MCP 配置列表
 * 路径：/system/mcp-configs
 */
test.describe('MCP 配置管理 - 列表页', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('导航到 MCP 配置页面', async ({ page }) => {
    await page.goto('/system/mcp-configs');
    await expect(page.locator('h1')).toContainText('MCP 配置管理', { timeout: 5000 });
  });

  test('MCP 配置页面内容或加载状态正常显示', async ({ page }) => {
    await page.goto('/system/mcp-configs');
    await page.waitForTimeout(3000);
    const hasTable = await page.locator('table').first().isVisible({ timeout: 2000 }).catch(() => false);
    const hasEmptyState = await page.locator('text=暂无 MCP 配置').first().isVisible({ timeout: 1000 }).catch(() => false);
    const hasLoading = await page.locator('text=加载中').first().isVisible({ timeout: 1000 }).catch(() => false);
    expect(hasTable || hasEmptyState || hasLoading).toBe(true);
  });
});
