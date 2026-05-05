import { test, expect, type Page } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

const API = process.env.BACKEND_URL || 'http://localhost:8000';

async function login(page: Page) {
  await page.goto('/login');
  await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL('/', { timeout: 5000 });
}

async function ensureTestUser(page: Page, suffix: string): Promise<string> {
  const username = `smoke-user-role-${suffix}`;
  const res = await page.request.post(`${API}/api/users/`, {
    data: { username, display_name: `切换角色-${suffix}`, password: 'Test123456', role: 'user', email: `${username}@smoke.test` },
  });
  if (!res.ok() && res.status() !== 400) {
    throw new Error(`ensureTestUser failed: ${res.status()}`);
  }
  return username;
}

async function switchRoleAndWait(page: Page, row: ReturnType<Page['locator']>, targetRole: string) {
  const roleSelect = row.locator('select');
  const putPromise = page.waitForResponse(r =>
    r.url().includes('/role') && r.request().method() === 'PUT', { timeout: 5000 });
  const getPromise = page.waitForResponse(r =>
    r.url().includes('/api/users') && r.request().method() === 'GET', { timeout: 5000 });
  await roleSelect.selectOption(targetRole);
  const resp = await putPromise;
  expect(resp.ok()).toBe(true);
  await getPromise;
  await page.waitForTimeout(300);
}

test.describe.configure({ mode: 'serial' });

test.describe('用户管理 - 切换角色', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('将用户从普通用户切换为业务分析师，角色下拉值更新', async ({ page }) => {
    const username = await ensureTestUser(page, 'switch-a');
    await page.goto('/system/users');
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    await page.locator('input[placeholder="搜索用户名称或邮箱..."]').fill(username);
    await page.waitForTimeout(500);

    const row = page.locator('tbody tr', { hasText: username }).first();
    await expect(row).toBeVisible({ timeout: 3000 });

    await switchRoleAndWait(page, row, 'analyst');

    await page.locator('input[placeholder="搜索用户名称或邮箱..."]').fill(username);
    await page.waitForTimeout(500);

    const updatedRow = page.locator('tbody tr', { hasText: username }).first();
    const currentRole = await updatedRow.locator('select').inputValue();
    expect(currentRole).toBe('analyst');
  });

  test('角色切换为数据管理员，下拉值更新为 data_admin', async ({ page }) => {
    const username = await ensureTestUser(page, 'switch-b');
    await page.goto('/system/users');
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    await page.locator('input[placeholder="搜索用户名称或邮箱..."]').fill(username);
    await page.waitForTimeout(500);

    const row = page.locator('tbody tr', { hasText: username }).first();
    await expect(row).toBeVisible({ timeout: 3000 });

    await switchRoleAndWait(page, row, 'data_admin');

    await page.locator('input[placeholder="搜索用户名称或邮箱..."]').fill(username);
    await page.waitForTimeout(500);

    const updatedRow = page.locator('tbody tr', { hasText: username }).first();
    const currentRole = await updatedRow.locator('select').inputValue();
    expect(currentRole).toBe('data_admin');
  });

  test('admin 行角色下拉默认为 admin', async ({ page }) => {
    await page.goto('/system/users');
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    const adminRow = page.locator('tbody tr', { hasText: 'admin@mulan.local' }).first();
    await expect(adminRow).toBeVisible({ timeout: 5000 });
    const adminRole = await adminRow.locator('select').inputValue();
    expect(adminRole).toBe('admin');
  });
});
