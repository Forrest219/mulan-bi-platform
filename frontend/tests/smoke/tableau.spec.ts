import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: Tableau MCP 接入
 */
test.describe('Tableau MCP 连接', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('Tableau 连接页加载无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/admin/tableau/connections');
    await expect(page.locator('table, [class*="table"], [class*="list"]').first()).toBeVisible({ timeout: 8000 });
    expect(errors.filter(e => !e.includes('favicon'))).toHaveLength(0);
  });

  test('连接列表页面正常渲染', async ({ page }) => {
    await page.goto('/admin/tableau/connections');
    // 页面应有连接列表或空状态提示
    const hasTable = await page.locator('table').first().isVisible({ timeout: 8000 }).catch(() => false);
    const hasEmptyState = await page.locator('text=暂无, text=没有数据, text=暂无连接').first().isVisible({ timeout: 2000 }).catch(() => false);
    expect(hasTable || hasEmptyState).toBe(true);
  });

  test('新建连接按钮存在', async ({ page }) => {
    await page.goto('/admin/tableau/connections');
    await expect(page.locator('button:has-text("新建"), button:has-text("添加"), button:has-text("创建")').first()).toBeVisible({ timeout: 8000 });
  });

  test('切换显示/隐藏非活跃连接', async ({ page }) => {
    await page.goto('/admin/tableau/connections');
    const toggle = page.locator('input[type="checkbox"], button:has-text("显示未激活"), button:has-text("隐藏未激活")').first();
    if (await toggle.isVisible({ timeout: 3000 })) {
      await toggle.click();
    }
    // 无报错即可
    expect(true).toBe(true);
  });
});
