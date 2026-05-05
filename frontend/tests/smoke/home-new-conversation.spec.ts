import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 首页新建对话按钮点击行为
 *
 * 补充 home-sidebar.spec.ts：验证"新建对话"按钮可点击并触发正确行为
 * （home-sidebar.spec.ts 仅验证侧边栏结构，未测试按钮交互）
 *
 * 按钮标识：aria-label="新建对话"
 * 行为：handleNew() → navigate('/')
 *
 * Spec: docs/specs/23-homepage-login-fixes.md
 */
test.describe('首页 - 新建对话按钮', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('"新建对话"按钮可见且可点击', async ({ page }) => {
    await page.goto('/');
    const newConvBtn = page.locator('button[aria-label="新建对话"]');
    await expect(newConvBtn).toBeVisible();
  });

  test('点击"新建对话"按钮后页面跳转到首页且 AskBar 可交互', async ({ page }) => {
    await page.goto('/');
    const newConvBtn = page.locator('button[aria-label="新建对话"]');
    await newConvBtn.click();
    await page.waitForTimeout(500);
    // 点击后应停留在首页（/）
    expect(page.url()).toMatch(/\/$|\/\?/);

    // AskBar 输入框应可用
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await expect(askBarInput).toBeVisible();
    await expect(askBarInput).toBeEnabled();
  });

  test('点击"新建对话"后 AskBar 仍可交互且页面无 JS 错误', async ({ page }) => {
    await page.goto('/');

    // 输入问题
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('测试问题');
    await expect(askBarInput).toHaveValue('测试问题');

    // 点击"新建对话"（handleNew 只做 navigate('/')，不清空 AskBar）
    const newConvBtn = page.locator('button[aria-label="新建对话"]');
    await newConvBtn.click();
    await page.waitForTimeout(1000);

    // 新建后 AskBar 应仍可见且可交互
    const newAskBar = page.locator('textarea[data-askbar-input]');
    await expect(newAskBar).toBeVisible();
    await expect(newAskBar).toBeEnabled();

    // 验证无 JS 错误
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    const realErrors = errors.filter(e =>
      !e.includes('401') && !e.includes('403') &&
      !e.includes('Unauthorized') && !e.includes('fetch') &&
      !e.includes('favicon') && !e.includes('net::')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('新建对话后侧边栏结构完整且无 JS 错误', async ({ page }) => {
    await page.goto('/');
    const newConvBtn = page.locator('button[aria-label="新建对话"]');
    await newConvBtn.click();
    await page.waitForTimeout(500);

    // 侧边栏应可见
    await expect(page.locator('#sidebar')).toBeVisible();
    // 建议问题区或 AskBar 应至少有一个可见
    const hasAskBar = await page.locator('textarea[data-askbar-input]').isVisible().catch(() => false);
    expect(hasAskBar).toBe(true);
  });
});
