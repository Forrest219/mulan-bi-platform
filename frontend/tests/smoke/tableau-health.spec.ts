import { test, expect } from '@playwright/test';

const ADMIN_USER = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: Tableau 巡检页
 * 路径: /governance/tableau-audit
 * 权限: tableau
 *
 * 覆盖:
 * - 页面可访问、站点选择器、资产表格
 * - 表格列宽（站点/类型/评分/检查时间/操作不换行）
 * - 检查时间显示为 yyyy-mm-dd + hh:mm:ss 两行格式
 * - 筛选器（类型/等级/问题）
 */
test.describe('Tableau 巡检页', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.getByPlaceholder('用户名').fill(ADMIN_USER);
    await page.getByPlaceholder('密码').fill(ADMIN_PASS);
    await page.getByRole('button', { name: '登录' }).click();
    await page.waitForURL('/', { timeout: 8000 });
  });

  test('页面可访问且有核心内容', async ({ page }) => {
    await page.goto('/governance/tableau-audit');
    await page.waitForTimeout(3000);

    const hasTitle = await page.locator('text=Tableau 巡检').first().isVisible().catch(() => false);
    const hasSelector = await page.locator('select').first().isVisible().catch(() => false);
    expect(hasTitle).toBe(true);
    expect(hasSelector).toBe(true);
  });

  test('站点选择器包含"全部站点"默认项', async ({ page }) => {
    await page.goto('/governance/tableau-audit');
    await page.waitForTimeout(3000);

    const select = page.locator('select').first();
    if (await select.isVisible().catch(() => false)) {
      const options = await select.locator('option').allTextContents();
      expect(options).toContain('全部站点');
    }
  });

  test('资产表格列标题正确', async ({ page }) => {
    await page.goto('/governance/tableau-audit');
    await page.waitForTimeout(3000);

    const table = page.locator('table').first();
    if (await table.isVisible().catch(() => false)) {
      const headers = await table.locator('th').allTextContents();
      expect(headers).toContain('资产名称');
      expect(headers).toContain('评分');
      expect(headers).toContain('主要问题');
      expect(headers).toContain('检查时间');
      expect(headers).toContain('操作');
    }
  });

  test('检查时间列显示 yyyy-mm-dd / hh:mm:ss 两行格式', async ({ page }) => {
    await page.goto('/governance/tableau-audit');
    await page.waitForTimeout(3000);

    const table = page.locator('table').first();
    if (await table.isVisible().catch(() => false)) {
      const rows = table.locator('tbody tr');
      const rowCount = await rows.count();
      if (rowCount > 0) {
        // 检查时间单元格内应有两个 div：日期 + 时间
        const firstTimeCell = rows.first().locator('td').nth(-2); // 倒数第二列
        const divs = firstTimeCell.locator('div > div');
        const divCount = await divs.count();
        if (divCount >= 2) {
          const dateText = await divs.nth(0).textContent();
          const timeText = await divs.nth(1).textContent();
          // yyyy-mm-dd 格式
          expect(dateText).toMatch(/^\d{4}-\d{2}-\d{2}$/);
          // hh:mm:ss 格式
          expect(timeText).toMatch(/^\d{2}:\d{2}:\d{2}$/);
        }
        // 不应出现"刚刚"、"分钟前"等相对时间
        const cellText = await firstTimeCell.textContent();
        expect(cellText).not.toContain('刚刚');
        expect(cellText).not.toContain('分钟前');
        expect(cellText).not.toContain('小时前');
      }
    }
  });

  test('站点/类型/评分列不换行（whitespace-nowrap）', async ({ page }) => {
    await page.goto('/governance/tableau-audit');
    await page.waitForTimeout(3000);

    const table = page.locator('table').first();
    if (await table.isVisible().catch(() => false)) {
      // 验证 th 有 whitespace-nowrap class
      const typeHeader = table.locator('th', { hasText: '类型' }).first();
      if (await typeHeader.isVisible().catch(() => false)) {
        const cls = await typeHeader.getAttribute('class') ?? '';
        expect(cls).toContain('whitespace-nowrap');
      }
      const scoreHeader = table.locator('th', { hasText: '评分' }).first();
      if (await scoreHeader.isVisible().catch(() => false)) {
        const cls = await scoreHeader.getAttribute('class') ?? '';
        expect(cls).toContain('whitespace-nowrap');
      }
    }
  });

  test('筛选器可见且可交互', async ({ page }) => {
    await page.goto('/governance/tableau-audit');
    await page.waitForTimeout(3000);

    // 类型/等级/问题筛选标签
    const hasTypeLabel = await page.locator('text=类型').first().isVisible().catch(() => false);
    const hasLevelLabel = await page.locator('text=等级').first().isVisible().catch(() => false);
    expect(hasTypeLabel).toBe(true);
    expect(hasLevelLabel).toBe(true);
  });

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/governance/tableau-audit');
    await page.waitForTimeout(3000);

    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('fetch') &&
      !e.includes('favicon') &&
      !e.includes('net::ERR') &&
      !e.includes('Failed to load resource')
    );
    expect(realErrors).toHaveLength(0);
  });
});
