import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: Agent 监控页
 * 路径：/system/agent-monitor（adminOnly）
 * Tab 切换：总览 / 工具列表 / 会话管理
 */
test.describe('Agent 监控', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('Agent 监控页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/system/agent-monitor');
    await expect(page.locator('h1')).toContainText('Agent 监控', { timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面结构完整 - 标题和副标题可见', async ({ page }) => {
    await page.goto('/system/agent-monitor');
    await page.waitForTimeout(2000);

    await expect(page.locator('h1')).toContainText('Agent 监控', { timeout: 5000 });
    const body = await page.locator('body').textContent() ?? '';
    expect(body).toContain('Data Agent');
  });

  test('Tab 导航按钮可见（总览 / 工具列表 / 会话管理）', async ({ page }) => {
    await page.goto('/system/agent-monitor');
    await page.waitForTimeout(2000);

    await expect(page.locator('button', { hasText: '总览' })).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button', { hasText: '工具列表' })).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button', { hasText: '会话管理' })).toBeVisible({ timeout: 5000 });
  });

  // ── 总览 Tab ──────────────────────────────────────────────────

  test('总览默认显示统计卡片或加载状态', async ({ page }) => {
    await page.goto('/system/agent-monitor');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    const hasStats = body.includes('总调用量') ||
      body.includes('成功率') ||
      body.includes('平均耗时') ||
      body.includes('加载中');
    expect(hasStats).toBe(true);
  });

  test('总览包含运行列表或空状态', async ({ page }) => {
    await page.goto('/system/agent-monitor');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    const hasRunList = body.includes('近期运行') ||
      body.includes('暂无运行记录') ||
      body.includes('加载中');
    expect(hasRunList).toBe(true);
  });

  test('总览包含状态筛选按钮（全部 / 成功 / 失败 / 运行中）', async ({ page }) => {
    await page.goto('/system/agent-monitor');
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent() ?? '';
    if (body.includes('近期运行')) {
      await expect(page.locator('button', { hasText: '全部' }).first()).toBeVisible();
      await expect(page.locator('button', { hasText: '成功' }).first()).toBeVisible();
      await expect(page.locator('button', { hasText: '失败' }).first()).toBeVisible();
      await expect(page.locator('button', { hasText: '运行中' }).first()).toBeVisible();
    }
  });

  // ── Tab 切换 ──────────────────────────────────────────────────

  test('可切换到工具列表 Tab', async ({ page }) => {
    await page.goto('/system/agent-monitor');
    await page.waitForTimeout(2000);

    await page.locator('button', { hasText: '工具列表' }).click();
    await page.waitForTimeout(1000);

    const body = await page.locator('body').textContent() ?? '';
    const hasToolsContent = body.includes('可用工具') ||
      body.includes('暂无已注册的工具') ||
      body.includes('加载中');
    expect(hasToolsContent).toBe(true);
  });

  test('可切换到会话管理 Tab', async ({ page }) => {
    await page.goto('/system/agent-monitor');
    await page.waitForTimeout(2000);

    await page.locator('button', { hasText: '会话管理' }).click();
    await page.waitForTimeout(1000);

    const body = await page.locator('body').textContent() ?? '';
    const hasSessionsContent = body.includes('Agent 会话') ||
      body.includes('暂无会话记录') ||
      body.includes('加载中');
    expect(hasSessionsContent).toBe(true);
  });

  // ── 无报错 ────────────────────────────────────────────────────

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/system/agent-monitor');
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
    await page.goto('/system/agent-monitor');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
    expect(body).not.toContain('FIXME');
  });
});
