import { test, expect } from '@playwright/test';

const ADMIN_USER = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * 规则配置页面冒烟测试
 * 路由: /dev/rule-config
 * 权限: 需要 rule_config 权限
 *
 * 页面功能:
 * - 规则列表展示（名称、类型、级别、状态）
 * - 分类筛选 (Naming/Structure/Type/Index/Audit)
 * - 级别筛选 (HIGH/MEDIUM/LOW)
 * - 搜索
 * - 新建规则 Modal
 * - 启用/禁用切换
 */
test.describe('规则配置', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.getByPlaceholder('用户名').fill(ADMIN_USER);
    await page.getByPlaceholder('密码').fill(ADMIN_PASS);
    await page.getByRole('button', { name: '登录' }).click();
    await page.waitForURL('/', { timeout: 8000 });
  });

  test('规则配置页可访问', async ({ page }) => {
    await page.goto('/dev/rule-config', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // 验证页面不是 404
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
    // 验证页面有内容（标题或规则相关元素）
    const hasContent = await page.locator('h1').first().isVisible().catch(() => false)
      || await page.locator('text=规则').first().isVisible().catch(() => false);
    expect(hasContent).toBe(true);
  });

  test('规则列表或空状态显示', async ({ page }) => {
    await page.goto('/dev/rule-config', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // 规则列表/表格 或 空状态
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').isVisible().catch(() => false)
      || await page.locator('text=没有').isVisible().catch(() => false);
    expect(hasTable || hasEmpty).toBe(true);
  });

  test('分类筛选标签可见', async ({ page }) => {
    await page.goto('/dev/rule-config', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // 分类标签: ALL, Naming, Structure, Type, Index, Audit
    const categoryLabels = ['Naming', 'Structure', 'Type', 'Index', 'Audit'];
    let foundCount = 0;
    for (const cat of categoryLabels) {
      const btn = page.locator('button').filter({ hasText: cat }).first();
      if (await btn.isVisible().catch(() => false)) foundCount++;
    }
    // 至少有一些分类按钮可见
    expect(foundCount).toBeGreaterThan(0);
  });

  test('级别筛选标签可见', async ({ page }) => {
    await page.goto('/dev/rule-config', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // 级别标签: HIGH, MEDIUM, LOW
    const levelLabels = ['HIGH', 'MEDIUM', 'LOW'];
    let foundCount = 0;
    for (const level of levelLabels) {
      const btn = page.locator('button').filter({ hasText: level }).first();
      if (await btn.isVisible().catch(() => false)) foundCount++;
    }
    expect(foundCount).toBeGreaterThan(0);
  });

  test('新建规则按钮或入口存在', async ({ page }) => {
    await page.goto('/dev/rule-config', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // 新建按钮
    const newBtn = page.locator('button').filter({ hasText: /新建|新增|添加|创建/ }).first();
    const hasNewBtn = await newBtn.isVisible().catch(() => false);

    // 或者页面显示规则（说明已有数据）
    const hasRules = await page.locator('table').isVisible().catch(() => false)
      || await page.locator('text=Naming').isVisible().catch(() => false)
      || await page.locator('text=Structure').isVisible().catch(() => false);

    expect(hasNewBtn || hasRules).toBe(true);
  });

  test('切换分类筛选', async ({ page }) => {
    await page.goto('/dev/rule-config', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // 点击 Naming 分类
    const namingBtn = page.locator('button').filter({ hasText: 'Naming' }).first();
    const hasNaming = await namingBtn.isVisible().catch(() => false);
    if (hasNaming) {
      await namingBtn.click();
      await page.waitForTimeout(500);
      // 再次点击 ALL 恢复
      const allBtn = page.locator('button').filter({ hasText: 'ALL' }).first();
      await allBtn.click();
    } else {
      // 如果没有 Naming 按钮，检查是否有其他分类
      const structBtn = page.locator('button').filter({ hasText: 'Structure' }).first();
      if (await structBtn.isVisible().catch(() => false)) {
        await structBtn.click();
        await page.waitForTimeout(500);
      }
    }
    // 筛选后页面无报错
    const hasError = await page.locator('text=Page Not Found').isVisible().catch(() => false);
    expect(hasError).toBe(false);
  });

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/dev/rule-config', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    const body = await page.locator('body').textContent();
    expect(body).not.toContain('TODO');
    expect(body).not.toContain('PLACEHOLDER');
    expect(body).not.toContain('FIXME');
  });

  test('无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/dev/rule-config', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

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
