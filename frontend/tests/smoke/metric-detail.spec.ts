import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 指标详情页
 * 路径：/governance/metrics/:id
 * Tab 切换：基本信息 / 指标血缘 / 一致性校验 / 异常检测
 */
test.describe('指标详情', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('指标详情页可访问（使用 ID=1）', async ({ page }) => {
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);

    // 页面可能加载成功显示指标内容，或因为 ID 不存在显示错误
    const body = await page.locator('body').textContent() ?? '';
    const hasMetricContent = body.includes('指标管理') || // 面包屑
      body.includes('基本信息') || // Tab
      body.includes('加载中') ||
      body.includes('获取指标详情失败') ||
      body.includes('返回指标列表');
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
    expect(hasMetricContent).toBe(true);
  });

  test('面包屑导航包含"指标管理"链接', async ({ page }) => {
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    // 面包屑或返回链接
    const hasBreadcrumb = body.includes('指标管理') || body.includes('返回指标列表');
    expect(hasBreadcrumb).toBe(true);
  });

  test('四个 Tab 按钮可见（成功加载时）', async ({ page }) => {
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    // 只在页面成功加载指标时检查 Tab
    if (body.includes('基本信息')) {
      await expect(page.locator('button', { hasText: '基本信息' })).toBeVisible();
      await expect(page.locator('button', { hasText: '指标血缘' })).toBeVisible();
      await expect(page.locator('button', { hasText: '一致性校验' })).toBeVisible();
      await expect(page.locator('button', { hasText: '异常检测' })).toBeVisible();
    }
  });

  // ── Tab 切换 ──────────────────────────────────────────────────

  test('可切换到指标血缘 Tab', async ({ page }) => {
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('基本信息')) {
      await page.locator('button', { hasText: '指标血缘' }).click();
      await page.waitForTimeout(1000);

      const updatedBody = await page.locator('body').textContent() ?? '';
      const hasLineageContent = updatedBody.includes('血缘') ||
        updatedBody.includes('暂无血缘记录') ||
        updatedBody.includes('加载血缘数据中');
      expect(hasLineageContent).toBe(true);
    }
  });

  test('可切换到一致性校验 Tab', async ({ page }) => {
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('基本信息')) {
      await page.locator('button', { hasText: '一致性校验' }).click();
      await page.waitForTimeout(1000);

      const updatedBody = await page.locator('body').textContent() ?? '';
      const hasConsistencyContent = updatedBody.includes('一致性') ||
        updatedBody.includes('暂无一致性校验记录') ||
        updatedBody.includes('校验记录');
      expect(hasConsistencyContent).toBe(true);
    }
  });

  test('可切换到异常检测 Tab', async ({ page }) => {
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('基本信息')) {
      await page.locator('button', { hasText: '异常检测' }).click();
      await page.waitForTimeout(1000);

      const updatedBody = await page.locator('body').textContent() ?? '';
      const hasAnomalyContent = updatedBody.includes('异常') ||
        updatedBody.includes('暂无异常记录') ||
        updatedBody.includes('异常记录');
      expect(hasAnomalyContent).toBe(true);
    }
  });

  // ── 无报错 ────────────────────────────────────────────────────

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('fetch') &&
      !e.includes('favicon') &&
      !e.includes('Failed to load resource') &&
      !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
    expect(body).not.toContain('FIXME');
  });
});
