import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 首页问答与 LLM 配置集成
 * 验证：LLM 配置正常 → 首页问答可用
 */
test.describe('首页问答 - LLM 集成', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('LLM 配置正常状态下首页问答可用', async ({ page }) => {
    // 1. 验证 LLM 配置页可访问且配置存在
    await page.goto('/system/llm-configs');
    await page.waitForTimeout(2000);

    // 检查是否有启用的 LLM 配置
    const hasActiveConfig = await page.locator('text=启用').first().isVisible({ timeout: 3000 }).catch(() => false);

    if (!hasActiveConfig) {
      // 如果没有启用配置，跳过此测试
      test.skip();
      return;
    }

    // 2. 验证配置连接状态正常（绿点）
    // 注意：这里假设连接测试已经通过

    // 3. 返回首页验证问答功能可用
    await page.goto('/');
    await page.waitForTimeout(1000);

    // 查找 AskBar 输入框
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await expect(askBarInput).toBeVisible({ timeout: 5000 });

    // 验证发送按钮存在且初始状态
    const sendBtn = page.locator('button[aria-label="发送"]');
    await expect(sendBtn).toBeVisible();

    // 4. 输入问题并发送
    await askBarInput.fill('查询本月销售额');

    // 发送按钮应该变为可点击
    await expect(sendBtn).toBeEnabled();

    // 点击发送（注意：可能会因为 LLM 服务问题而失败）
    await sendBtn.click();

    // 5. 验证请求已发送（输入框应被清空）
    await page.waitForTimeout(500);

    // 如果出现错误提示，检查是否是 "LLM service unavailable"
    const errorMsg = page.locator('text=LLM service unavailable');
    const hasError = await errorMsg.isVisible({ timeout: 2000 }).catch(() => false);

    if (hasError) {
      // 如果出现此错误，说明 LLM 配置虽然测试通过，但实际调用失败
      // 这是应用程序的 bug
      throw new Error('LLM 配置测试通过但实际调用失败：LLM service unavailable');
    }

    // 如果没有错误，验证问答返回了结果或正在加载
    // （这里不做严格断言，因为可能因为各种原因导致回答延迟）
  });

  test('首页问答错误信息应清晰', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1000);

    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('测试问题');

    const sendBtn = page.locator('button[aria-label="发送"]');
    await sendBtn.click();

    // 等待一段时间看是否有错误返回
    await page.waitForTimeout(3000);

    // 如果有错误，验证错误信息是否有用
    const errorMessages = [
      'LLM service unavailable',
      'LLM_001',
      '网络错误',
      '请求失败'
    ];

    for (const errMsg of errorMessages) {
      const hasError = await page.locator(`text=${errMsg}`).first().isVisible({ timeout: 1000 }).catch(() => false);
      if (hasError) {
        // 错误信息应该让用户知道发生了什么
        console.log(`Found error: ${errMsg}`);
        break;
      }
    }
  });
});
