import { test, expect, type Page } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 用户管理 - 创建用户
 * 路径：/system/users
 *
 * 测试数据用 `smoke-user-` 前缀，由 globalTeardown 自动清理。
 */

async function login(page: Page) {
  await page.goto('/login');
  await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL('/', { timeout: 5000 });
}

async function openCreateModal(page: Page) {
  await page.goto('/system/users');
  await expect(page.locator('table')).toBeVisible({ timeout: 10000 });
  await page.getByRole('button', { name: /创建用户/i }).click();
  await expect(page.getByRole('heading', { name: '创建新用户' })).toBeVisible({ timeout: 5000 });
}

test.describe('用户管理 - 创建用户', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('必填校验：仅填用户名其他空，提示"请输入显示名称"', async ({ page }) => {
    await openCreateModal(page);
    await page.locator('input[placeholder="用于登录"]').fill('smoke-user-only-name');
    await page.getByRole('button', { name: /^创建$/ }).click();
    await expect(page.locator('text=/请输入显示名称/')).toBeVisible({ timeout: 3000 });
  });

  test('密码长度校验：密码 5 位，提示"密码长度至少为6位"', async ({ page }) => {
    await openCreateModal(page);
    await page.locator('input[placeholder="用于登录"]').fill(`smoke-user-pwd-${Date.now()}`);
    await page.locator('input[placeholder="显示名称"]').fill('短密码用户');
    await page.locator('input[placeholder="至少6位"]').fill('12345');
    await page.locator('input[placeholder="再次输入密码"]').fill('12345');
    await page.getByRole('button', { name: /^创建$/ }).click();
    await expect(page.locator('text=/密码长度至少为6位/')).toBeVisible({ timeout: 3000 });
  });

  test('两次密码不一致：提示"两次输入的密码不一致"', async ({ page }) => {
    await openCreateModal(page);
    await page.locator('input[placeholder="用于登录"]').fill(`smoke-user-mismatch-${Date.now()}`);
    await page.locator('input[placeholder="显示名称"]').fill('密码不一致用户');
    await page.locator('input[placeholder="至少6位"]').fill('123456');
    await page.locator('input[placeholder="再次输入密码"]').fill('654321');
    await page.getByRole('button', { name: /^创建$/ }).click();
    await expect(page.locator('text=/两次输入的密码不一致/')).toBeVisible({ timeout: 3000 });
  });

  test('happy path：创建普通用户成功后列表可见', async ({ page }) => {
    await openCreateModal(page);
    const username = `smoke-user-${Date.now()}`;
    await page.locator('input[placeholder="用于登录"]').fill(username);
    await page.locator('input[placeholder="显示名称"]').fill('Smoke 测试用户');
    await page.locator('input[placeholder="至少6位"]').fill('Test123456');
    await page.locator('input[placeholder="再次输入密码"]').fill('Test123456');
    await page.locator('input[placeholder="example@company.com"]').fill(`${username}@smoke.test`);

    const respPromise = page.waitForResponse(r =>
      r.url().endsWith('/api/users/') && r.request().method() === 'POST',
      { timeout: 5000 },
    );
    await page.getByRole('button', { name: /^创建$/ }).click();
    const resp = await respPromise;
    expect(resp.ok()).toBe(true);

    // 弹窗关闭
    await expect(page.getByRole('heading', { name: '创建新用户' })).not.toBeVisible({ timeout: 3000 });

    // 列表中可见新用户（搜索框过滤 username 后第一行命中）
    await page.locator('input[placeholder="搜索用户名称或邮箱..."]').fill(username);
    await expect(page.locator('tbody tr', { hasText: username })).toBeVisible({ timeout: 3000 });
  });

  test('用户名重复：弹窗保留并显示后端错误', async ({ page }) => {
    // 先创建一个
    await openCreateModal(page);
    const username = `smoke-user-dup-${Date.now()}`;
    await page.locator('input[placeholder="用于登录"]').fill(username);
    await page.locator('input[placeholder="显示名称"]').fill('重复用户测试');
    await page.locator('input[placeholder="至少6位"]').fill('Test123456');
    await page.locator('input[placeholder="再次输入密码"]').fill('Test123456');
    await page.locator('input[placeholder="example@company.com"]').fill(`${username}@smoke.test`);
    await page.getByRole('button', { name: /^创建$/ }).click();
    await expect(page.getByRole('heading', { name: '创建新用户' })).not.toBeVisible({ timeout: 5000 });

    // 再次用同一 username 创建 → 后端 400
    await openCreateModal(page);
    await page.locator('input[placeholder="用于登录"]').fill(username);
    await page.locator('input[placeholder="显示名称"]').fill('重复用户测试2');
    await page.locator('input[placeholder="至少6位"]').fill('Test123456');
    await page.locator('input[placeholder="再次输入密码"]').fill('Test123456');
    await page.locator('input[placeholder="example@company.com"]').fill(`${username}-2@smoke.test`);

    const respPromise = page.waitForResponse(r =>
      r.url().endsWith('/api/users/') && r.request().method() === 'POST',
      { timeout: 5000 },
    );
    await page.getByRole('button', { name: /^创建$/ }).click();
    const resp = await respPromise;
    expect(resp.status()).toBeGreaterThanOrEqual(400);

    // 弹窗保留 + formError 显示
    await expect(page.getByRole('heading', { name: '创建新用户' })).toBeVisible();
    // formError 区域非空（后端 detail 通常包含"已存在"或"已被注册"）
    const errBox = page.locator('div.bg-red-50, div.text-red-700, [class*="red"]').filter({ hasText: /已存在|已被|失败|重复/ }).first();
    await expect(errBox).toBeVisible({ timeout: 3000 });
  });
});
