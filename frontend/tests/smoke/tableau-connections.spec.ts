import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

const MOCK_CONN = {
  id: 1,
  name: 'mcp_test_0419',
  server_url: 'https://online.tableau.com',
  site: 'https://online.tableau.com',
  api_version: '3.21',
  connection_type: 'mcp',
  token_name: 'test',
  is_active: true,
  last_test_success: true,
  auto_sync_enabled: false,
  sync_interval_hours: 24,
  sync_status: 'idle',
  last_sync_at: null,
  last_test_at: null,
};

function mockConnectionsRoute(page: import('@playwright/test').Page) {
  return page.route('**/api/tableau/connections?*', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connections: [MOCK_CONN], total: 1 }),
    })
  );
}

test.describe('Tableau 连接管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('Tableau 连接页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await expect(page.locator('h1')).toContainText('Tableau', { timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面有新建按钮', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    const addBtn = page.locator('button').filter({ hasText: /新建|新增|添加|创建/ });
    await expect(addBtn.first()).toBeVisible({ timeout: 5000 });
  });

  test('页面显示连接列表或空状态', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasCards = await page.locator('[class*="rounded"]').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').isVisible().catch(() => false);
    expect(hasTable || hasCards || hasEmpty).toBe(true);
  });

  test('同步成功时弹窗显示操作成功和具体消息', async ({ page }) => {
    await mockConnectionsRoute(page);
    await page.route('**/api/tableau/connections/1/sync', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: '同步任务已提交', status: 'pending', task_id: 'mock' }),
      })
    );

    await page.goto('/assets/tableau-connections');
    await expect(page.locator('text=mcp_test_0419')).toBeVisible({ timeout: 5000 });

    await page.locator('button', { hasText: '同步' }).click();
    await expect(page.locator('text=操作成功')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=同步任务已提交')).toBeVisible();
  });

  test('同步失败时结构化错误正确显示中文消息而非 [object Object]', async ({ page }) => {
    await mockConnectionsRoute(page);
    await page.route('**/api/tableau/connections/1/sync', route =>
      route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: { error_code: 'TAB_002', message: '无权访问此连接', detail: {} },
        }),
      })
    );

    await page.goto('/assets/tableau-connections');
    await expect(page.locator('text=mcp_test_0419')).toBeVisible({ timeout: 5000 });

    await page.locator('button', { hasText: '同步' }).click();

    await expect(page.locator('text=操作失败')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=无权访问此连接')).toBeVisible();
    await expect(page.locator('text=[object Object]')).toHaveCount(0);
  });

  test('同步失败后按钮恢复可点击状态', async ({ page }) => {
    await mockConnectionsRoute(page);
    await page.route('**/api/tableau/connections/1/sync', route =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '服务器内部错误' }),
      })
    );

    await page.goto('/assets/tableau-connections');
    await expect(page.locator('text=mcp_test_0419')).toBeVisible({ timeout: 5000 });

    const syncBtn = page.locator('button', { hasText: '同步' });
    await syncBtn.click();

    await expect(page.locator('text=操作失败')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=服务器内部错误')).toBeVisible();

    // 关闭弹窗
    await page.locator('text=关闭').click();

    // 按钮应恢复可点击
    await expect(syncBtn).toBeEnabled();
  });
});
