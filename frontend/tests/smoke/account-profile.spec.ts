import { test, expect } from '@playwright/test';

/**
 * Smoke Test: 个人中心 /account/profile
 *
 * 场景：
 * 1. 页面可访问，表单字段渲染正常
 * 2. 修改姓名并保存 → 成功 toast 出现且新姓名写入 DOM
 * 3. 刷新页面 → 新姓名持久化（验证后端真实落库）
 */

const ADMIN_USER = process.env.SMOKE_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.SMOKE_ADMIN_PASSWORD ?? 'admin123';

const ORIGINAL_NAME = 'admin';       // 恢复用
const TEST_NAME = '张星辰_smoke';    // 唯一前缀避免与真实数据混淆

async function login(page: any) {
  await page.goto('/login');
  await page.getByPlaceholder('用户名').fill(ADMIN_USER);
  await page.getByPlaceholder('密码').fill(ADMIN_PASS);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('/', { timeout: 8000 });
}

test.describe('个人中心', () => {

  test.afterAll(async ({ browser }) => {
    // 恢复姓名，避免影响其他测试
    const page = await browser.newPage();
    await login(page);
    await page.goto('/account/profile');
    await page.waitForLoadState('networkidle');
    const nameInput = page.locator('input[placeholder="请输入姓名"]');
    await nameInput.fill(ORIGINAL_NAME);
    await page.getByRole('button', { name: '保存修改' }).click();
    await page.close();
  });

  test('场景A：页面可访问，表单字段全部渲染', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await login(page);
    await page.goto('/account/profile');
    await page.waitForLoadState('networkidle');

    // 标题
    await expect(page.locator('h1')).toContainText('个人中心');

    // 表单字段
    await expect(page.locator('input[placeholder="请输入姓名"]')).toBeVisible();
    await expect(page.locator('input[placeholder="如：BI 总监"]')).toBeVisible();
    await expect(page.locator('input[placeholder="如：BI 中心"]')).toBeVisible();
    await expect(page.locator('input[placeholder="请输入企业邮箱"]')).toBeVisible();

    // 保存按钮
    await expect(page.getByRole('button', { name: '保存修改' })).toBeVisible();

    const realErrors = errors.filter(e =>
      !e.includes('401') && !e.includes('403') &&
      !e.includes('fetch') && !e.includes('favicon') &&
      !e.includes('net::ERR') && !e.includes('Failed to load resource')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('场景B：修改姓名并保存 → 成功 toast 且新姓名写入 DOM', async ({ page }) => {
    await login(page);
    await page.goto('/account/profile');
    await page.waitForLoadState('networkidle');

    const nameInput = page.locator('input[placeholder="请输入姓名"]');
    await nameInput.fill(TEST_NAME);

    await page.getByRole('button', { name: '保存修改' }).click();

    // 成功 toast
    await expect(page.locator('text=个人信息已保存')).toBeVisible({ timeout: 5000 });

    // 新姓名出现在 DOM（头像区域的姓名展示）
    await expect(page.locator(`text=${TEST_NAME}`).first()).toBeVisible();
  });

  test('场景C：刷新页面后新姓名持久化', async ({ page }) => {
    await login(page);
    await page.goto('/account/profile');
    await page.waitForLoadState('networkidle');

    // 先保存新姓名（与场景B独立，避免依赖顺序）
    const nameInput = page.locator('input[placeholder="请输入姓名"]');
    await nameInput.fill(TEST_NAME);
    await page.getByRole('button', { name: '保存修改' }).click();
    await expect(page.locator('text=个人信息已保存')).toBeVisible({ timeout: 5000 });

    // 刷新
    await page.reload();
    await page.waitForLoadState('networkidle');

    // input 值持久化
    await expect(nameInput).toHaveValue(TEST_NAME, { timeout: 5000 });
  });

});
