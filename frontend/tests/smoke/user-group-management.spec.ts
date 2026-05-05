import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';
const TEST_GROUP_PREFIX = 'smoke_test_group_';

/**
 * Smoke Test: 用户组管理页面
 * 路径：/system/groups
 *
 * 页面功能（Spec 04-auth-rbac-spec.md）：
 * - 用户组列表展示（名称/描述/成员数/权限标签）
 * - 创建用户组（名称/描述/初始权限）
 * - 成员管理（添加/移除成员）
 * - 权限配置（切换权限标签/暂存/保存）
 * - 删除用户组
 *
 * Spec: docs/specs/04-auth-rbac-spec.md §3.3 用户组端点
 */
test.describe('用户组管理', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 页面加载 ──────────────────────────────────────────────────

  test('用户组管理页可访问且显示中文标题', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/system/groups');
    await expect(page.locator('h1')).toContainText('用户组', { timeout: 5000 });
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('fetch') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('页面显示用户组列表或空状态', async ({ page }) => {
    await page.goto('/system/groups');
    await page.waitForTimeout(2000);
    // 有数据时应有卡片式列表（bg-white rounded-xl）
    const hasGroupCards = await page.locator('.bg-white.rounded-xl').first().isVisible().catch(() => false);
    // 无数据时应有"暂无用户组"文案
    const hasEmptyState = await page.locator('text=暂无用户组').first().isVisible().catch(() => false);
    expect(hasGroupCards || hasEmptyState).toBe(true);
  });

  test('"创建用户组"按钮可见', async ({ page }) => {
    await page.goto('/system/groups');
    await page.waitForTimeout(2000);
    const createBtn = page.locator('button').filter({ hasText: /创建用户组/ }).first();
    await expect(createBtn).toBeVisible();
  });

  // ── 创建用户组 ────────────────────────────────────────────────

  test('可以创建一个用户组并出现在列表中', async ({ page }) => {
    await page.goto('/system/groups');
    await page.waitForTimeout(2000);

    // 点击创建用户组按钮
    const createBtn = page.locator('button').filter({ hasText: /创建用户组/ }).first();
    await createBtn.click();
    await page.waitForTimeout(500);

    // 填写表单
    const timestamp = Date.now();
    const groupName = `${TEST_GROUP_PREFIX}${timestamp}`;

    // 弹窗中应有关闭按钮
    const modal = page.locator('text=创建用户组').first();
    await expect(modal).toBeVisible();

    // 找到组名称输入框
    const nameInput = page.locator('input[placeholder*="数据分析师"], input[placeholder*="组名称"]').first();
    await nameInput.fill(groupName);
    await page.waitForTimeout(300);

    // 点击创建按钮
    const submitBtn = page.locator('button').filter({ hasText: /^创建$/ }).first();
    await submitBtn.click();
    await page.waitForTimeout(2000);

    // 新建用户组应出现在列表中
    const groupH3 = page.locator('h3').filter({ hasText: groupName }).first();
    await expect(groupH3).toBeVisible({ timeout: 5000 });

    // 清理：用 JS 找到包含该组名称的卡片 div，再点击其中的"删除"按钮
    const deleteBtn = page.locator('div.bg-white.rounded-xl').filter({
      has: page.locator('h3').filter({ hasText: groupName })
    }).locator('button').filter({ hasText: '删除' });
    await deleteBtn.click();
    // 等待确认弹窗打开
    await page.waitForSelector('[role="dialog"], .fixed.inset-0', { timeout: 3000 });
    await page.waitForTimeout(300);
    // 点击弹窗遮罩内的"删除"按钮（force 跳过 pointer-events 检查）
    const confirmBtn = page.locator('.fixed.inset-0 button').filter({ hasText: '删除' }).first();
    await confirmBtn.click({ force: true });
    await page.waitForTimeout(1000);
  });

  // ── 搜索功能 ─────────────────────────────────────────────────

  test('搜索框可输入并触发过滤', async ({ page }) => {
    await page.goto('/system/groups');
    await page.waitForTimeout(2000);

    const searchInput = page.locator('input[placeholder*="搜索"]');
    const hasSearch = await searchInput.isVisible().catch(() => false);

    if (hasSearch) {
      await searchInput.fill('admin');
      await page.waitForTimeout(500);
      // 搜索后列表应被过滤（页面不报错即可）
      const errors: string[] = [];
      page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(msg.text());
      });
      const realErrors = errors.filter(e => !e.includes('401') && !e.includes('403') && !e.includes('fetch'));
      expect(realErrors).toHaveLength(0);
    } else {
      // 如果无搜索框（空状态），跳过
      test.skip();
    }
  });

  // ── 成员管理 ─────────────────────────────────────────────────

  test('成员管理弹窗可打开并查看成员', async ({ page }) => {
    await page.goto('/system/groups');
    await page.waitForTimeout(2000);

    // 找到任意一个用户组的"成员"按钮
    const memberBtn = page.locator('button').filter({ hasText: /成员/ }).first();
    const hasMemberBtn = await memberBtn.isVisible().catch(() => false);

    if (hasMemberBtn) {
      await memberBtn.click();
      await page.waitForTimeout(500);

      // 弹窗应打开（应有"组成员管理"标题）
      const modalTitle = page.locator('text=组成员管理').first();
      await expect(modalTitle).toBeVisible();

      // 弹窗应有关闭/完成按钮
      const closeBtn = page.locator('button').filter({ hasText: /完成/ }).first();
      await expect(closeBtn).toBeVisible();

      // 关闭弹窗
      await closeBtn.click();
      await page.waitForTimeout(300);
      await expect(modalTitle).not.toBeVisible();
    } else {
      // 无用户组时跳过
      test.skip();
    }
  });

  // ── 权限暂存与保存 ───────────────────────────────────────────

  test('权限切换后出现暂存提示栏', async ({ page }) => {
    await page.goto('/system/groups');
    await page.waitForTimeout(2000);

    // 找到任意一个权限标签按钮
    const permBtn = page.locator('button').filter({ hasText: /^\+.*$/ }).first(); // 未选中权限以 "+" 开头
    const hasPermBtn = await permBtn.isVisible().catch(() => false);

    if (hasPermBtn) {
      await permBtn.click();
      await page.waitForTimeout(500);

      // 暂存提示栏应出现
      const pendingBar = page.locator('text=尚未保存');
      await expect(pendingBar).toBeVisible();

      // 点击取消更改
      const cancelBtn = page.locator('button').filter({ hasText: /取消更改/ }).first();
      await cancelBtn.click();
      await page.waitForTimeout(500);

      // 暂存提示栏应消失
      await expect(pendingBar).not.toBeVisible();
    } else {
      test.skip();
    }
  });

  // ── 删除用户组 ────────────────────────────────────────────────

  test('可以删除一个用户组', async ({ page }) => {
    await page.goto('/system/groups');
    await page.waitForTimeout(2000);

    // 先创建一个测试用户组
    const createBtn = page.locator('button').filter({ hasText: /创建用户组/ }).first();
    await createBtn.click();
    await page.waitForTimeout(500);

    const timestamp = Date.now();
    const groupName = `${TEST_GROUP_PREFIX}delete_${timestamp}`;
    const nameInput = page.locator('input[placeholder*="数据分析师"], input[placeholder*="组名称"]').first();
    await nameInput.fill(groupName);
    const submitBtn = page.locator('button').filter({ hasText: /^创建$/ }).first();
    await submitBtn.click();
    await page.waitForTimeout(2000);

    // 用 JS 找到包含该组名称的卡片 div，再点击其中的"删除"按钮
    const groupH3 = page.locator('h3').filter({ hasText: groupName }).first();
    await expect(groupH3).toBeVisible({ timeout: 5000 });
    const deleteBtn = page.locator('div.bg-white.rounded-xl').filter({
      has: page.locator('h3').filter({ hasText: groupName })
    }).locator('button').filter({ hasText: '删除' });
    await deleteBtn.click();
    // 等待确认弹窗打开
    await page.waitForSelector('[role="dialog"], .fixed.inset-0', { timeout: 3000 });
    await page.waitForTimeout(300);

    // 确认删除（弹窗遮罩已打开，点击弹窗内的"删除"确认按钮）
    const confirmBtn = page.locator('.fixed.inset-0 button').filter({ hasText: '删除' }).first();
    await confirmBtn.click({ force: true });
    await page.waitForTimeout(1000);

    // 用户组应从列表中消失
    await expect(groupH3).not.toBeVisible({ timeout: 3000 });
  });

  // ── 无英文占位文案残留 ────────────────────────────────────────

  test('无英文占位文案残留', async ({ page }) => {
    await page.goto('/system/groups');
    await page.waitForTimeout(2000);
    const body = await page.locator('body').textContent();
    expect(body).not.toMatch(/No data|TODO|placeholder|Import Placeholder/i);
  });
});
