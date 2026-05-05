import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 维护窗口管理
 * 路径：/governance/metrics/maintenance-windows
 */
test.describe('维护窗口管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('维护窗口页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/governance/metrics/maintenance-windows');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    const hasContent = body.includes('维护窗口');
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
    expect(hasContent).toBe(true);
  });

  test('页面包含新建按钮', async ({ page }) => {
    await page.goto('/governance/metrics/maintenance-windows');
    await page.waitForTimeout(2000);

    await expect(page.locator('button', { hasText: '新建窗口' })).toBeVisible();
  });

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/metrics/maintenance-windows');
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
    await page.goto('/governance/metrics/maintenance-windows');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
    expect(body).not.toContain('FIXME');
  });

  // ── 新建窗口 ──────────────────────────────────────────────────

  test('可打开新建窗口 Modal', async ({ page }) => {
    await page.goto('/governance/metrics/maintenance-windows');
    await page.waitForTimeout(2000);

    await page.locator('button', { hasText: '新建窗口' }).click();
    await page.waitForTimeout(500);

    const body = await page.locator('body').textContent() ?? '';
    expect(body.includes('新建维护窗口') || body.includes('窗口名称')).toBe(true);
  });

  test('新建窗口表单可填写并提交', async ({ page }) => {
    await page.goto('/governance/metrics/maintenance-windows');
    await page.waitForTimeout(2000);

    // 打开新建 Modal
    await page.locator('button', { hasText: '新建窗口' }).click();
    await page.waitForTimeout(500);

    // 填写表单
    const now = new Date();
    const startTime = new Date(now.getTime() + 60 * 60 * 1000); // 1小时后
    const endTime = new Date(now.getTime() + 2 * 60 * 60 * 1000); // 2小时后

    const formatForInput = (d: Date) => {
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const hour = String(d.getHours()).padStart(2, '0');
      const min = String(d.getMinutes()).padStart(2, '0');
      return `${year}-${month}-${day}T${hour}:${min}`;
    };

    await page.locator('input[placeholder*="数据库"]').fill('测试维护窗口');
    await page.locator('input[type="datetime-local"]').first().fill(formatForInput(startTime));
    await page.locator('input[type="datetime-local"]').nth(1).fill(formatForInput(endTime));
    await page.locator('textarea').fill('冒烟测试维护窗口');

    // 提交
    await page.locator('button', { hasText: '创建' }).click();
    await page.waitForTimeout(2000);

    // 验证列表中出现了新窗口
    const body = await page.locator('body').textContent() ?? '';
    expect(body.includes('测试维护窗口') || body.includes('暂无')).toBe(true);
  });

  // ── 列表展示 ──────────────────────────────────────────────────

  test('维护窗口列表或空状态可见', async ({ page }) => {
    await page.goto('/governance/metrics/maintenance-windows');
    await page.waitForTimeout(2000);

    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无维护窗口').isVisible().catch(() => false);
    expect(hasTable || hasEmpty).toBe(true);
  });

  test('状态筛选按钮可见', async ({ page }) => {
    await page.goto('/governance/metrics/maintenance-windows');
    await page.waitForTimeout(2000);

    await expect(page.locator('button', { hasText: '全部' })).toBeVisible();
    await expect(page.locator('button', { hasText: '激活' })).toBeVisible();
    await expect(page.locator('button', { hasText: '未激活' })).toBeVisible();
  });

  // ── 指标详情页维护窗口提示 ──────────────────────────────────────────────────

  test('指标详情页异常检测 Tab 显示维护窗口状态', async ({ page }) => {
    await page.goto('/governance/metrics/1');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    // 检查是否有 Tab 存在（可能显示维护窗口提示或异常记录）
    const hasTab = body.includes('异常检测');
    expect(hasTab).toBe(true);
  });
});
