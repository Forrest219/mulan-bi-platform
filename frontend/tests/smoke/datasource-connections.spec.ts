import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD=process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('数据源管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('数据源管理页可访问', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');
    expect(page.url()).toContain('/assets/datasources');
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
    // 页面应显示标题或错误状态（API 依赖后端）
    const hasH1 = await page.locator('h1').isVisible().catch(() => false);
    const hasSidebar = await page.locator('text=数据源管理').isVisible().catch(() => false);
    expect(hasH1 || hasSidebar).toBe(true);
  });

  test('页面有新建按钮或加载状态', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');
    const hasBtn = await page.locator('button').filter({ hasText: /新建|新增|添加|创建/ }).first().isVisible().catch(() => false);
    const hasContent = await page.locator('text=数据源').first().isVisible().catch(() => false);
    expect(hasBtn || hasContent).toBe(true);
  });

  test('页面显示数据表格或空状态', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForTimeout(2000);
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasCards = await page.locator('[class*="rounded"]').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').isVisible().catch(() => false);
    expect(hasTable || hasCards || hasEmpty).toBe(true);
  });

  test('页面结构完整 - 标题、副标题、新建按钮均可见', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');

    // 页面主标题
    await expect(page.locator('h1')).toContainText('数据源管理', { timeout: 5000 });
    // 副标题
    await expect(page.locator('text=管理数据库连接与数据源配置')).toBeVisible();
    // 新建按钮
    await expect(page.locator('button', { hasText: '新建数据源' })).toBeVisible();
    // 无 404 错误
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('打开新建数据源 Modal，表单字段完整可见', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');
    await page.locator('button', { hasText: '新建数据源' }).click();
    await page.waitForTimeout(500);

    // Modal 标题
    await expect(page.locator('h2', { hasText: '新建数据源' })).toBeVisible();
    // 数据库类型下拉框
    await expect(page.locator('text=数据库类型')).toBeVisible();
    // 必填字段标签
    await expect(page.locator('text=名称')).toBeVisible();
    await expect(page.locator('text=Host')).toBeVisible();
    await expect(page.locator('text=端口')).toBeVisible();
    await expect(page.locator('text=数据库名')).toBeVisible();
    await expect(page.locator('text=用户名')).toBeVisible();
    await expect(page.locator('text=密码')).toBeVisible();
    // 操作按钮
    await expect(page.locator('button', { hasText: '取消' })).toBeVisible();
    await expect(page.locator('button', { hasText: '创建' })).toBeVisible();
  });

  test('新建 Modal 可取消关闭', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');
    await page.locator('button', { hasText: '新建数据源' }).click();
    await page.waitForTimeout(500);
    await expect(page.locator('h2', { hasText: '新建数据源' })).toBeVisible();
    await page.locator('button', { hasText: '取消' }).click();
    await page.waitForTimeout(500);
    await expect(page.locator('h2', { hasText: '新建数据源' })).not.toBeVisible();
  });

  test('列表页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    const realErrors = errors.filter(e =>
      !e.includes('401') && !e.includes('403') && !e.includes('fetch') &&
      !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/assets/datasources');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('Import Placeholder');
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('option C shell');
    expect(body).not.toContain('Owner placeholder');
  });

  test('连接中心有数据源管理跳转链接', async ({ page }) => {
    await page.goto('/assets/connection-center?type=db');
    await page.waitForTimeout(1000);
    await expect(page.locator('a[href="/assets/datasources"]').last()).toBeVisible({ timeout: 3000 });
  });
});
