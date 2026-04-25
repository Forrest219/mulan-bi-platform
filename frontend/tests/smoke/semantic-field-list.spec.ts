import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 语义 - 字段管理列表页
 * 路径：/governance/semantic/fields（重定向到 /semantic-maintenance/fields）
 */
test.describe('语义 - 字段管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('字段语义管理页可访问', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForLoadState('networkidle');
    expect(page.url()).toContain('/semantic-maintenance/fields');
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/semantic/fields');
    await page.waitForTimeout(2000);
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('fetch') &&
      !e.includes('favicon') &&
      !e.includes('Failed to load resource') &&
      !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  // ── 页面结构 ──────────────────────────────────────────────────

  test('页面标题和副标题可见', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h1')).toContainText('字段语义管理', { timeout: 5000 });
    await expect(page.locator('text=批量管理和审核字段语义')).toBeVisible();
  });

  test('有同步字段按钮', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForLoadState('networkidle');
    const hasSyncBtn = await page.locator('button').filter({ hasText: /同步字段/ }).first().isVisible().catch(() => false);
    expect(hasSyncBtn).toBe(true);
  });

  test('有连接选择下拉框', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForLoadState('networkidle');
    const hasSelect = await page.locator('select').first().isVisible().catch(() => false);
    expect(hasSelect).toBe(true);
  });

  test('有状态筛选下拉框', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForLoadState('networkidle');
    const hasStatusFilter = await page.locator('text=状态').isVisible().catch(() => false);
    expect(hasStatusFilter).toBe(true);
  });

  // ── 列表状态 ──────────────────────────────────────────────────

  test('未选连接时显示请先选择连接', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForTimeout(1500);
    const hasEmpty = await page.locator('text=暂无数据').isVisible().catch(() => false);
    const hasPrompt = await page.locator('text=请先选择连接').isVisible().catch(() => false);
    expect(hasEmpty || hasPrompt).toBe(true);
  });

  test('有加载状态或表格或空状态', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForTimeout(2000);
    const hasLoading = await page.locator('text=加载中').isVisible().catch(() => false);
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无数据').isVisible().catch(() => false);
    expect(hasLoading || hasTable || hasEmpty).toBe(true);
  });

  test('表格表头包含 ID、字段名称、语义名称等列', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForTimeout(2000);
    const hasIdHeader = await page.locator('th', { hasText: 'ID' }).first().isVisible().catch(() => false);
    const hasFieldHeader = await page.locator('th', { hasText: '字段名称' }).first().isVisible().catch(() => false);
    const hasSemanticHeader = await page.locator('th', { hasText: '语义名称' }).first().isVisible().catch(() => false);
    expect(hasIdHeader && hasFieldHeader && hasSemanticHeader).toBe(true);
  });

  // ── 无英文占位文案残留 ─────────────────────────────────────────

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/governance/semantic/fields');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('PLACEHOLDER');
    expect(body).not.toContain('Import Placeholder');
  });

  // ── 路由兼容性 ───────────────────────────────────────────────

  test('/semantic-maintenance/fields 路径可直接访问', async ({ page }) => {
    await page.goto('/semantic-maintenance/fields');
    await page.waitForTimeout(2000);
    expect(page.url()).toContain('/semantic-maintenance/fields');
    const hasContent = await page.locator('h1').first().isVisible().catch(() => false);
    expect(hasContent).toBe(true);
  });
});
