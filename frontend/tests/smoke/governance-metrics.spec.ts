import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('治理指标管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('指标管理页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/governance/metrics');
    await expect(page.locator('h1')).toContainText('指标', { timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面结构完整 - 标题、新建按钮、筛选区域均可见', async ({ page }) => {
    await page.goto('/governance/metrics');
    await page.waitForTimeout(2000);

    // 页面主标题
    await expect(page.locator('h1')).toContainText('指标', { timeout: 5000 });
    // 新建按钮
    const addBtn = page.locator('button').filter({ hasText: /新建|新增|添加|创建/ });
    await expect(addBtn.first()).toBeVisible({ timeout: 5000 });
    // 无 404 错误
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('指标类型筛选标签可见（原子/派生/比率）', async ({ page }) => {
    await page.goto('/governance/metrics');
    await page.waitForTimeout(2000);

    await expect(page.locator('text=原子')).toBeVisible();
    await expect(page.locator('text=派生')).toBeVisible();
    await expect(page.locator('text=比率')).toBeVisible();
  });

  test('页面显示指标列表或空状态', async ({ page }) => {
    await page.goto('/governance/metrics');
    await page.waitForTimeout(2000);

    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasCards = await page.locator('[class*="rounded"]').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').isVisible().catch(() => false);
    expect(hasTable || hasCards || hasEmpty).toBe(true);
  });

  test('列表页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/metrics');
    await page.waitForTimeout(2000);
    const realErrors = errors.filter(e =>
      !e.includes('401') && !e.includes('403') && !e.includes('fetch') &&
      !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/governance/metrics');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
  });

  test('新建指标按钮可点击', async ({ page }) => {
    await page.goto('/governance/metrics');
    await page.waitForTimeout(2000);
    const addBtn = page.locator('button').filter({ hasText: /新建|新增|添加|创建/ });
    await expect(addBtn.first()).toBeEnabled({ timeout: 5000 });
  });
});
