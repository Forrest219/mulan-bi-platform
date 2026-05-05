import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD=process.env.ADMIN_PASSWORD ?? 'admin123';

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

test.describe('Tableau 连接', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('Tableau 连接页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await expect(page.locator('text=Tableau 连接')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面显示连接列表或空状态', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);
    const hasTable = await page.locator('table').isVisible();
    const hasCards = await page.locator('[class*="rounded"]').first().isVisible();
    const hasEmpty = await page.locator('text=暂无').isVisible();
    expect(hasTable || hasCards || hasEmpty).toBe(true);
  });

  test('页面结构完整 - 标题、副标题、横幅、筛选复选框均可见', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);

    await expect(page.locator('text=Tableau 连接')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=连接由 MCP 配置自动管理')).toBeVisible();
    await expect(page.locator('a[href="/system/mcp-configs"]')).toBeVisible();
    await expect(page.locator('text=显示已禁用的连接')).toBeVisible();
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面无增删改操作按钮', async ({ page }) => {
    await mockConnectionsRoute(page);
    await page.goto('/assets/tableau-connections');
    await expect(page.locator('text=mcp_test_0419')).toBeVisible({ timeout: 5000 });

    await expect(page.locator('button', { hasText: '新建连接' })).toHaveCount(0);
    await expect(page.locator('button', { hasText: '编辑' })).toHaveCount(0);
    await expect(page.locator('button', { hasText: '删除' })).toHaveCount(0);
    await expect(page.locator('button', { hasText: /^启用$|^禁用$/ })).toHaveCount(0);

    await expect(page.locator('button', { hasText: '测试' })).toBeVisible();
    await expect(page.locator('button', { hasText: '同步' })).toBeVisible();
    await expect(page.locator('button', { hasText: '日志' })).toBeVisible();
  });

  test('MCP 配置提示横幅可见且包含链接', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);

    await expect(page.locator('text=连接由 MCP 配置自动管理')).toBeVisible({ timeout: 5000 });
    const mcpLink = page.locator('a[href="/system/mcp-configs"]');
    await expect(mcpLink).toBeVisible();
    await expect(mcpLink).toContainText('MCP 配置');
  });

  test('列表页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);
    const realErrors = errors.filter(e =>
      !e.includes('401') && !e.includes('403') && !e.includes('fetch') &&
      !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('Import Placeholder');
    expect(body).not.toContain('TODO');
  });

  test('筛选复选框可点击切换状态', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);
    const checkbox = page.locator('text=显示已禁用的连接').locator('..').locator('input[type="checkbox"]');
    const isChecked = await checkbox.isChecked();
    await page.locator('text=显示已禁用的连接').click();
    await page.waitForTimeout(500);
    const isCheckedAfter = await checkbox.isChecked();
    expect(isCheckedAfter).toBe(!isChecked);
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

  test('点击日志按钮跳转到同步日志页面', async ({ page }) => {
    await mockConnectionsRoute(page);

    await page.goto('/assets/tableau-connections');
    await expect(page.locator('text=mcp_test_0419')).toBeVisible({ timeout: 5000 });

    // 点击日志按钮
    await page.locator('button', { hasText: '日志' }).click();

    // 验证跳转到同步日志页面
    await expect(page).toHaveURL(/\/assets\/tableau-connections\/1\/sync-logs/, { timeout: 5000 });
    await expect(page.locator('text=的同步日志')).toBeVisible({ timeout: 5000 });
  });

  test('测试按钮成功时弹窗显示操作成功', async ({ page }) => {
    await mockConnectionsRoute(page);
    await page.route('**/api/tableau/connections/1/test', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: '连接测试成功' }),
      })
    );

    await page.goto('/assets/tableau-connections');
    await expect(page.locator('text=mcp_test_0419')).toBeVisible({ timeout: 5000 });

    await page.locator('button', { hasText: '测试' }).click();
    await expect(page.locator('text=操作成功')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=连接测试成功')).toBeVisible();
  });

  test('测试按钮失败时弹窗显示中文错误消息', async ({ page }) => {
    await mockConnectionsRoute(page);
    await page.route('**/api/tableau/connections/1/test', route =>
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

    await page.locator('button', { hasText: '测试' }).click();
    await expect(page.locator('text=操作失败')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=无权访问此连接')).toBeVisible();
    await expect(page.locator('text=[object Object]')).toHaveCount(0);
  });
});
