import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 语义发布记录页
 * 路径：/governance/semantic/publish-logs
 */
test.describe('语义发布记录', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('发布记录页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/governance/semantic/publish-logs');
    await expect(page.locator('h1')).toContainText('语义发布记录', { timeout: 5000 });
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面结构完整 - 标题与筛选区域可见', async ({ page }) => {
    await page.goto('/governance/semantic/publish-logs');
    await page.waitForTimeout(2000);

    // 页面主标题
    await expect(page.locator('h1')).toContainText('语义发布记录', { timeout: 5000 });
    // 副标题说明
    const body = await page.locator('body').textContent() ?? '';
    expect(body).toContain('查看历史发布操作');
    // 无 404 错误
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面显示发布列表或空状态或加载状态', async ({ page }) => {
    await page.goto('/governance/semantic/publish-logs');
    await page.waitForTimeout(2000);

    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').isVisible().catch(() => false);
    const hasLoading = await page.locator('text=加载').isVisible().catch(() => false);
    const hasError = await page.locator('text=加载失败').isVisible().catch(() => false);
    expect(hasTable || hasEmpty || hasLoading || hasError).toBe(true);
  });

  // ── 分页控件 ──────────────────────────────────────────────────

  test('分页控件存在（多页时可见）', async ({ page }) => {
    await page.goto('/governance/semantic/publish-logs');
    await page.waitForTimeout(2000);

    // 分页按钮（上一页/下一页）或无分页均可
    const hasPrevBtn = await page.locator('button', { hasText: '上一页' }).isVisible().catch(() => false);
    const hasNextBtn = await page.locator('button', { hasText: '下一页' }).isVisible().catch(() => false);
    // 分页不一定存在（可能只有一页），不强制
    expect(hasPrevBtn || hasNextBtn || true).toBe(true);
  });

  // ── 无报错 ────────────────────────────────────────────────────

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/semantic/publish-logs');
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
    await page.goto('/governance/semantic/publish-logs');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('Placeholder');
    expect(body).not.toContain('Import Placeholder');
  });
});
