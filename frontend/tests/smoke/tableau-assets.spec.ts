import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('Tableau 资产浏览', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('资产浏览页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/assets/tableau');
    await expect(page.locator('h1')).toContainText('Tableau 资产浏览', { timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面有连接选择器', async ({ page }) => {
    await page.goto('/assets/tableau');
    const selector = page.locator('select');
    await expect(selector).toBeVisible({ timeout: 5000 });
  });

  test('页面有资产类型筛选按钮', async ({ page }) => {
    await page.goto('/assets/tableau');
    await expect(page.locator('button').filter({ hasText: '全部' })).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button').filter({ hasText: '工作簿' })).toBeVisible();
  });

  test('空状态显示同步按钮而非纯文字提示', async ({ page }) => {
    // mock 连接列表返回一个连接，资产列表返回空
    await page.route('**/api/tableau/connections', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [{
            id: 1,
            name: 'test_conn',
            server_url: 'https://tableau.test',
            is_active: true,
            last_test_success: true,
            connection_type: 'mcp',
          }],
        }),
      })
    );
    await page.route('**/api/tableau/assets**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ assets: [], total: 0 }),
      })
    );
    await page.route('**/api/tableau/projects**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ projects: [] }),
      })
    );

    await page.goto('/assets/tableau?connection_id=1');

    // 空状态提示文案
    await expect(page.locator('text=未找到资产')).toBeVisible({ timeout: 5000 });

    // 同步按钮存在且可点击
    const syncBtn = page.locator('[data-testid="empty-sync-btn"]');
    await expect(syncBtn).toBeVisible();
    await expect(syncBtn).toContainText('同步资产');
  });

  test('点击同步按钮发送 POST 请求', async ({ page }) => {
    // mock 连接 + 空资产
    await page.route('**/api/tableau/connections', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [{ id: 99, name: 'mock_conn', server_url: 'https://t.test', is_active: true, last_test_success: true, connection_type: 'mcp' }],
        }),
      })
    );
    await page.route('**/api/tableau/assets**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ assets: [], total: 0 }),
      })
    );
    await page.route('**/api/tableau/projects**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ projects: [] }),
      })
    );

    // mock 同步请求
    let syncCalled = false;
    await page.route('**/api/tableau/connections/99/sync', route => {
      syncCalled = true;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: 'mock-task', message: '同步任务已提交', status: 'pending' }),
      });
    });

    await page.goto('/assets/tableau?connection_id=99');
    await expect(page.locator('[data-testid="empty-sync-btn"]')).toBeVisible({ timeout: 5000 });
    await page.locator('[data-testid="empty-sync-btn"]').click();

    // 验证成功反馈文案渲染到 DOM
    await expect(page.locator('text=同步任务已提交')).toBeVisible({ timeout: 5000 });
    expect(syncCalled).toBe(true);
  });

  test('同步失败时结构化错误对象正确显示中文消息而非 [object Object]', async ({ page }) => {
    await page.route('**/api/tableau/connections', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [{ id: 1, name: 'conn', server_url: 'https://t.test', is_active: true, last_test_success: true, connection_type: 'mcp' }],
        }),
      })
    );
    await page.route('**/api/tableau/assets**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ assets: [], total: 0 }),
      })
    );
    await page.route('**/api/tableau/projects**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ projects: [] }),
      })
    );

    // mock 同步返回结构化错误对象（后端权限校验格式）
    await page.route('**/api/tableau/connections/1/sync', route =>
      route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: { error_code: 'TAB_002', message: '无权访问此连接', detail: {} },
        }),
      })
    );

    await page.goto('/assets/tableau?connection_id=1');
    await page.locator('[data-testid="empty-sync-btn"]').click();

    // 必须显示结构化错误中的中文 message，不能显示 [object Object]
    await expect(page.locator('text=无权访问此连接')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=[object Object]')).toHaveCount(0);
  });

  test('同步失败时纯字符串错误正确显示', async ({ page }) => {
    await page.route('**/api/tableau/connections', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [{ id: 1, name: 'conn', server_url: 'https://t.test', is_active: true, last_test_success: true, connection_type: 'mcp' }],
        }),
      })
    );
    await page.route('**/api/tableau/assets**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ assets: [], total: 0 }),
      })
    );
    await page.route('**/api/tableau/projects**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ projects: [] }),
      })
    );

    await page.route('**/api/tableau/connections/1/sync', route =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '连接不存在' }),
      })
    );

    await page.goto('/assets/tableau?connection_id=1');
    await page.locator('[data-testid="empty-sync-btn"]').click();

    await expect(page.locator('text=连接不存在')).toBeVisible({ timeout: 5000 });
  });

  test('有资产时展示资产卡片', async ({ page }) => {
    await page.route('**/api/tableau/connections', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [{ id: 1, name: 'conn', server_url: 'https://t.test', is_active: true, last_test_success: true, connection_type: 'mcp' }],
        }),
      })
    );
    await page.route('**/api/tableau/assets**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          assets: [
            { id: 1, name: '销售分析看板', asset_type: 'workbook', project_name: '财务', owner_name: '张三', view_count: 42 },
            { id: 2, name: '月度报表', asset_type: 'view', project_name: '财务', owner_name: '李四', view_count: 10, parent_workbook_name: '销售分析看板' },
          ],
          total: 2,
        }),
      })
    );
    await page.route('**/api/tableau/projects**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ projects: [{ name: '财务', children: {} }] }),
      })
    );

    await page.goto('/assets/tableau?connection_id=1');

    // 资产卡片中显示 mock 数据
    await expect(page.locator('text=销售分析看板').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=月度报表')).toBeVisible();
    // 同步按钮在有资产时不应出现
    await expect(page.locator('[data-testid="empty-sync-btn"]')).toHaveCount(0);
  });
});
