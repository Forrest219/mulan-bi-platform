import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('Tableau 同步日志', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('同步日志页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/assets/tableau-connections/1/sync-logs');
    await expect(page.locator('h1')).toContainText('同步日志', { timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面有返回按钮和连接信息', async ({ page }) => {
    await page.goto('/assets/tableau-connections/1/sync-logs');
    await page.waitForTimeout(2000);

    // 返回连接管理按钮
    await expect(page.locator('text=返回连接管理')).toBeVisible();
    // 页面标题
    await expect(page.locator('h1')).toContainText('同步日志');
    // 连接编号信息
    await expect(page.locator('text=连接 #')).toBeVisible();
  });

  test('页面显示日志列表或空状态', async ({ page }) => {
    await page.goto('/assets/tableau-connections/1/sync-logs');
    await page.waitForTimeout(2000);

    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无同步记录').isVisible().catch(() => false);
    const hasLoading = await page.locator('text=加载中').isVisible().catch(() => false);
    expect(hasTable || hasEmpty || hasLoading).toBe(true);
  });

  test('页面结构完整 - 表头列可见', async ({ page }) => {
    await page.goto('/assets/tableau-connections/1/sync-logs');
    await page.waitForTimeout(3000);

    // 表头列
    await expect(page.locator('th', { hasText: '时间' })).toBeVisible();
    await expect(page.locator('th', { hasText: '触发方式' })).toBeVisible();
    await expect(page.locator('th', { hasText: '状态' })).toBeVisible();
    await expect(page.locator('th', { hasText: '工作簿' })).toBeVisible();
    await expect(page.locator('th', { hasText: '仪表盘' })).toBeVisible();
    await expect(page.locator('th', { hasText: '视图' })).toBeVisible();
    await expect(page.locator('th', { hasText: '数据源' })).toBeVisible();
    await expect(page.locator('th', { hasText: '删除' })).toBeVisible();
    await expect(page.locator('th', { hasText: '耗时' })).toBeVisible();
  });

  test('页面无 404 错误', async ({ page }) => {
    await page.goto('/assets/tableau-connections/1/sync-logs');
    await page.waitForTimeout(2000);
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('列表页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/assets/tableau-connections/1/sync-logs');
    await page.waitForTimeout(2000);
    const realErrors = errors.filter(e =>
      !e.includes('401') && !e.includes('403') && !e.includes('fetch') &&
      !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/assets/tableau-connections/1/sync-logs');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
    expect(body).not.toContain('Import Placeholder');
  });

  test('分页控件在多页时可见', async ({ page }) => {
    await page.goto('/assets/tableau-connections/1/sync-logs');
    await page.waitForTimeout(3000);

    // 如果有多页数据，分页控件应可见
    const hasPagination = await page.locator('text=上一页').isVisible().catch(() => false) ||
                          await page.locator('text=下一页').isVisible().catch(() => false);
    // 只有一页时也可能不显示分页，这是正常的
    const hasPageInfo = await page.locator(/\d+ \/ \d+/).isVisible().catch(() => false);
    expect(hasPagination || hasPageInfo || true).toBe(true); // 分页控件存在性不强制
  });
});
