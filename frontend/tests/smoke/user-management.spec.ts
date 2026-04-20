import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';
const TEST_USER_PREFIX = 'smoke_test_user_';
const TEST_DISPLAY_NAME = 'Smoke Test User';

/**
 * Smoke Test: 用户管理页面
 * 路径：/system/users
 */
test.describe('用户管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('用户管理页可访问', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/system/users');
    await expect(page.locator('h1')).toContainText('用户', { timeout: 5000 });
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('fetch') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('页面加载后显示用户列表或空状态', async ({ page }) => {
    await page.goto('/system/users');
    const hasTable = await page.locator('table').first().isVisible().catch(() => false);
    const hasEmptyState = await page.locator('text=暂无').first().isVisible().catch(() => false);
    const hasLoading = await page.locator('text=加载中').first().isVisible().catch(() => false);
    expect(hasTable || hasEmptyState || hasLoading).toBe(true);
  });

  // ── 新增用户 ──────────────────────────────────────────────────

  test('可以新增一个普通用户', async ({ page }) => {
    await page.goto('/system/users');

    // 点击新增按钮
    const addBtn = page.locator('button').filter({ hasText: /新增|添加|创建/i }).first();
    await addBtn.click();

    // 填写表单
    const timestamp = Date.now();
    const username = `${TEST_USER_PREFIX}${timestamp}`;
    const displayName = `${TEST_DISPLAY_NAME} ${timestamp}`;

    await page.locator('input[placeholder="用于登录"]').fill(username);
    await page.locator('input[placeholder="显示名称"]').fill(displayName);
    await page.locator('input[placeholder="至少6位"]').fill('test123456');

    // 选择角色（默认 analyst）
    const roleSelect = page.locator('select').first();
    if (await roleSelect.isVisible().catch(() => false)) {
      await roleSelect.selectOption('analyst');
    }

    // 提交
    const submitBtn = page.locator('button').filter({ hasText: /创建|保存|确定/i }).first();
    await submitBtn.click();

    // 等待用户出现在列表中
    await page.waitForTimeout(1500);
    const userRow = page.locator(`tr`, { hasText: username });
    await expect(userRow).toBeVisible({ timeout: 5000 });

    // 清理：定位到该用户行，再点删除
    const deleteBtn = userRow.locator('button').filter({ hasText: /删除/i }).first();
    await deleteBtn.click();
    await page.waitForTimeout(500);
    // 确认删除
    const confirmBtn = page.locator('button').filter({ hasText: /确定|删除|确认/i }).first();
    await confirmBtn.click();
    await page.waitForTimeout(500);
    // 验证该用户已不在列表中
    await expect(userRow).not.toBeVisible({ timeout: 3000 });
  });

  // ── 搜索 ──────────────────────────────────────────────────────

  test('搜索框可输入并触发过滤', async ({ page }) => {
    await page.goto('/system/users');
    await page.waitForTimeout(2000);

    const searchInput = page.locator('input[placeholder*="搜索"]');
    await expect(searchInput).toBeVisible();
    await searchInput.fill('admin');
    await page.waitForTimeout(500);
    // 列表中应包含 admin
    const hasAdmin = await page.locator('text=admin').first().isVisible().catch(() => false);
    expect(hasAdmin).toBe(true);
  });

  // ── 编辑用户 ──────────────────────────────────────────────────

  test('可以编辑已有用户的显示名', async ({ page }) => {
    await page.goto('/system/users');
    await page.waitForTimeout(2000);

    // 创建测试用户
    const addBtn = page.locator('button').filter({ hasText: /新增|添加|创建/i }).first();
    await addBtn.click();
    const timestamp = Date.now();
    const username = `${TEST_USER_PREFIX}edit_${timestamp}`;
    const displayName = `${TEST_DISPLAY_NAME} ${timestamp}`;
    await page.locator('input[placeholder="用于登录"]').fill(username);
    await page.locator('input[placeholder="显示名称"]').fill(displayName);
    await page.locator('input[placeholder="至少6位"]').fill('test123456');
    const submitBtn = page.locator('button').filter({ hasText: /创建|保存|确定/i }).first();
    await submitBtn.click();
    await page.waitForTimeout(1500);

    // 找到该用户行并编辑
    const userRow = page.locator(`tr`, { hasText: username });
    await expect(userRow).toBeVisible();
    const editBtn = userRow.locator('button').filter({ hasText: /编辑/i }).first();
    await editBtn.click();
    await page.waitForTimeout(500);

    const displayInput = page.locator('input[placeholder="显示名称"]');
    await displayInput.clear();
    const newDisplayName = `Smoke Updated ${timestamp}`;
    await displayInput.fill(newDisplayName);
    const saveBtn = page.locator('button').filter({ hasText: /保存|确定/i }).first();
    await saveBtn.click();
    await page.waitForTimeout(1000);

    // 验证更新后的显示名
    await expect(page.locator(`text=${newDisplayName}`).first()).toBeVisible();

    // 清理：删除测试用户
    const deleteBtn = userRow.locator('button').filter({ hasText: /删除/i }).first();
    await deleteBtn.click();
    await page.waitForTimeout(500);
    const confirmBtn = page.locator('button').filter({ hasText: /确定|删除|确认/i }).first();
    await confirmBtn.click();
    await page.waitForTimeout(500);
  });

  // ── 禁用/启用 ─────────────────────────────────────────────────

  test('可以禁用再启用一个用户', async ({ page }) => {
    await page.goto('/system/users');
    await page.waitForTimeout(2000);

    // 创建测试用户
    const addBtn = page.locator('button').filter({ hasText: /新增|添加|创建/i }).first();
    await addBtn.click();
    const timestamp = Date.now();
    const username = `${TEST_USER_PREFIX}toggle_${timestamp}`;
    await page.locator('input[placeholder="用于登录"]').fill(username);
    await page.locator('input[placeholder="显示名称"]').fill(`Toggle User ${timestamp}`);
    await page.locator('input[placeholder="至少6位"]').fill('test123456');
    const submitBtn = page.locator('button').filter({ hasText: /创建|保存|确定/i }).first();
    await submitBtn.click();
    await page.waitForTimeout(1500);

    const userRow = page.locator(`tr`, { hasText: username });
    await expect(userRow).toBeVisible();

    // 找启用/禁用按钮
    const toggleBtn = userRow.locator('button').filter({ hasText: /禁用|启用/i }).first();
    const btnText = await toggleBtn.textContent();
    await toggleBtn.click();
    await page.waitForTimeout(500);

    // 按钮文字应变为相反操作
    const oppositeText = btnText?.includes('禁用') ? '启用' : '禁用';
    const newBtn = userRow.locator('button').filter({ hasText: new RegExp(oppositeText) }).first();
    await expect(newBtn).toBeVisible();

    // 清理：恢复状态并删除
    if (btnText?.includes('启用')) {
      // 用户现在是启用状态，再点一次禁用
      await newBtn.click();
      await page.waitForTimeout(500);
    }
    const deleteBtn = userRow.locator('button').filter({ hasText: /删除/i }).first();
    await deleteBtn.click();
    await page.waitForTimeout(500);
    const confirmBtn = page.locator('button').filter({ hasText: /确定|删除|确认/i }).first();
    await confirmBtn.click();
    await page.waitForTimeout(500);
  });
});
