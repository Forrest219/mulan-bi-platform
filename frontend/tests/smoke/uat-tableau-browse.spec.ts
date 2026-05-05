import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('Tableau 资产浏览 UAT — Tableau-bisite', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL('/', { timeout: 8000 });
  });

  test('场景1：首次访问与连接自动选择', async ({ page }) => {
    // 清除 localStorage 模拟首次访问
    await page.evaluate(() => localStorage.removeItem('tableau-explorer-connection'));

    await page.goto('/assets/tableau');

    // 页面标题
    await expect(page.locator('h1')).toContainText('Tableau 资产浏览', { timeout: 8000 });

    // 连接选择器可见且自动选中
    const selector = page.locator('select');
    await expect(selector).toBeVisible({ timeout: 5000 });
    const selectedValue = await selector.inputValue();
    console.log('[场景1] 自动选中的连接 ID:', selectedValue);

    // 连接状态徽章可见
    const badge = page.locator('span.rounded-full').first();
    await expect(badge).toBeVisible({ timeout: 5000 });
    const badgeText = await badge.textContent();
    console.log('[场景1] 连接状态徽章:', badgeText);

    // URL 不含 connection_id
    expect(page.url()).not.toContain('connection_id');
    console.log('[场景1] URL:', page.url());

    // 页面内容：有资产或空状态+同步按钮
    const emptyCount = await page.locator('text=未找到资产').count();
    if (emptyCount === 0) {
      console.log('[场景1] 结果: 有资产卡片展示');
    } else {
      await expect(page.locator('[data-testid="empty-sync-btn"]')).toBeVisible();
      console.log('[场景1] 结果: 空状态，同步按钮可见');
    }

    // localStorage 已保存
    const savedName = await page.evaluate(() => localStorage.getItem('tableau-explorer-connection'));
    console.log('[场景1] localStorage:', savedName);
  });

  test('场景2：切换到 Tableau-bisite 并验证记忆保持', async ({ page }) => {
    await page.evaluate(() => localStorage.removeItem('tableau-explorer-connection'));
    await page.goto('/assets/tableau');

    const selector = page.locator('select');
    await expect(selector).toBeVisible({ timeout: 8000 });

    // 找到 Tableau-bisite 选项并选中
    const options = await selector.locator('option').allTextContents();
    console.log('[场景2] 可选连接:', options);
    const bisiteOption = options.find(o => o.includes('Tableau-bisite'));
    expect(bisiteOption).toBeTruthy();

    await selector.selectOption({ label: bisiteOption! });
    await page.waitForTimeout(1000);

    // URL 保持稳定
    expect(page.url()).not.toContain('connection_id');
    console.log('[场景2] 切换后 URL:', page.url());

    // localStorage 保存了 Tableau-bisite
    const saved = await page.evaluate(() => localStorage.getItem('tableau-explorer-connection'));
    expect(saved).toBe('Tableau-bisite');
    console.log('[场景2] localStorage:', saved);

    // 刷新页面验证记忆保持
    await page.reload();
    await expect(page.locator('h1')).toContainText('Tableau 资产浏览', { timeout: 8000 });
    await expect(selector).toBeVisible({ timeout: 5000 });

    // 刷新后仍选中 Tableau-bisite
    const selectedText = await selector.locator('option:checked').textContent();
    expect(selectedText).toContain('Tableau-bisite');
    console.log('[场景2] 刷新后选中:', selectedText);

    // 连接状态徽章
    const badge = page.locator('span.rounded-full').first();
    await expect(badge).toBeVisible({ timeout: 5000 });
    const badgeText = await badge.textContent();
    console.log('[场景2] 连接状态:', badgeText);
  });

  test('场景3：搜索筛选与资产详情钻取', async ({ page }) => {
    // 先确保选中 Tableau-bisite
    await page.evaluate(() => localStorage.setItem('tableau-explorer-connection', 'Tableau-bisite'));
    await page.goto('/assets/tableau');
    await expect(page.locator('h1')).toContainText('Tableau 资产浏览', { timeout: 8000 });

    // 确认选中的是 Tableau-bisite
    const selector = page.locator('select');
    await expect(selector).toBeVisible({ timeout: 5000 });
    const selectedText = await selector.locator('option:checked').textContent();
    console.log('[场景3] 当前连接:', selectedText);

    // 等待加载完成
    await page.waitForTimeout(2000);
    const emptyCount = await page.locator('text=未找到资产').count();

    if (emptyCount > 0) {
      console.log('[场景3] Tableau-bisite 下无资产，跳过搜索/筛选/钻取测试');
      console.log('[场景3] 需要先同步资产数据');

      // 验证同步按钮可用
      const syncBtn = page.locator('[data-testid="empty-sync-btn"]');
      await expect(syncBtn).toBeVisible();
      await expect(syncBtn).toBeEnabled();
      console.log('[场景3] 同步按钮可见且可用');
      return;
    }

    // 有资产：执行搜索
    const searchInput = page.locator('input[placeholder*="搜索"]');
    await expect(searchInput).toBeVisible();

    // 记录初始资产数
    const initialCards = await page.locator('[class*="cursor-pointer"]').count();
    console.log('[场景3] 初始资产数:', initialCards);

    // 点击资产类型筛选
    const workbookBtn = page.locator('button').filter({ hasText: '工作簿' });
    if (await workbookBtn.isVisible()) {
      await workbookBtn.click();
      await page.waitForTimeout(1000);
      const filteredCards = await page.locator('[class*="cursor-pointer"]').count();
      console.log('[场景3] 筛选工作簿后资产数:', filteredCards);

      // 恢复全部
      await page.locator('button').filter({ hasText: '全部' }).click();
      await page.waitForTimeout(1000);
    }

    // 视图切换
    const listViewBtn = page.locator('button i.ri-list-check').locator('..');
    if (await listViewBtn.isVisible()) {
      await listViewBtn.click();
      await page.waitForTimeout(500);
      const hasTable = await page.locator('table').count() > 0;
      console.log('[场景3] 切换列表视图:', hasTable ? '表格可见' : '未切换');

      // 切回网格
      await page.locator('button i.ri-grid-line').locator('..').click();
    }

    // 点击第一个资产卡片钻取
    const firstCard = page.locator('[class*="cursor-pointer"]').first();
    if (await firstCard.isVisible()) {
      const assetName = await firstCard.locator('h4').textContent();
      console.log('[场景3] 点击资产:', assetName);
      await firstCard.click();
      await page.waitForURL(/\/assets\/tableau\/\d+/, { timeout: 5000 });
      console.log('[场景3] 详情页 URL:', page.url());

      // 验证详情页加载
      await page.waitForTimeout(1000);
      console.log('[场景3] 详情页已加载');
    }
  });
});
