import { test, expect, type Page } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

const API = process.env.BACKEND_URL || 'http://localhost:8000';

/**
 * Smoke Test: 用户管理 - 配置权限
 * 路径：/system/users
 *
 * 前提：通过 API 创建一个 analyst 角色测试用户。
 */

async function login(page: Page) {
  await page.goto('/login');
  await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL('/', { timeout: 5000 });
}

async function ensureAnalystUser(page: Page, suffix: string): Promise<string> {
  const username = `smoke-user-perm-${suffix}`;
  const create = await page.request.post(`${API}/api/users/`, {
    data: { username, display_name: `权限测试-${suffix}`, password: 'Test123456', role: 'analyst', email: `${username}@smoke.test` },
  });
  if (!create.ok() && create.status() !== 400) {
    throw new Error(`create failed: ${create.status()}`);
  }
  return username;
}

test.describe.configure({ mode: 'serial' });

test.describe('用户管理 - 配置权限', () => {
  const SUFFIX = 'perm';

  test.beforeEach(async ({ page }) => { await login(page); });

  test('配置权限弹窗显示 8 项权限，分析师默认勾选 2 项', async ({ page }) => {
    const username = await ensureAnalystUser(page, SUFFIX);
    await page.goto('/system/users');
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    await page.locator('input[placeholder="搜索用户名称或邮箱..."]').fill(username);
    await page.waitForTimeout(500);

    const row = page.locator('tbody tr', { hasText: username }).first();
    await expect(row).toBeVisible({ timeout: 3000 });

    // 点击权限列徽章按钮
    const permBtn = row.locator('button').filter({ hasText: /^\s*\d+\s*$/ }).first();
    await permBtn.click();

    await expect(page.getByRole('heading', { name: '配置权限' })).toBeVisible({ timeout: 3000 });

    // 8 项权限
    const checkboxes = page.locator('div.bg-white').last().locator('input[type="checkbox"]');
    const count = await checkboxes.count();
    expect(count).toBe(8);

    // analyst 默认 2 项已勾选（scan_logs, tableau）
    const checked = page.locator('div.bg-white').last().locator('input[type="checkbox"]:checked');
    expect(await checked.count()).toBe(2);
  });

  test('保存修改后的权限组合，列表权限列计数更新', async ({ page }) => {
    const username = await ensureAnalystUser(page, SUFFIX);
    await page.goto('/system/users');
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    await page.locator('input[placeholder="搜索用户名称或邮箱..."]').fill(username);
    await page.waitForTimeout(500);

    const row = page.locator('tbody tr', { hasText: username }).first();
    const permBtn = row.locator('button').filter({ hasText: /^\s*\d+\s*$/ }).first();
    await permBtn.click();
    await expect(page.getByRole('heading', { name: '配置权限' })).toBeVisible({ timeout: 3000 });

    // 取消所有现有勾选
    while (true) {
      const checkedNow = page.locator('div.bg-white').last().locator('input[type="checkbox"]:checked');
      const cnt = await checkedNow.count();
      if (cnt === 0) break;
      await checkedNow.first().click();
      await page.waitForTimeout(100);
    }

    // 勾选 "DDL 规范检查"
    await page.locator('label').filter({ hasText: 'DDL 规范检查' }).first().click();

    // 保存 → PUT /api/users/{id}/permissions
    const respPromise = page.waitForResponse(r =>
      r.url().includes('/permissions') && r.request().method() === 'PUT',
      { timeout: 5000 },
    );
    await page.getByRole('button', { name: '保存' }).click();
    const resp = await respPromise;
    expect(resp.ok()).toBe(true);

    // 弹窗关闭
    await expect(page.getByRole('heading', { name: '配置权限' })).not.toBeVisible({ timeout: 3000 });

    // 列表权限列变为 1
    await page.waitForTimeout(800);
    const updatedRow = page.locator('tbody tr', { hasText: username }).first();
    const updatedBtn = updatedRow.locator('button').filter({ hasText: /^\s*\d+\s*$/ }).first();
    const text = await updatedBtn.textContent();
    expect(parseInt(text || '0', 10)).toBe(1);
  });

  test('点击 admin 用户的权限按钮提示"管理员拥有所有权限，无需编辑"', async ({ page }) => {
    await page.goto('/system/users');
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    // admin 行：email 为 admin@mulan.local
    const adminRow = page.locator('tbody tr', { hasText: 'admin@mulan.local' }).first();
    await expect(adminRow).toBeVisible({ timeout: 5000 });
    const fullBtn = adminRow.locator('button').filter({ hasText: '全部' }).first();
    await expect(fullBtn).toBeVisible();
    await fullBtn.click();

    // 应出现"管理员拥有所有权限"提示，弹窗不打开
    await expect(page.locator('text=/管理员拥有所有权限/')).toBeVisible({ timeout: 3000 });
    await expect(page.getByRole('heading', { name: '配置权限' })).not.toBeVisible();
  });
});
