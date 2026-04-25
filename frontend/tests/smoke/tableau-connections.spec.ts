import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD=process.env.ADMIN_PASSWORD ?? 'admin123';

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
});
