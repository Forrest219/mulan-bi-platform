import { expect, test, type Page } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? process.env.SMOKE_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? process.env.SMOKE_ADMIN_PASSWORD ?? 'admin123';

async function loginAsAdmin(page: Page) {
  const adminUser = {
    id: 1,
    username: ADMIN_USERNAME,
    display_name: '管理员',
    email: 'admin@mulan.local',
    role: 'admin',
    permissions: [],
    all_permissions: [
      'ddl_check',
      'ddl_generator',
      'database_monitor',
      'rule_config',
      'scan_logs',
      'user_management',
      'tableau',
      'llm',
    ],
    group_ids: [],
    group_names: [],
    is_active: true,
    created_at: '2026-05-01 00:00:00',
    last_login: '2026-05-10 10:00:00',
  };

  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(adminUser),
    });
  });

  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: '登录成功',
        mfa_required: false,
        user: adminUser,
      }),
    });
  });

  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Token 已刷新' }),
    });
  });

  await page.goto('/login');
  await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL('/', { timeout: 5000 });
}

async function mockActivityApis(page: Page) {
  const logRequests: URL[] = [];
  let resolveExportUrl: (url: URL) => void = () => {};
  const exportUrlPromise = new Promise<URL>((resolve) => {
    resolveExportUrl = resolve;
  });

  await page.route('**/api/permissions/users', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        users: [
          {
            id: 1,
            username: 'admin',
            display_name: '管理员',
            tag: '活跃',
            tag_emoji: '🟢',
            tag_color: 'emerald',
            days_since_login: 0,
          },
          {
            id: 2,
            username: 'alice',
            display_name: 'Alice 分析师',
            tag: '正常',
            tag_emoji: '🔵',
            tag_color: 'blue',
            days_since_login: 3,
          },
        ],
      }),
    });
  });

  await page.route('**/api/activity/types', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ types: ['login', 'logout', 'permission_update'] }),
    });
  });

  await page.route('**/api/activity/stats**', async (route) => {
    const url = new URL(route.request().url());
    const userId = url.searchParams.get('user_id');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_users: userId ? 1 : 2,
        active_users: userId ? 1 : 2,
        active_rate: 100,
        tag_counts: userId === '2'
          ? { 活跃: 0, 正常: 1, 冷门: 0, 潜水: 0, 僵尸: 0 }
          : { 活跃: 1, 正常: 1, 冷门: 0, 潜水: 0, 僵尸: 0 },
        operation_stats: userId ? { total: 1 } : {},
      }),
    });
  });

  await page.route((url) => url.pathname === '/api/activity/logs/export', async (route) => {
    const url = new URL(route.request().url());
    resolveExportUrl(url);
    await route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/csv;charset=utf-8',
        'Content-Disposition': "attachment; filename*=UTF-8''activity-logs-smoke.csv",
      },
      body: 'id,operator,operation_type\n9002,alice,permission_update\n',
    });
  });

  await page.route((url) => url.pathname === '/api/activity/logs', async (route) => {
    const url = new URL(route.request().url());
    logRequests.push(url);
    const operationType = url.searchParams.get('operation_type');
    const userId = url.searchParams.get('user_id');
    const logs = [
      {
        id: 9001,
        op_time: '2026-05-10 10:00:00',
        operator: 'admin',
        operator_id: 1,
        operation_type: operationType || 'login',
        target: 'admin',
        status: 'success',
        details: { message: 'mock-login-detail' },
        ip_address: '10.0.0.1',
        user_agent: 'SmokeBrowser/1.0',
        trace_id: 'trace-smoke-1',
      },
      {
        id: 9002,
        op_time: '2026-05-10 10:05:00',
        operator: 'alice',
        operator_id: 2,
        operation_type: 'permission_update',
        target: '用户权限',
        status: 'success',
        details: 'plain-detail-not-json',
        ip_address: '10.0.0.2',
        user_agent: 'SmokeBrowser/2.0',
        trace_id: 'trace-smoke-2',
      },
    ].filter((log) => !userId || String(log.operator_id) === userId);

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        logs,
        total: logs.length,
        page: Number(url.searchParams.get('page') || 1),
        page_size: Number(url.searchParams.get('page_size') || 20),
        pages: 1,
      }),
    });
  });

  return { logRequests, exportUrlPromise };
}

test.describe('操作日志', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('操作日志页渲染分页列表、统计卡片和动态操作类型', async ({ page }) => {
    const { logRequests } = await mockActivityApis(page);

    await page.goto('/system/activity');

    await expect(page.getByRole('heading', { name: '操作日志' }).first()).toBeVisible();
    await expect(page.getByText('用户活动统计和登录记录')).toBeVisible();
    await expect(page.getByText('总用户数')).toBeVisible();
    await expect(page.locator('main').getByText('管理员')).toBeVisible();
    await expect(page.locator('main').getByText('Alice 分析师')).toBeVisible();
    await expect(page.getByText('10.0.0.1')).toBeVisible();
    await expect(page.locator('select')).toContainText('permission_update');

    await expect.poll(() => logRequests.length).toBeGreaterThan(0);
    const firstRequest = logRequests[0];
    expect(firstRequest.searchParams.get('page')).toBe('1');
    expect(firstRequest.searchParams.get('page_size')).toBe('20');
    expect(firstRequest.searchParams.get('start_time')).toBeTruthy();
    expect(firstRequest.searchParams.get('end_time')).toBeTruthy();
  });

  test('时间、操作类型、用户下钻筛选会进入服务端查询参数', async ({ page }) => {
    const { logRequests, exportUrlPromise } = await mockActivityApis(page);

    await page.goto('/system/activity');
    await expect(page.locator('main').getByText('Alice 分析师')).toBeVisible();

    await page.locator('select').selectOption('permission_update');
    await expect.poll(() => logRequests.some((url) => url.searchParams.get('operation_type') === 'permission_update')).toBe(true);

    await page.getByRole('button', { name: '自定义' }).click();
    await page.locator('input[type="date"]').first().fill('2026-05-01');
    await page.locator('input[type="date"]').nth(1).fill('2026-05-10');
    await expect.poll(() => logRequests.some((url) => url.searchParams.get('start_time')?.startsWith('2026-05-01'))).toBe(true);

    await page.locator('main').getByText('Alice 分析师').click();
    await expect(page.getByText('已锁定特定用户')).toBeVisible();
    await expect.poll(() => logRequests.some((url) => url.searchParams.get('user_id') === '2')).toBe(true);

    await page.getByRole('button', { name: '导出报告' }).click();
    const exportUrl = await exportUrlPromise;
    expect(exportUrl.searchParams.get('operation_type')).toBe('permission_update');
    expect(exportUrl.searchParams.get('user_id')).toBe('2');
    expect(exportUrl.searchParams.get('start_time')).toContain('2026-05-01');
  });

  test('日志详情抽屉展示完整字段，非 JSON details 不会崩溃', async ({ page }) => {
    await mockActivityApis(page);

    await page.goto('/system/activity');
    await expect(page.locator('main').getByText('Alice 分析师')).toBeVisible();

    await page.getByRole('row', { name: /alice/ }).click();
    await expect(page.getByRole('heading', { name: '操作详情' })).toBeVisible();
    await expect(page.getByText('trace-smoke-2')).toBeVisible();
    await expect(page.getByText('SmokeBrowser/2.0')).toBeVisible();
    await expect(page.getByText('plain-detail-not-json')).toBeVisible();
  });
});
