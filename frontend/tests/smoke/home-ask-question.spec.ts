import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 首页问答功能
 * 路径：/
 */
test.describe('首页 - 问答功能', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('首页显示问答输入框', async ({ page }) => {
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await expect(askBarInput).toBeVisible();
  });

  test('发送问题后出现加载或回答状态', async ({ page }) => {
    await page.goto('/');

    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');

    await askBarInput.fill('查询销售额最高的产品');
    await sendBtn.click();

    // 等待 UI 响应：要么出现加载状态，要么出现回答内容
    // 使用 loading 出现再消失的策略，等待 LLM 响应
    await page.waitForTimeout(2000);

    const hasLoading = await page.locator('text=正在思考').isVisible().catch(() => false)
      || await page.locator('text=加载中').isVisible().catch(() => false);

    const hasError = await page.locator('text=LLM').isVisible().catch(() => false)
      && await page.locator('text=不可用').isVisible().catch(() => false);

    // 至少要有一种状态：加载中 / 回答内容 / 错误提示
    // 如果 2 秒后什么都没有，说明 UI 有问题
    const hasAnswerArea = await page.locator('[class*="message"], [class*="answer"], [class*="result"]').first().isVisible().catch(() => false);
    expect(hasLoading || hasError || hasAnswerArea).toBe(true);
  });

  test('回车键可以发送问题', async ({ page }) => {
    await page.goto('/');

    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('查询本月收入');
    await askBarInput.press('Enter');

    // 输入框应被清空
    await expect(askBarInput).toHaveValue('');
  });

  test('发送后输入框被清空', async ({ page }) => {
    await page.goto('/');

    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');

    await askBarInput.fill('测试问题');
    await sendBtn.click();

    // 无论结果如何，输入框都应清空
    await expect(askBarInput).toHaveValue('');
  });
});
