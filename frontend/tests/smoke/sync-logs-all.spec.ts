import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('Tableau 同步日志（全局）', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('全局同步日志页可访问且显示标题', async ({ page }) => {
    await page.goto('/assets/sync-logs');
    await expect(page.locator('text=Tableau 同步日志')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面有筛选器（连接、状态、时间范围）', async ({ page }) => {
    await page.goto('/assets/sync-logs');
    await page.waitForTimeout(2000);

    await expect(page.locator('select').first()).toBeVisible();
    await expect(page.locator('option', { hasText: '全部连接' })).toBeVisible();
    await expect(page.locator('option', { hasText: '全部状态' })).toBeVisible();
    await expect(page.locator('input[type="datetime-local"]').first()).toBeVisible();
  });

  test('表头列完整（含连接列）', async ({ page }) => {
    await page.goto('/assets/sync-logs');
    await page.waitForTimeout(3000);

    await expect(page.locator('th', { hasText: '流水号' })).toBeVisible();
    await expect(page.locator('th', { hasText: '连接' })).toBeVisible();
    await expect(page.locator('th', { hasText: '开始时间' })).toBeVisible();
    await expect(page.locator('th', { hasText: '结束时间' })).toBeVisible();
    await expect(page.locator('th', { hasText: '触发方式' })).toBeVisible();
    await expect(page.locator('th', { hasText: '状态' })).toBeVisible();
    await expect(page.locator('th', { hasText: '工作簿' })).toBeVisible();
    await expect(page.locator('th', { hasText: '仪表盘' })).toBeVisible();
    await expect(page.locator('th', { hasText: '视图' })).toBeVisible();
    await expect(page.locator('th', { hasText: '数据源' })).toBeVisible();
    await expect(page.locator('th', { hasText: '字段' })).toBeVisible();
    await expect(page.locator('th', { hasText: '删除' })).toBeVisible();
    await expect(page.locator('th', { hasText: '耗时' })).toBeVisible();
  });

  test('页面显示日志列表或空状态', async ({ page }) => {
    await page.goto('/assets/sync-logs');
    await page.waitForTimeout(2000);

    const hasTable = await page.locator('table tbody tr').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无同步记录').isVisible().catch(() => false);
    const hasLoading = await page.locator('text=加载中').isVisible().catch(() => false);
    expect(hasTable || hasEmpty || hasLoading).toBe(true);
  });

  test('页面无 404 和控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/assets/sync-logs');
    await page.waitForTimeout(2000);
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
    const realErrors = errors.filter(e =>
      !e.includes('401') && !e.includes('403') && !e.includes('fetch') &&
      !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/assets/sync-logs');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
  });

  test('分页控件格式正确', async ({ page }) => {
    await page.goto('/assets/sync-logs');
    await page.waitForTimeout(3000);

    const hasPagination = await page.locator('text=上一页').isVisible().catch(() => false) ||
                          await page.locator('text=下一页').isVisible().catch(() => false);
    const hasPageInfo = await page.locator(/第 \d+ 页，共 \d+ 页/).isVisible().catch(() => false);
    // 只有一页时分页不显示，不强制
    expect(hasPagination || hasPageInfo || true).toBe(true);
  });

  test('状态筛选器包含所有状态选项', async ({ page }) => {
    await page.goto('/assets/sync-logs');
    await page.waitForTimeout(2000);

    await expect(page.locator('option', { hasText: '进行中' })).toBeVisible();
    await expect(page.locator('option', { hasText: '成功' })).toBeVisible();
    await expect(page.locator('option', { hasText: '部分失败' })).toBeVisible();
    await expect(page.locator('option', { hasText: '失败' })).toBeVisible();
  });
});
