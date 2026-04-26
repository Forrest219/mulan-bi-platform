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

  test('页面结构完整 - 标题、副标题、筛选复选框均可见', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);

    // 页面主标题
    await expect(page.locator('h1')).toContainText('Tableau 连接管理', { timeout: 5000 });
    // 副标题
    await expect(page.locator('text=配置 Tableau Server 连接并同步资产')).toBeVisible();
    // 筛选复选框
    await expect(page.locator('text=显示已禁用的连接')).toBeVisible();
    // 新建按钮
    await expect(page.locator('button', { hasText: '新建连接' })).toBeVisible();
    // 无 404 错误
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('打开新建连接 Modal，表单字段完整可见', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);
    await page.locator('button', { hasText: '新建连接' }).click();
    await page.waitForTimeout(500);

    // Modal 标题
    await expect(page.locator('h2', { hasText: '新建 Tableau 连接' })).toBeVisible();
    // 连接类型选项
    await expect(page.locator('text=MCP/REST')).toBeVisible();
    await expect(page.locator('text=TSC 直连')).toBeVisible();
    // 必填字段标签
    await expect(page.locator('text=连接名称')).toBeVisible();
    await expect(page.locator('text=Server URL')).toBeVisible();
    await expect(page.locator('text=站点 (Site)')).toBeVisible();
    await expect(page.locator('text=PAT Name')).toBeVisible();
    await expect(page.locator('text=PAT Token')).toBeVisible();
    // 自动同步设置
    await expect(page.locator('text=启用自动同步')).toBeVisible();
    // 操作按钮
    await expect(page.locator('button', { hasText: '取消' })).toBeVisible();
    await expect(page.locator('button', { hasText: '创建' })).toBeVisible();
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
    expect(body).not.toContain('New Connection (CTA)');
  });

  test('筛选复选框可点击切换状态', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await page.waitForTimeout(2000);
    const checkbox = page.locator('text=显示已禁用的连接').locator('..').locator('input[type="checkbox"]');
    const isChecked = await checkbox.isChecked().catch(() => false);
    await page.locator('text=显示已禁用的连接').click();
    await page.waitForTimeout(500);
    const isCheckedAfter = await checkbox.isChecked().catch(() => false);
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
>>>>>>> Stashed changes
  });
});
