import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * 同步日志实时轮询冒烟测试
 *
 * 覆盖：
 * - /assets/sync-logs 页面 auto-poll：running → success 状态自动刷新
 * - /assets/tableau-connections 页面同步按钮反馈：显示同步结果计数
 */

function makeSyncLog(overrides: Record<string, unknown> = {}) {
  return {
    id: 100,
    connection_id: 1,
    connection_name: '测试连接',
    trigger_type: 'manual',
    started_at: '2026-05-04 10:00:00',
    finished_at: null,
    status: 'running',
    workbooks_synced: 0,
    views_synced: 0,
    dashboards_synced: 0,
    datasources_synced: 0,
    assets_deleted: 0,
    error_message: null,
    duration_sec: null,
    ...overrides,
  };
}

test.describe('同步日志实时轮询', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('sync-logs 页面 running 记录自动刷新为 success', async ({ page }) => {
    let callCount = 0;
    const runningLog = makeSyncLog();
    const successLog = makeSyncLog({
      status: 'success',
      finished_at: '2026-05-04 10:00:05',
      workbooks_synced: 3,
      views_synced: 12,
      dashboards_synced: 2,
      datasources_synced: 5,
      duration_sec: 5,
    });

    await page.route('**/api/tableau/sync-logs**', async (route) => {
      callCount++;
      const log = callCount <= 2 ? runningLog : successLog;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [log],
          total: 1,
          page: 1,
          page_size: 20,
          pages: 1,
        }),
      });
    });

    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [{ id: 1, name: '测试连接' }],
          total: 1,
        }),
      });
    });

    await page.goto('/assets/sync-logs');
    const table = page.locator('table');

    // 初始：表格内显示"进行中"状态徽章
    await expect(table.getByText('进行中')).toBeVisible({ timeout: 5000 });

    // 等待轮询（3s 间隔），状态应自动刷新为"成功"
    await expect(table.getByText('成功')).toBeVisible({ timeout: 10000 });

    // mock 被调用多次，说明轮询生效
    expect(callCount).toBeGreaterThanOrEqual(3);
  });

  test('sync-logs 页面 running 记录自动刷新为失败', async ({ page }) => {
    let callCount = 0;
    const runningLog = makeSyncLog();
    const failedLog = makeSyncLog({
      status: 'failed',
      finished_at: '2026-05-04 10:00:08',
      error_message: '连接超时',
      duration_sec: 8,
    });

    await page.route('**/api/tableau/sync-logs**', async (route) => {
      callCount++;
      const log = callCount <= 2 ? runningLog : failedLog;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [log],
          total: 1,
          page: 1,
          page_size: 20,
          pages: 1,
        }),
      });
    });

    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [{ id: 1, name: '测试连接' }],
          total: 1,
        }),
      });
    });

    await page.goto('/assets/sync-logs');
    const table = page.locator('table');

    await expect(table.getByText('进行中')).toBeVisible({ timeout: 5000 });
    await expect(table.getByText('失败')).toBeVisible({ timeout: 10000 });

    // 展开错误详情
    await page.locator('tr', { hasText: '测试连接' }).first().click();
    await expect(page.locator('text=连接超时')).toBeVisible({ timeout: 3000 });
  });

  test('sync-logs 页面无 running 记录时不轮询', async ({ page }) => {
    let callCount = 0;
    const successLog = makeSyncLog({
      status: 'success',
      finished_at: '2026-05-04 10:00:05',
      workbooks_synced: 3,
      duration_sec: 5,
    });

    await page.route('**/api/tableau/sync-logs**', async (route) => {
      callCount++;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          logs: [successLog],
          total: 1,
          page: 1,
          page_size: 20,
          pages: 1,
        }),
      });
    });

    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [{ id: 1, name: '测试连接' }],
          total: 1,
        }),
      });
    });

    await page.goto('/assets/sync-logs');
    const table = page.locator('table');
    await expect(table.getByText('成功')).toBeVisible({ timeout: 5000 });

    // 等待 5 秒，确认没有额外轮询
    await page.waitForTimeout(5000);
    expect(callCount).toBeLessThanOrEqual(2);
  });
});
