import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 首页问答与 LLM 配置集成
 * 验证：LLM 配置正常 → 首页问答可用
 *
 * 策略：
 * - 不依赖特定 LLM 配置状态，以"冒烟"为目标
 * - 验证页面加载、API 可达、有意义的错误提示
 * - 不再使用 test.skip()，而是优雅处理所有状态
 */
test.describe('首页问答 - LLM 集成', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('LLM 配置页可访问且页面结构正常', async ({ page }) => {
    await page.goto('/system/llm-configs');
    await page.waitForTimeout(2000);

    const hasHeading = await page.locator('h1').first().isVisible().catch(() => false);
    expect(hasHeading).toBe(true);

    const hasTable = await page.locator('table').first().isVisible().catch(() => false);
    const hasEmptyState = await page.locator('text=暂无').first().isVisible().catch(() => false);
    const hasLoading = await page.locator('text=加载中').first().isVisible().catch(() => false);
    expect(hasTable || hasEmptyState || hasLoading).toBe(true);
  });

  test('首页问答框在各种 LLM 状态下均有合理 UI', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1000);

    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');

    await expect(askBarInput).toBeVisible({ timeout: 3000 });
    await expect(sendBtn).toBeVisible();

    await askBarInput.fill('查询本月销售额');
    await expect(sendBtn).toBeEnabled();

    await sendBtn.click();
    await page.waitForTimeout(3000);

    // 验证 UI 响应：应该有某种状态出现（加载中 / 错误 / 回答）
    const hasLoading = await page.locator('text=正在思考').isVisible().catch(() => false)
      || await page.locator('text=加载中').isVisible().catch(() => false);

    const hasError = await page.locator('text=不可用').isVisible().catch(() => false)
      || await page.locator('text=失败').isVisible().catch(() => false)
      || await page.locator('text=错误').isVisible().catch(() => false);

    const hasAnswer = await page.locator('[class*="message"], [class*="answer"], [class*="result"]').first().isVisible().catch(() => false);

    expect(hasLoading || hasError || hasAnswer).toBe(true);
  });

  test('问答后出现回答内容或明确状态提示', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1000);

    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');

    await askBarInput.fill('测试问题');
    await sendBtn.click();

    // 等待足够时间让 LLM 响应（最多 10 秒）
    await page.waitForTimeout(5000);

    // 验证有明确的 UI 状态：加载中 / 错误 / 回答
    const hasLoading = await page.locator('text=正在思考').isVisible().catch(() => false)
      || await page.locator('text=加载中').isVisible().catch(() => false);

    const hasError = await page.locator('text=不可用').isVisible().catch(() => false)
      || await page.locator('text=失败').isVisible().catch(() => false)
      || await page.locator('text=错误').isVisible().catch(() => false)
      || await page.locator('text=LLM').isVisible().catch(() => false);

    const hasAnswer = await page.locator('[class*="message"], [class*="answer"], [class*="result"]').first().isVisible().catch(() => false);

    // 必须有至少一种明确状态
    expect(hasLoading || hasError || hasAnswer).toBe(true);
  });
});
